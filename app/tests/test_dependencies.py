from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from ecom_crawler.harness.dependencies import (
    DependencyPolicy,
    DependencyRequest,
    install_with_pip,
)


def completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["pip", "install"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


class DependencyPolicyTests(unittest.TestCase):
    def test_baseline_package_is_available(self) -> None:
        policy = DependencyPolicy(baseline={"lxml": "6.1.3"})
        decision = policy.request(DependencyRequest(name="lxml"))
        self.assertEqual(decision.status, "available")
        self.assertEqual(decision.version, "6.1.3")

    def test_allowlisted_package_installs_with_fake_installer(self) -> None:
        calls: list[tuple[str, str, Path]] = []

        def installer(name: str, version: str, python: Path):
            calls.append((name, version, python))
            return completed(0, stdout="installed")

        policy = DependencyPolicy(
            allowlist={"pyyaml": {"version": "6.0.3", "license": "MIT"}},
            installer=installer,
            build_python=Path("/build/python"),
        )
        decision = policy.request(DependencyRequest(name="pyyaml"))
        self.assertEqual(decision.status, "installed")
        self.assertEqual(decision.license, "MIT")
        self.assertEqual(calls, [("pyyaml", "6.0.3", Path("/build/python"))])

    def test_installer_failure_returns_stderr(self) -> None:
        policy = DependencyPolicy(
            allowlist={"missingpkg": {"version": "1.0.0"}},
            installer=lambda name, version, python: completed(
                1, stderr="no matching distribution"
            ),
            build_python=Path("/build/python"),
        )
        decision = policy.request(DependencyRequest(name="missingpkg"))
        self.assertEqual(decision.status, "failed")
        self.assertIn("no matching distribution", decision.stderr)

    def test_unknown_package_needs_approval(self) -> None:
        decision = DependencyPolicy().request(DependencyRequest(name="unknownpkg"))
        self.assertEqual(decision.status, "approval_required")

    def test_invalid_package_manager_and_version_are_denied(self) -> None:
        policy = DependencyPolicy()
        self.assertEqual(
            policy.request(DependencyRequest(name="../escape")).status, "denied"
        )
        self.assertEqual(
            policy.request(
                DependencyRequest(name="pkg", manager="system")
            ).status,
            "denied",
        )
        self.assertEqual(
            policy.request(
                DependencyRequest(name="pkg", version="1.0; rm -rf /")
            ).status,
            "denied",
        )

    def test_policy_file_and_missing_build_interpreter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "deps.json"
            path.write_text(
                json.dumps(
                    {
                        "baseline": {"lxml": "6.1.3"},
                        "allowlist": {"pyyaml": {"version": "6.0.3"}},
                    }
                ),
                encoding="utf-8",
            )
            policy = DependencyPolicy.from_file(path)
        self.assertEqual(
            policy.request(DependencyRequest(name="lxml")).status, "available"
        )
        self.assertEqual(
            policy.request(DependencyRequest(name="pyyaml")).status,
            "approval_required",
        )
        with self.assertRaises(FileNotFoundError):
            install_with_pip("pyyaml", "6.0.3", Path("/missing/python"))


if __name__ == "__main__":
    unittest.main()
