"""Task-owned real-browser fetcher built on Patchright over CDP.

The static runtime uses ``ScraplingFetcher`` (curl_cffi).  This module adds a
real Chromium/Chrome path for rules that declare ``fetch.default_engine:
browser`` or a browser override in ``fetch.per_url_type``.

Design boundaries:

- The browser is launched as a child process with a task-owned profile
  directory.  Both the process and the profile are registered in
  ``task_resources`` so a normal finish, a cancel, or a crashed worker's lease
  takeover can clean them up.
- Playwright's sync API is thread-affine.  The fetcher is created and used in
  the task thread, and ``thread_affine`` tells ``TaskRunner`` to process items
  inline instead of handing them to a thread pool.
- One browser and one page are reused for the whole task.  Requests are
  serialized by a lock; this is deliberate for the first adapter version.
- No login, paywall, challenge solving or fingerprint bypass is attempted.
  ``challenge_wait_ms`` only allows a bounded wait when a human is watching a
  headful browser.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

from .fetcher import DomainLimiter
from .models import FetchResult
from .resources import register_path, register_process, terminate_process
from .store import TaskStore

DEFAULT_PROFILE_NAME = "browser-profile"
CHALLENGE_TITLE_MARKERS = (
    "just a moment",
    "attention required",
    "access denied",
    "access to this page has been denied",
    "verify you are human",
    "checking your browser",
    "press & hold",
    "enable javascript and cookies to continue",
)
SUPPORTED_WAIT_UNTIL = {"commit", "domcontentloaded", "load", "networkidle"}
SUPPORTED_SELECTOR_STATES = {"attached", "detached", "hidden", "visible"}

logger = logging.getLogger(__name__)


class BrowserLaunchError(RuntimeError):
    """The browser could not be started or connected."""


@dataclass(frozen=True)
class LaunchOptions:
    headless: bool = True
    real_chrome: bool = False
    executable_path: str | None = None
    extra_flags: tuple[str, ...] = ()
    user_agent: str | None = None
    locale: str | None = None
    timezone: str | None = None
    proxy: str | None = None
    challenge_wait_ms: int = 0


@dataclass(frozen=True)
class PageOptions:
    wait_until: str = "domcontentloaded"
    wait_selector: str | None = None
    wait_selector_state: str = "attached"
    wait_ms: int = 0
    network_idle: bool = False
    network_idle_timeout_ms: int = 5000
    disable_resources: bool = False
    timeout_ms: int = 45000


@dataclass(frozen=True)
class BrowserConfig:
    launch: LaunchOptions = field(default_factory=LaunchOptions)
    page: PageOptions = field(default_factory=PageOptions)
    page_by_type: dict[str, PageOptions] = field(default_factory=dict)
    profile_name: str = DEFAULT_PROFILE_NAME

    @classmethod
    def from_fetch(cls, fetch: dict[str, Any]) -> BrowserConfig:
        raw = fetch.get("browser")
        browser = raw if isinstance(raw, dict) else {}
        timeout_ms = _positive_int(
            browser.get("timeout_ms", fetch.get("timeout_ms", 45000)), 45000
        )
        base_page = PageOptions(
            wait_until=_wait_until(browser.get("wait_until")),
            wait_selector=_optional_string(browser.get("wait_selector")),
            wait_selector_state=_selector_state(browser.get("wait_selector_state")),
            wait_ms=_non_negative_int(browser.get("wait_ms"), 0),
            network_idle=bool(browser.get("network_idle", False)),
            network_idle_timeout_ms=_positive_int(
                browser.get("network_idle_timeout_ms"), 5000
            ),
            disable_resources=bool(browser.get("disable_resources", False)),
            timeout_ms=timeout_ms,
        )
        page_by_type: dict[str, PageOptions] = {}
        per_type = fetch.get("per_url_type", {})
        if isinstance(per_type, dict):
            for item_type, value in per_type.items():
                if not isinstance(value, dict):
                    continue
                page_by_type[str(item_type)] = _page_override(base_page, value)
        launch = LaunchOptions(
            headless=bool(browser.get("headless", True)),
            real_chrome=bool(browser.get("real_chrome", False)),
            executable_path=_optional_string(browser.get("executable_path")),
            extra_flags=tuple(
                str(flag) for flag in browser.get("extra_flags", []) if str(flag).strip()
            ),
            user_agent=_optional_string(browser.get("user_agent")),
            locale=_optional_string(browser.get("locale")),
            timezone=_optional_string(browser.get("timezone")),
            proxy=_optional_string(browser.get("proxy")),
            challenge_wait_ms=_non_negative_int(browser.get("challenge_wait_ms"), 0),
        )
        profile_name = _optional_string(browser.get("profile_name")) or DEFAULT_PROFILE_NAME
        return cls(
            launch=launch,
            page=base_page,
            page_by_type=page_by_type,
            profile_name=_safe_profile_name(profile_name),
        )


class BrowserFetcher:
    """Fetch rendered HTML through a locally launched Chromium/Chrome."""

    thread_affine = True

    def __init__(
        self,
        store: TaskStore,
        *,
        task_id: str,
        out_root: str | Path,
        config: BrowserConfig | None = None,
        limiter: DomainLimiter | None = None,
        lease_token: int | None = None,
        max_attempts: int = 2,
        backoff_ms: int = 1000,
        process: subprocess.Popen[Any] | None = None,
        browser: Any | None = None,
        context: Any | None = None,
        page: Any | None = None,
        playwright: Any | None = None,
    ) -> None:
        self.store = store
        self.task_id = task_id
        self.out_root = Path(out_root)
        self.config = config or BrowserConfig()
        self.limiter = limiter
        self.lease_token = lease_token
        self.max_attempts = max(1, int(max_attempts))
        self.backoff_ms = max(0, int(backoff_ms))
        self._lock = threading.Lock()
        self._proc = process
        self._browser = browser
        self._context = context
        self._page = page
        self._playwright = playwright
        self._profile_dir = self.out_root / task_id / self.config.profile_name
        self._profile_resource = f"browser-profile:{task_id}"
        self._process_resource = f"browser-process:{task_id}"
        self._browser_name = ""
        self._browser_version = ""
        self._launched = process is not None
        self._resources_disabled = False
        self.requests = 0
        self.retries = 0

    # ------------------------------------------------------------------
    # Fetch API
    # ------------------------------------------------------------------
    def get(self, url: str, *, item_type: str | None = None) -> FetchResult:
        return self._fetch(url, item_type=item_type)

    def get_listing(
        self,
        url: str,
        *,
        advance: dict[str, Any],
        item_selector: str | None = None,
        item_type: str | None = None,
    ) -> FetchResult:
        return self._fetch(
            url,
            item_type=item_type,
            advance=advance,
            item_selector=item_selector,
        )

    def _fetch(
        self,
        url: str,
        *,
        item_type: str | None = None,
        advance: dict[str, Any] | None = None,
        item_selector: str | None = None,
    ) -> FetchResult:
        options = self._options_for(item_type)
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            if self.limiter is not None:
                self.limiter.wait(url)
            self.requests += 1
            if attempt > 1:
                self.retries += 1
            try:
                with self._lock:
                    return self._navigate(
                        url,
                        options,
                        advance=advance,
                        item_selector=item_selector,
                    )
            except Exception as exc:  # noqa: BLE001 - transport / browser boundary
                last_error = f"{type(exc).__name__}: {exc}"
                self._recover_if_dead()
                if attempt < self.max_attempts:
                    self._backoff(attempt)
        return FetchResult(status=0, url=url, error=last_error)

    @property
    def browser_launched(self) -> bool:
        return self._launched

    def describe(self) -> dict[str, Any]:
        pid = self._proc.pid if self._proc is not None else None
        return {
            "engine": "browser",
            "thread_affine": True,
            "engines_used": ["browser"] if self._launched else [],
            "browser_launched": self._launched,
            "browser_headless": self.config.launch.headless,
            "browser_binary": self._browser_name,
            "browser_version": self._browser_version,
            "browser_pid": pid,
            "browser_profile": self.config.profile_name,
        }

    def close(self) -> None:
        with self._lock:
            self._shutdown()
        self._launched = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def _navigate(
        self,
        url: str,
        options: PageOptions,
        *,
        advance: dict[str, Any] | None = None,
        item_selector: str | None = None,
    ) -> FetchResult:
        page = self._ensure_page(options)
        self._apply_resource_policy(page, options)
        response = page.goto(
            url,
            wait_until=options.wait_until,
            timeout=options.timeout_ms,
        )
        final_url = str(page.url)
        if final_url.startswith("chrome-error://"):
            return FetchResult(status=0, url=url, error=f"browser error page: {final_url}")
        status = int(getattr(response, "status", 0) or 0) if response is not None else 0
        if options.wait_selector:
            page.wait_for_selector(
                options.wait_selector,
                state=options.wait_selector_state,
                timeout=options.timeout_ms,
            )
        if options.network_idle:
            try:
                page.wait_for_load_state("networkidle", timeout=options.network_idle_timeout_ms)
            except Exception:
                logger.debug("network idle wait timed out", exc_info=True)
        if options.wait_ms:
            page.wait_for_timeout(options.wait_ms)
        if self.config.launch.challenge_wait_ms and _is_challenge_title(page.title()):
            self._wait_for_challenge(page)
        meta: dict[str, Any] = {"engine": "browser"}
        if advance:
            meta["advance"] = self._advance_listing(page, advance, item_selector)
        rendered_status = self._rendered_status(page)
        if rendered_status:
            status = rendered_status
        body = page.content().encode("utf-8")
        if _is_challenge_title(page.title()):
            meta["challenge_suspected"] = True
        return FetchResult(status=status, url=final_url, body=body, meta=meta)

    def _rendered_status(self, page: Any) -> int:
        """Read the status of the document that actually rendered.

        Challenge pages often answer the first request with 403/429/503 and
        then reload into the real page.  Playwright's ``goto`` response keeps
        the first status, so prefer the navigation timing entry when the page
        exposes it.  Fall back to the initial status when the API is missing.
        """
        script = (
            "() => { const nav = performance.getEntriesByType('navigation')[0]; "
            "return nav && typeof nav.responseStatus === 'number' ? nav.responseStatus : 0; }"
        )
        for _ in range(3):
            try:
                value = page.evaluate(script)
            except Exception:  # noqa: BLE001 - navigation may race with evaluation
                value = 0
            if isinstance(value, int) and value > 0:
                return value
            time.sleep(0.2)
        return 0

    def _wait_for_challenge(self, page: Any) -> None:
        deadline = time.monotonic() + self.config.launch.challenge_wait_ms / 1000
        while time.monotonic() < deadline:
            time.sleep(min(1.0, max(deadline - time.monotonic(), 0.1)))
            try:
                if not _is_challenge_title(page.title()):
                    return
            except Exception:  # noqa: BLE001 - page may be navigating
                return

    def _advance_listing(
        self,
        page: Any,
        advance: dict[str, Any],
        item_selector: str | None,
    ) -> dict[str, Any]:
        """Click or scroll a listing a bounded number of times.

        The final DOM is returned to the runner, which applies the existing
        link discovery and scope filters.  Append-style lists work; virtual
        lists that discard earlier rows are intentionally out of scope.
        """
        advance_type = str(advance.get("type", ""))
        selector = str(item_selector or advance.get("item_selector") or "").strip()
        settle_ms = _non_negative_int(advance.get("settle_ms"), 1000)
        no_new_stop = max(1, _positive_int(advance.get("no_new_stop"), 2))
        if advance_type == "load_more":
            max_steps = max(1, min(_positive_int(advance.get("max_clicks"), 10), 50))
        else:
            max_steps = max(1, min(_positive_int(advance.get("max_scrolls"), 10), 50))
        stats: dict[str, Any] = {
            "type": advance_type,
            "steps": 0,
            "items": 0,
            "stop": "MAX_STEPS",
            "max_steps": max_steps,
            "start_url": str(page.url),
            "final_url": str(page.url),
            "url_changes": 0,
            "urls": [],
        }
        if not selector:
            stats["stop"] = "MISSING_ITEM_SELECTOR"
            return stats
        try:
            previous = int(page.locator(selector).count())
        except Exception as exc:  # noqa: BLE001 - invalid selector boundary
            stats["stop"] = "INVALID_ITEM_SELECTOR"
            stats["detail"] = f"{type(exc).__name__}: {exc}"
            return stats
        stats["items"] = previous
        stalls = 0
        for step in range(max_steps):
            try:
                if advance_type == "load_more":
                    if not self._click_load_more(page, advance):
                        stats["stop"] = "BUTTON_GONE"
                        self._record_advance_url(page, stats)
                        break
                elif not self._scroll_once(page, advance):
                    stats["stop"] = "SCROLL_FAILED"
                    self._record_advance_url(page, stats)
                    break
            except Exception as exc:  # noqa: BLE001 - action boundary
                stats["stop"] = "ACTION_FAILED"
                stats["detail"] = f"{type(exc).__name__}: {exc}"
                self._record_advance_url(page, stats)
                break
            stats["steps"] = step + 1
            if settle_ms:
                page.wait_for_timeout(settle_ms)
            self._record_advance_url(page, stats)
            try:
                current = int(page.locator(selector).count())
            except Exception as exc:  # noqa: BLE001 - page may be navigating
                stats["stop"] = "INVALID_ITEM_SELECTOR"
                stats["detail"] = f"{type(exc).__name__}: {exc}"
                break
            stats["items"] = current
            if current > previous:
                previous = current
                stalls = 0
            else:
                stalls += 1
                if stalls >= no_new_stop:
                    stats["stop"] = "NO_NEW_ITEMS"
                    break
        self._record_advance_url(page, stats)
        return stats

    def _record_advance_url(self, page: Any, stats: dict[str, Any]) -> None:
        """Keep a small trace of URL state changes made by the action.

        AJAX pagination often updates ``?page=N`` while appending products.
        Recording the URL lets a rule author see that the next state is
        directly addressable and switch to ``page_param`` instead of repeating
        clicks or scrolls.
        """
        try:
            current = str(page.url)
        except Exception:  # noqa: BLE001 - page may be navigating
            return
        stats["final_url"] = current
        if current == stats["start_url"]:
            return
        urls = stats["urls"]
        if current not in urls and len(urls) < 10:
            urls.append(current)
            stats["url_changes"] = len(urls)

    def _click_load_more(self, page: Any, advance: dict[str, Any]) -> bool:
        selector = str(advance.get("button_selector") or "").strip()
        if not selector:
            return False
        locator = page.locator(selector)
        if locator.count() == 0:
            return False
        button = locator.first
        if not button.is_enabled():
            return False
        button.click()
        return True

    def _scroll_once(self, page: Any, advance: dict[str, Any]) -> bool:
        mode = str(advance.get("mode", "auto")).strip().lower()
        if mode not in {"auto", "scroll", "wheel"}:
            mode = "auto"
        container = str(advance.get("container") or "").strip()
        if container:
            locator = page.locator(container)
            if locator.count() == 0:
                return False
            target = locator.first
            if mode == "wheel":
                box = target.bounding_box()
                if not box:
                    return False
                page.mouse.move(
                    box["x"] + box["width"] / 2,
                    box["y"] + box["height"] / 2,
                )
                page.mouse.wheel(0, 2000)
            else:
                target.evaluate("el => { el.scrollTop = el.scrollHeight; }")
            return True
        if mode == "wheel":
            viewport = page.viewport_size or {"width": 1280, "height": 720}
            page.mouse.move(viewport["width"] / 2, viewport["height"] / 2)
            page.mouse.wheel(0, 2000)
        else:
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        return True

    def _options_for(self, item_type: str | None) -> PageOptions:
        if item_type and item_type in self.config.page_by_type:
            return self.config.page_by_type[item_type]
        return self.config.page

    # ------------------------------------------------------------------
    # Browser lifecycle
    # ------------------------------------------------------------------
    def _ensure_page(self, options: PageOptions) -> Any:
        if self._proc is not None and self._proc.poll() is not None:
            self._shutdown()
        if self._page is not None and not self._page.is_closed():
            return self._page
        self._start(options)
        return self._page

    def _start(self, options: PageOptions) -> None:
        try:
            from patchright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise BrowserLaunchError(
                "patchright is not installed; install the app dependencies first"
            ) from exc
        self._profile_dir.mkdir(parents=True, exist_ok=True)
        register_path(
            self.store,
            self.task_id,
            self._profile_dir,
            resource_id=self._profile_resource,
            lease_token=self.lease_token,
        )
        self._playwright = sync_playwright().start()
        try:
            executable, browser_name = self._resolve_executable()
            self._browser_name = browser_name
            port = _free_port()
            args = self._launch_args(executable, port)
            self._proc = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self._launched = True
            register_process(
                self.store,
                self.task_id,
                self._proc,
                resource_id=self._process_resource,
                lease_token=self.lease_token,
            )
            websocket_url, version = _wait_for_devtools(port, timeout=20.0)
            self._browser_version = version
            self._browser = self._playwright.chromium.connect_over_cdp(websocket_url)
            self._context = (
                self._browser.contexts[0]
                if self._browser.contexts
                else self._browser.new_context()
            )
            pages = list(self._context.pages)
            self._page = pages[0] if pages else self._context.new_page()
            self._configure_page(self._page, options)
        except Exception as exc:
            self._shutdown()
            if isinstance(exc, BrowserLaunchError):
                raise
            raise BrowserLaunchError(f"{type(exc).__name__}: {exc}") from exc

    def _launch_args(self, executable: str, port: int) -> list[str]:
        args = [
            executable,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={self._profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-default-apps",
            "--disable-sync",
            "--disable-component-update",
            "--disable-dev-shm-usage",
            "--metrics-recording-only",
            "--window-size=1280,900",
            "about:blank",
        ]
        if self.config.launch.headless:
            args.insert(1, "--headless=new")
        if (
            os.environ.get("GITHUB_ACTIONS") == "true"
            and self._browser_name == "chromium"
        ):
            # GitHub Actions' Ubuntu 24.04 AppArmor policy blocks the user
            # namespaces Playwright's bundled Chromium needs for its sandbox.
            # Keep the sandbox outside CI; CI only fetches local fixtures.
            args.insert(1, "--no-sandbox")
        if self.config.launch.locale:
            locale = self.config.launch.locale
            args.extend([f"--lang={locale}", f"--accept-lang={locale}"])
        if self.config.launch.user_agent:
            args.append(f"--user-agent={self.config.launch.user_agent}")
        if self.config.launch.proxy:
            args.append(f"--proxy-server={self.config.launch.proxy}")
        args.extend(self.config.launch.extra_flags)
        return args

    def _configure_page(self, page: Any, options: PageOptions) -> None:
        timeout = options.timeout_ms
        page.set_default_timeout(timeout)
        page.set_default_navigation_timeout(timeout)
        if options.disable_resources:
            page.route("**/*", _block_heavy_resources)
            self._resources_disabled = True
        if self.config.launch.timezone:
            try:
                session = page.context.new_cdp_session(page)
                session.send(
                    "Emulation.setTimezoneOverride",
                    {"timezoneId": self.config.launch.timezone},
                )
            except Exception:
                logger.debug("timezone override failed", exc_info=True)

    def _apply_resource_policy(self, page: Any, options: PageOptions) -> None:
        if options.disable_resources == self._resources_disabled:
            return
        try:
            page.unroute("**/*")
        except Exception:
            logger.debug("resource route removal failed", exc_info=True)
        if options.disable_resources:
            page.route("**/*", _block_heavy_resources)
        self._resources_disabled = options.disable_resources
    def _resolve_executable(self) -> tuple[str, str]:
        configured = self.config.launch.executable_path
        if configured:
            path = Path(configured).expanduser()
            if not path.is_file():
                raise BrowserLaunchError(f"browser executable not found: {path}")
            return str(path), _browser_name(path)
        if self.config.launch.real_chrome:
            for path in _system_browser_candidates():
                if path.is_file():
                    return str(path), _browser_name(path)
            raise BrowserLaunchError(
                "real_chrome requested but no system Chrome/Edge was found; "
                "set fetch.browser.executable_path"
            )
        executable = Path(self._playwright.chromium.executable_path)
        if not executable.is_file():
            raise BrowserLaunchError(
                "Patchright Chromium is not installed; run "
                "'python -m patchright install chromium'"
            )
        return str(executable), "chromium"

    def _recover_if_dead(self) -> None:
        if self._proc is None or self._proc.poll() is None:
            return
        self._shutdown()

    def _shutdown(self) -> None:
        page, browser, playwright = self._page, self._browser, self._playwright
        proc = self._proc
        self._page = None
        self._browser = None
        self._context = None
        self._playwright = None
        self._proc = None
        self._launched = False
        try:
            if page is not None:
                page.close()
        except Exception:
            logger.debug("page close failed", exc_info=True)
        try:
            if browser is not None:
                browser.close()
        except Exception:
            logger.debug("browser close failed", exc_info=True)
        try:
            if playwright is not None:
                playwright.stop()
        except Exception:
            logger.debug("playwright stop failed", exc_info=True)
        if proc is not None:
            if proc.poll() is None:
                terminate_process(proc.pid, grace_seconds=2.0)
            try:
                proc.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                pass
        if _remove_path(self._profile_dir):
            try:
                self.store.remove_resource(self.task_id, self._process_resource)
                self.store.remove_resource(self.task_id, self._profile_resource)
            except Exception:
                logger.debug("resource row cleanup failed", exc_info=True)

    def _backoff(self, attempt: int) -> None:
        if self.backoff_ms <= 0:
            return
        delay = min(self.backoff_ms / 1000 * (2 ** (attempt - 1)), 5.0)
        time.sleep(delay)


def _page_override(base: PageOptions, value: dict[str, Any]) -> PageOptions:
    return PageOptions(
        wait_until=(
            _wait_until(value.get("wait_until"))
            if value.get("wait_until") is not None
            else base.wait_until
        ),
        wait_selector=(
            _optional_string(value.get("wait_selector"))
            if "wait_selector" in value
            else base.wait_selector
        ),
        wait_selector_state=(
            _selector_state(value.get("wait_selector_state"))
            if value.get("wait_selector_state") is not None
            else base.wait_selector_state
        ),
        wait_ms=(
            _non_negative_int(value.get("wait_ms"), 0)
            if value.get("wait_ms") is not None
            else base.wait_ms
        ),
        network_idle=(
            bool(value.get("network_idle"))
            if "network_idle" in value
            else base.network_idle
        ),
        network_idle_timeout_ms=(
            _positive_int(value.get("network_idle_timeout_ms"), 5000)
            if value.get("network_idle_timeout_ms") is not None
            else base.network_idle_timeout_ms
        ),
        disable_resources=(
            bool(value.get("disable_resources"))
            if "disable_resources" in value
            else base.disable_resources
        ),
        timeout_ms=(
            _positive_int(value.get("timeout_ms"), 45000)
            if value.get("timeout_ms") is not None
            else base.timeout_ms
        ),
    )


def _wait_for_devtools(port: int, timeout: float) -> tuple[str, str]:
    deadline = time.monotonic() + max(timeout, 0.1)
    endpoint = f"http://127.0.0.1:{port}/json/version"
    # Never send the loopback DevTools probe through an HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with opener.open(endpoint, timeout=1) as response:
                payload = json.loads(response.read().decode("utf-8"))
            websocket_url = str(payload.get("webSocketDebuggerUrl") or "")
            if websocket_url:
                return websocket_url, str(payload.get("Browser") or "")
            last_error = "DevTools endpoint has no webSocketDebuggerUrl"
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(0.15)
    raise BrowserLaunchError(f"browser DevTools did not start: {last_error}")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _system_browser_candidates() -> list[Path]:
    candidates: list[Path] = []
    for env_name in ("ECOM_CHROME_PATH", "CHROME_PATH"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(Path(value).expanduser())
    for name in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "microsoft-edge",
        "msedge",
        "chrome",
    ):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    if os.name == "nt":
        roots = [
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
            os.environ.get("LOCALAPPDATA"),
        ]
        for root in roots:
            if not root:
                continue
            candidates.extend(
                [
                    Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe",
                    Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                ]
            )
    elif os.uname().sysname == "Darwin":  # pragma: no cover - macOS
        candidates.extend(
            [
                Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            ]
        )
    return list(dict.fromkeys(candidates))


def _browser_name(path: Path) -> str:
    name = path.name.lower()
    if "edge" in name or name == "msedge":
        return "msedge"
    if name.startswith("chrome"):
        return "chrome"
    return "chromium"


def _block_heavy_resources(route: Any) -> None:
    if route.request.resource_type in {"image", "font", "media"}:
        route.abort()
    else:
        route.continue_()


def _is_challenge_title(title: str) -> bool:
    normalized = (title or "").strip().lower()
    return any(marker in normalized for marker in CHALLENGE_TITLE_MARKERS)


def _remove_path(path: Path) -> bool:
    if not path.exists():
        return True
    for attempt in range(3):
        try:
            shutil.rmtree(path)
            return True
        except OSError:
            if attempt == 2:
                return False
            time.sleep(0.3)
    return False


def _safe_profile_name(value: str) -> str:
    cleaned = "".join(
        character for character in value if character.isalnum() or character in {"-", "_", "."}
    ).strip(". ")
    return cleaned or DEFAULT_PROFILE_NAME


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _non_negative_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number >= 0 else default


def _wait_until(value: Any) -> str:
    text = str(value or "domcontentloaded").strip().lower()
    return text if text in SUPPORTED_WAIT_UNTIL else "domcontentloaded"


def _selector_state(value: Any) -> str:
    text = str(value or "attached").strip().lower()
    return text if text in SUPPORTED_SELECTOR_STATES else "attached"
