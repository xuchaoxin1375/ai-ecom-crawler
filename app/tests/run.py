"""Run selected backend checks without replacing unittest discovery."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import unittest
from collections.abc import Iterator
from pathlib import Path

TESTS = Path(__file__).resolve().parent
GROUPS = {
    "quick": (
        "test_schema",
        "test_normalize",
        "test_csv_contract",
        "test_rule_diff",
        "test_batches",
    ),
    "api": ("test_web", "test_batches", "test_feedback", "test_migrate_rules"),
    "build": (
        "test_builds",
        "test_dependencies",
        "test_dependency_bridge",
        "test_harness",
        "test_preflight",
        "test_rule_diff",
        "test_service",
        "test_trace",
    ),
    "runtime": (
        "test_archive",
        "test_atomic",
        "test_cli",
        "test_control",
        "test_control_flow",
        "test_execution",
        "test_hybrid",
        "test_lease",
        "test_resources",
        "test_worker_quota",
    ),
    "browser": ("test_browser", "test_browser_actions"),
}
PARALLEL_GROUPS = ("build", "runtime")
PARALLEL_TIMEOUT = 180
_CHILD = "_parallel-child"


def load_suite(group: str, patterns: list[str]) -> unittest.TestSuite:
    loader = unittest.TestLoader()
    loader.testNamePatterns = [
        pattern if any(char in pattern for char in "*?[") else f"*{pattern}*"
        for pattern in patterns
    ] or None
    if group == "all":
        suite = loader.discover(str(TESTS), top_level_dir=str(TESTS.parent))
    else:
        suite = loader.loadTestsFromNames([f"tests.{name}" for name in GROUPS[group]])
    if loader.errors:
        raise ValueError("Test discovery failed:\n" + "\n".join(loader.errors))
    if suite.countTestCases() == 0:
        raise ValueError("no tests matched; check the group and --match pattern")
    return suite


def _test_ids(suite: unittest.TestSuite) -> Iterator[str]:
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _test_ids(item)
        else:
            yield item.id()


def _fingerprint(ids: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest()


def parallel_plan(suites: dict[str, unittest.TestSuite]) -> dict[str, str]:
    seen: set[str] = set()
    plan: dict[str, str] = {}
    for name, suite in suites.items():
        ids = list(_test_ids(suite))
        unique = set(ids)
        if not ids or len(unique) != len(ids) or seen & unique:
            raise ValueError(f"empty or overlapping parallel group: {name}")
        seen.update(unique)
        plan[name] = _fingerprint(ids)
    return plan


def run_suite(suite: unittest.TestSuite, scope: str, *, quiet: bool) -> int:
    selected = suite.countTestCases()
    sys.stderr.write(f"Backend suite: {scope}; {selected} tests selected\n")
    sys.stderr.flush()
    verbosity = 0 if quiet else 2
    if sys.version_info >= (3, 12):
        runner = unittest.TextTestRunner(verbosity=verbosity, durations=10)
    else:
        runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    for test, reason in result.skipped:
        sys.stderr.write(f"Not verified: {test}: {reason}\n")
    if result.testsRun != selected:
        sys.stderr.write(f"Incomplete run: {result.testsRun} of {selected} selected tests executed\n")
        return 1
    return 0 if result.wasSuccessful() and not result.skipped else 1


def _run_child(group: str, expected: str, receipt: str, quiet: str) -> int:
    # No test imports or subprocesses before the parent has assigned the job.
    marker = Path(receipt).with_suffix(".pid")
    staging = marker.with_suffix(".pid.tmp")
    staging.write_text(str(os.getpid()), encoding="ascii")
    staging.replace(marker)
    if sys.stdin.buffer.read(1) != b"1":
        return 1
    try:
        suite = load_suite(group, [])
        if _fingerprint(list(_test_ids(suite))) != expected:
            raise ValueError(f"test selection changed in {group}")
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    code = run_suite(suite, group, quiet=quiet == "1")
    if code == 0:
        Path(receipt).write_text(expected, encoding="ascii")
    return code


def main(argv: list[str] | None = None) -> int:
    """Select a suite, report timings, and fail on empty or incomplete runs."""
    args_list = sys.argv[1:] if argv is None else argv
    sys.path.insert(0, str(TESTS.parent))
    if args_list[:1] == [_CHILD]:
        if len(args_list) != 5 or args_list[1] not in PARALLEL_GROUPS:
            return 2
        return _run_child(*args_list[1:])

    parser = argparse.ArgumentParser(
        description="Run backend unittest suites against local fixtures; no live sites or models.",
        allow_abbrev=False,
        epilog=(
            "Examples (with app dev dependencies installed): "
            "python app/tests/run.py; python app/tests/run.py build -k price_regression; "
            "python app/tests/run.py parallel; python app/tests/run.py all. "
            "Browser tests require installed Chromium; "
            "some build tests require Node.js. Tests use temporary files, SQLite, and local "
            "fixture processes as needed. The script does not install dependencies. "
            "Exit codes: 0 all selected tests passed, 1 failed, skipped or timed out, "
            "2 invalid/empty selection or unsupported invocation, 130 interrupted."
        ),
    )
    parser.add_argument(
        "group", nargs="?", default="quick", choices=(*GROUPS, "parallel", "all"),
        help="quick (default): data contracts and batch API; api, build, runtime, or browser: "
        "one area; parallel: build + runtime on Windows, without Chromium; "
        "all: discover the full backend suite (serial)",
    )
    parser.add_argument(
        "-k", "--match", action="append", default=[], metavar="PATTERN",
        help="filter by test ID substring or glob; repeat to match any given pattern",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="suppress per-test progress, not the summary",
    )
    parser.add_argument(
        "--timeout", type=int, metavar="SECONDS",
        help=f"wall-clock limit for both parallel workers (default: {PARALLEL_TIMEOUT}s)",
    )
    args = parser.parse_args(args_list)
    if any(not pattern.strip() for pattern in args.match):
        parser.error("--match requires a non-empty pattern")

    if args.group != "parallel" and args.timeout is not None:
        parser.error("--timeout is only supported in parallel mode")
    try:
        if args.group == "parallel":
            if sys.platform != "win32":
                parser.error("parallel mode requires Windows; run build and runtime separately")
            if args.match:
                parser.error("parallel mode does not accept --match; filter build or runtime instead")
            if args.timeout is not None and args.timeout < 1:
                parser.error("--timeout must be positive")
            from tests.parallel_runner import run_parallel

            plan = parallel_plan({group: load_suite(group, []) for group in PARALLEL_GROUPS})
            return run_parallel(
                [sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()), _CHILD],
                plan, quiet=args.quiet, timeout=args.timeout or PARALLEL_TIMEOUT,
            )
        suite = load_suite(args.group, args.match)
    except ValueError as exc:
        parser.exit(2, f"{exc}\n")
    scope = f"{args.group} (filtered)" if args.match else args.group
    return run_suite(suite, scope, quiet=args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
