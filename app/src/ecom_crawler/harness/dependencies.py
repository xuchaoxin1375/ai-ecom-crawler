"""Dependency request policy for build sessions.

This module owns the decision and installation boundary, not the OpenCode tool
bridge.  The bridge writes structured requests and waits for a decision; this
module validates package names and managers, decides baseline/allowlist/
approval outcomes, installs into an explicit build interpreter and verifies the
result.  Installation is never run through a shell.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+!-]{0,127}$")
INSTALL_MANAGERS = {"pip", "uv"}
KNOWN_MANAGERS = {"pip", "uv", "npm", "system"}
SCOPES = {"build", "system"}

Installer = Callable[[str, str, Path], subprocess.CompletedProcess[str]]
Verifier = Callable[[str, str, Path], subprocess.CompletedProcess[str]]


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class DependencyRequest:
    """One structured dependency request from the build agent.

    ``package`` is the documented field name; ``name`` is kept as the internal
    spelling and accepts the older payload shape.
    """

    name: str
    version: str | None = None
    manager: str = "uv"
    reason: str | None = None
    source: str | None = None
    license: str | None = None
    scope: str = "build"
    fallback: str | None = None

    @property
    def package(self) -> str:
        return self.name

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DependencyRequest:
        raw_name = payload.get("package", payload.get("name", ""))
        raw_version = payload.get("version")
        return cls(
            name=str(raw_name or ""),
            version=None if raw_version is None else str(raw_version),
            manager=str(payload.get("manager") or "uv"),
            reason=_optional_text(payload.get("reason")),
            source=_optional_text(payload.get("source")),
            license=_optional_text(payload.get("license")),
            scope=str(payload.get("scope") or "build"),
            fallback=_optional_text(payload.get("fallback")),
        )


@dataclass
class DependencyDecision:
    status: str
    name: str
    version: str | None
    license: str | None
    detail: str
    command: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    scope: str = "build"
    source: str | None = None
    reason: str | None = None
    fallback: str | None = None
    approved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "package": self.name,
            "name": self.name,
            "version": self.version,
            "license": self.license,
            "detail": self.detail,
            "command": self.command,
            "stdout": self.stdout[-4000:],
            "stderr": self.stderr[-4000:],
            "scope": self.scope,
            "source": self.source,
            "reason": self.reason,
            "fallback": self.fallback,
            "approved": self.approved,
        }


class DependencyPolicy:
    """Baseline / allowlist policy with explicit approval and installation.

    ``installer`` is the legacy single-installer form and applies to every
    supported manager.  ``installers`` selects per manager and takes
    precedence.  A missing installer yields ``approval_required`` instead of
    guessing.
    """

    def __init__(
        self,
        *,
        baseline: dict[str, str] | None = None,
        allowlist: dict[str, dict[str, str]] | None = None,
        installer: Installer | None = None,
        installers: dict[str, Installer] | None = None,
        build_python: str | Path | None = None,
        verifier: Verifier | None = None,
    ) -> None:
        self.baseline = dict(baseline or {})
        self.allowlist = {
            str(name): dict(meta or {})
            for name, meta in (allowlist or {}).items()
        }
        self.build_python = Path(build_python) if build_python else None
        self.verifier = verifier
        self.installers: dict[str, Installer] = dict(installers or {})
        if installer is not None:
            self.installers.setdefault("*", installer)

    @classmethod
    def from_file(cls, path: str | Path) -> DependencyPolicy:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("dependency policy must be a JSON object")
        baseline = payload.get("baseline") or {}
        allowlist = payload.get("allowlist") or {}
        if not isinstance(baseline, dict) or not isinstance(allowlist, dict):
            raise TypeError("baseline and allowlist must be objects")
        return cls(
            baseline={str(key): str(value) for key, value in baseline.items()},
            allowlist={
                str(key): dict(value or {})
                for key, value in allowlist.items()
                if isinstance(value, dict)
            },
        )

    @classmethod
    def empty(cls) -> DependencyPolicy:
        return cls()

    def request(
        self,
        request: DependencyRequest,
        *,
        approved: bool = False,
    ) -> DependencyDecision:
        """Decide one request.

        Without ``approved`` an allowlisted package installs automatically and
        an unknown or system-scope request returns ``approval_required``.
        ``approved=True`` is the operator's one-time approval and allows an
        unknown build-scope package with an explicit version to install.
        """

        name = request.name.strip()
        manager = request.manager.strip().lower()
        scope = request.scope.strip().lower()
        metadata = self.allowlist.get(name)
        license_name = request.license or (
            metadata.get("license") if metadata is not None else None
        )

        def decision(
            status: str,
            detail: str,
            *,
            version: str | None = request.version,
        ) -> DependencyDecision:
            return DependencyDecision(
                status=status,
                name=name,
                version=version,
                license=license_name,
                detail=detail,
                scope=scope,
                source=request.source,
                reason=request.reason,
                fallback=request.fallback,
                approved=approved,
            )

        if not PACKAGE_RE.fullmatch(name):
            return decision("denied", "invalid package name")
        if manager not in KNOWN_MANAGERS:
            return decision("denied", f"unsupported manager: {request.manager}")
        if scope not in SCOPES:
            return decision("denied", f"unsupported scope: {request.scope}")
        if request.version is not None and not VERSION_RE.fullmatch(
            str(request.version)
        ):
            return decision("denied", "invalid version")

        if name in self.baseline:
            available = self.baseline[name]
            if request.version is None or str(request.version) == available:
                return decision(
                    "available",
                    "present in the build baseline",
                    version=available,
                )
            if not approved:
                return decision(
                    "approval_required",
                    f"baseline has {available}; version change needs approval",
                )

        version = str(
            request.version or (metadata.get("version") if metadata else "") or ""
        )

        if scope == "system":
            return decision(
                "approval_required",
                "system scope is installed by the operator, not the build policy",
                version=version or None,
            )
        if manager not in INSTALL_MANAGERS:
            return decision(
                "approval_required",
                f"{manager} packages are installed by the operator",
                version=version or None,
            )
        if metadata is None and not approved:
            return decision(
                "approval_required",
                "package is not in the allowlist; explicit approval is required",
                version=version or None,
            )
        if not version:
            return decision(
                "approval_required",
                "allowlisted package needs an explicit version",
                version=None,
            )
        installer = self.installers.get(manager) or self.installers.get("*")
        if installer is None or self.build_python is None:
            return decision(
                "approval_required",
                f"no installer is configured for manager {manager}",
                version=version,
            )

        try:
            completed = installer(name, version, self.build_python)
        except Exception as exc:  # noqa: BLE001 - installer boundary
            return decision(
                "failed",
                f"{type(exc).__name__}: {exc}",
                version=version,
            )
        stdout = str(getattr(completed, "stdout", "") or "")
        stderr = str(getattr(completed, "stderr", "") or "")
        command = list(getattr(completed, "args", []) or [])
        if completed.returncode != 0:
            return DependencyDecision(
                status="failed",
                name=name,
                version=version,
                license=license_name,
                detail="installer failed",
                command=command,
                stdout=stdout,
                stderr=stderr,
                scope=scope,
                source=request.source,
                reason=request.reason,
                fallback=request.fallback,
                approved=approved,
            )

        if self.verifier is not None:
            try:
                checked = self.verifier(name, version, self.build_python)
            except Exception as exc:  # noqa: BLE001 - verifier boundary
                return DependencyDecision(
                    status="failed",
                    name=name,
                    version=version,
                    license=license_name,
                    detail=f"installed but verification raised {type(exc).__name__}: {exc}",
                    command=command,
                    stdout=stdout,
                    stderr=stderr,
                    scope=scope,
                    source=request.source,
                    reason=request.reason,
                    fallback=request.fallback,
                    approved=approved,
                )
            check_stdout = str(getattr(checked, "stdout", "") or "")
            check_stderr = str(getattr(checked, "stderr", "") or "")
            stdout = "\n".join(part for part in (stdout, check_stdout) if part)
            stderr = "\n".join(part for part in (stderr, check_stderr) if part)
            if checked.returncode != 0:
                return DependencyDecision(
                    status="failed",
                    name=name,
                    version=version,
                    license=license_name,
                    detail="installed but verification failed",
                    command=command,
                    stdout=stdout,
                    stderr=stderr,
                    scope=scope,
                    source=request.source,
                    reason=request.reason,
                    fallback=request.fallback,
                    approved=approved,
                )

        return DependencyDecision(
            status="installed",
            name=name,
            version=version,
            license=license_name,
            detail="installed and verified" if self.verifier else "installed",
            command=command,
            stdout=stdout,
            stderr=stderr,
            scope=scope,
            source=request.source,
            reason=request.reason,
            fallback=request.fallback,
            approved=approved,
        )


def install_with_pip(
    name: str,
    version: str,
    build_python: Path,
    *,
    timeout: float = 300.0,
) -> subprocess.CompletedProcess[str]:
    """Install one allowlisted package into an explicit interpreter.

    The caller owns the build environment; this helper never falls back to the
    ambient Python or a shell.
    """
    if not build_python.is_file():
        raise FileNotFoundError(f"build interpreter not found: {build_python}")
    return subprocess.run(
        [
            str(build_python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            f"{name}=={version}",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )


def _uv_command(uv: str | Sequence[str] | None) -> list[str]:
    if isinstance(uv, str):
        return [uv]
    if uv is not None:
        return [str(part) for part in uv]
    found = shutil.which("uv")
    if found:
        return [found]
    return [sys.executable, "-m", "uv"]


def install_with_uv(
    name: str,
    version: str,
    build_python: Path,
    *,
    uv: str | Sequence[str] | None = None,
    timeout: float = 300.0,
) -> subprocess.CompletedProcess[str]:
    """Install one package with ``uv pip`` into an explicit interpreter."""
    if not build_python.is_file():
        raise FileNotFoundError(f"build interpreter not found: {build_python}")
    return subprocess.run(
        [
            *_uv_command(uv),
            "pip",
            "install",
            "--python",
            str(build_python),
            f"{name}=={version}",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )


def verify_with_python(
    name: str,
    version: str,
    build_python: Path,
    *,
    timeout: float = 60.0,
) -> subprocess.CompletedProcess[str]:
    """Check that the build interpreter can resolve installed metadata.

    The version argument is part of the verifier signature; the check reports
    the installed version rather than parsing requirement syntax.
    """
    del version
    if not build_python.is_file():
        raise FileNotFoundError(f"build interpreter not found: {build_python}")
    script = (
        "import importlib.metadata as metadata, sys; "
        "print(metadata.version(sys.argv[1]))"
    )
    return subprocess.run(
        [str(build_python), "-c", script, name],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )
