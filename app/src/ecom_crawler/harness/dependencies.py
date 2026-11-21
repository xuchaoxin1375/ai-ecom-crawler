"""Dependency request policy for build sessions.

This module owns the decision and installation boundary, not the OpenCode tool
bridge.  A BuildService or a pause-gate-style plugin can call it; package names
and managers are validated here and installation is never run through a shell.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+!-]{0,127}$")
MANAGERS = {"pip", "uv"}

Installer = Callable[[str, str, Path], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class DependencyRequest:
    name: str
    version: str | None = None
    manager: str = "uv"
    reason: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DependencyRequest:
        return cls(
            name=str(payload.get("name") or ""),
            version=payload.get("version"),
            manager=str(payload.get("manager") or "uv"),
            reason=payload.get("reason"),
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "name": self.name,
            "version": self.version,
            "license": self.license,
            "detail": self.detail,
            "command": self.command,
            "stdout": self.stdout[-4000:],
            "stderr": self.stderr[-4000:],
        }


class DependencyPolicy:
    """Baseline / allowlist policy with an optional isolated installer."""

    def __init__(
        self,
        *,
        baseline: dict[str, str] | None = None,
        allowlist: dict[str, dict[str, str]] | None = None,
        installer: Installer | None = None,
        build_python: str | Path | None = None,
    ) -> None:
        self.baseline = dict(baseline or {})
        self.allowlist = {
            str(name): dict(meta or {})
            for name, meta in (allowlist or {}).items()
        }
        self.installer = installer
        self.build_python = Path(build_python) if build_python else None

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

    def request(self, request: DependencyRequest) -> DependencyDecision:
        name = request.name.strip()
        if not PACKAGE_RE.fullmatch(name):
            return DependencyDecision(
                "denied", name, request.version, None, "invalid package name"
            )
        if request.manager not in MANAGERS:
            return DependencyDecision(
                "denied",
                name,
                request.version,
                None,
                f"unsupported manager: {request.manager}",
            )
        if request.version is not None and not VERSION_RE.fullmatch(
            str(request.version)
        ):
            return DependencyDecision(
                "denied",
                name,
                request.version,
                None,
                "invalid version",
            )
        if name in self.baseline:
            available = self.baseline[name]
            if request.version is None or str(request.version) == available:
                return DependencyDecision(
                    "available",
                    name,
                    available,
                    None,
                    "present in the build baseline",
                )
            return DependencyDecision(
                "approval_required",
                name,
                request.version,
                None,
                f"baseline has {available}; version change needs approval",
            )
        metadata = self.allowlist.get(name)
        if metadata is None:
            return DependencyDecision(
                "approval_required",
                name,
                request.version,
                None,
                "package is not in the allowlist",
            )
        version = str(request.version or metadata.get("version") or "")
        license_name = metadata.get("license")
        if not version:
            return DependencyDecision(
                "approval_required",
                name,
                None,
                license_name,
                "allowlisted package needs an explicit version",
            )
        if self.installer is None or self.build_python is None:
            return DependencyDecision(
                "approval_required",
                name,
                version,
                license_name,
                "installer or build interpreter is not configured",
            )
        try:
            completed = self.installer(name, version, self.build_python)
        except Exception as exc:  # noqa: BLE001 - installer boundary
            return DependencyDecision(
                "failed",
                name,
                version,
                license_name,
                f"{type(exc).__name__}: {exc}",
            )
        status = "installed" if completed.returncode == 0 else "failed"
        return DependencyDecision(
            status,
            name,
            version,
            license_name,
            "installed into the build interpreter" if status == "installed" else "installer failed",
            command=list(getattr(completed, "args", []) or []),
            stdout=str(getattr(completed, "stdout", "") or ""),
            stderr=str(getattr(completed, "stderr", "") or ""),
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
