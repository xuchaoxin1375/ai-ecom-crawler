"""Real dependency bridge smoke for the build policy.

This creates a throwaway venv, starts the host-side file bridge, submits one
allowlisted request, installs the package through the same policy/installer/
verifier path a build uses, and removes the venv.  It is a manual experiment,
not part of the unit test suite: it needs network access and a package index.

Run with the app environment:

    python -m uv run --project app python experiments/harness/dependency_install_smoke.py

Use ``--manager pip`` to exercise the pip installer, or ``--keep`` to inspect
the temporary workspace and venv.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from ecom_crawler.harness.adapter import BuildSession
from ecom_crawler.harness.dependencies import (
    DependencyPolicy,
    DependencyRequest,
    install_with_pip,
    install_with_uv,
    verify_with_python,
)
from ecom_crawler.harness.dependency_bridge import DependencyBridge
from ecom_crawler.harness.models import BuildTask
from ecom_crawler.harness.workspace import BuildWorkspace


class PolicyAdapter:
    """Minimal adapter surface used by the host bridge in this smoke."""

    def __init__(self, policy: DependencyPolicy) -> None:
        self.policy = policy

    def request_dependency(
        self,
        build_id: str,
        request: dict[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        return self.policy.request(
            DependencyRequest.from_dict(request),
            approved=approved,
        ).to_dict()


def _venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _wait_for_response(
    path: Path, timeout: float
) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        time.sleep(0.1)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manager", choices=("pip", "uv"), default="uv")
    parser.add_argument("--package", default="six")
    parser.add_argument("--version", default="1.17.0")
    parser.add_argument("--license", default="MIT")
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    temporary = args.work_dir is None
    root = (
        Path(tempfile.mkdtemp(prefix="ecom-dependency-smoke-"))
        if temporary
        else args.work_dir
    )
    root.mkdir(parents=True, exist_ok=True)
    venv = root / "venv"
    print(f"venv: {venv}")
    subprocess.run(
        [sys.executable, "-m", "venv", str(venv)],
        check=True,
    )
    build_python = _venv_python(venv)
    if not build_python.is_file():
        print(f"ERROR: venv interpreter not found: {build_python}")
        return 1

    if args.manager == "pip":
        installer = install_with_pip
    else:
        installer = install_with_uv

    policy = DependencyPolicy(
        allowlist={
            args.package: {
                "version": args.version,
                "license": args.license,
            }
        },
        installers={args.manager: installer},
        build_python=build_python,
        verifier=verify_with_python,
    )
    task = BuildTask(
        build_id="dependency-smoke",
        site={"entry_url": "https://example.test/"},
        market="GB",
        locale="en-GB",
        notes="Dependency bridge smoke; synthetic site.",
    )
    workspace = BuildWorkspace.create(
        root / "sessions",
        task,
        pause_gate=False,
        dependency_tool=False,
    )
    session = BuildSession(
        build_id=task.build_id,
        state="RUNNING",
        workspace=workspace,
        session_id=None,
    )
    events: list[Any] = []
    bridge = DependencyBridge(
        session,
        PolicyAdapter(policy),
        on_event=events.append,
        poll_interval=0.05,
        approval_timeout=60,
    )
    request_id = "smoke-request"
    request = {
        "request_id": request_id,
        "package": args.package,
        "manager": args.manager,
        "version": args.version,
        "reason": "dependency bridge smoke",
        "source": "PyPI",
        "license": args.license,
        "scope": "build",
        "fallback": "stop and report the missing dependency",
    }
    request_path = workspace.dependency_requests_dir / f"{request_id}.json"
    request_path.write_text(
        json.dumps(request, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    bridge.start()
    try:
        response = _wait_for_response(
            workspace.dependency_responses_dir / f"{request_id}.json",
            args.timeout,
        )
    finally:
        bridge.stop()
    if response is None:
        print("ERROR: no bridge response before timeout")
        return 1
    print(json.dumps(response, ensure_ascii=False, indent=2))
    print(
        "events: "
        + ", ".join(event.type for event in events)
    )
    ok = response.get("status") == "installed"
    if temporary and not args.keep:
        shutil.rmtree(root, ignore_errors=True)
    else:
        print(f"kept: {root}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
