"""Run selected backend checks without replacing unittest discovery."""

from __future__ import annotations

import argparse
import sys
import unittest
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


def main(argv: list[str] | None = None) -> int:
    """Select a suite, report timings, and fail on empty or incomplete runs."""
    parser = argparse.ArgumentParser(
        description="Run backend unittest suites against local fixtures; no live sites or models.",
        allow_abbrev=False,
        epilog=(
            "Examples (with app dev dependencies installed): "
            "python app/tests/run.py; python app/tests/run.py build -k price_regression; "
            "python app/tests/run.py all. Browser tests require installed Chromium; "
            "some build tests require Node.js. Tests use temporary files, SQLite, and local "
            "fixture processes as needed. The script does not install dependencies. "
            "Exit codes: 0 all selected tests passed, 1 failed or skipped, 2 invalid/empty selection."
        ),
    )
    parser.add_argument(
        "group", nargs="?", default="quick", choices=(*GROUPS, "all"),
        help="quick (default): data contracts and batch API; api, build, runtime, or browser: "
        "one area; all: discover the full backend suite",
    )
    parser.add_argument(
        "-k", "--match", action="append", default=[], metavar="PATTERN",
        help="filter by test ID substring or glob; repeat to match any given pattern",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="suppress per-test progress, not the summary",
    )
    args = parser.parse_args(argv)
    if any(not pattern.strip() for pattern in args.match):
        parser.error("--match requires a non-empty pattern")

    sys.path.insert(0, str(TESTS.parent))
    loader = unittest.TestLoader()
    loader.testNamePatterns = [
        pattern if any(char in pattern for char in "*?[") else f"*{pattern}*"
        for pattern in args.match
    ] or None
    if args.group == "all":
        suite = loader.discover(str(TESTS), top_level_dir=str(TESTS.parent))
    else:
        suite = loader.loadTestsFromNames([f"tests.{name}" for name in GROUPS[args.group]])
    if loader.errors:
        parser.exit(2, "Test discovery failed:\n" + "\n".join(loader.errors))
    selected = suite.countTestCases()
    if selected == 0:
        parser.error("no tests matched; check the group and --match pattern")

    scope = f"{args.group} (filtered)" if args.match else args.group
    sys.stderr.write(f"Backend suite: {scope}; {selected} tests selected\n")
    sys.stderr.flush()
    verbosity = 0 if args.quiet else 2
    if sys.version_info >= (3, 12):
        runner = unittest.TextTestRunner(verbosity=verbosity, durations=10)
    else:
        runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    if result.skipped:
        for test, reason in result.skipped:
            sys.stderr.write(f"Not verified: {test}: {reason}\n")
    if result.testsRun != selected:
        sys.stderr.write(f"Incomplete run: {result.testsRun} of {selected} selected tests executed\n")
        return 1
    return 0 if result.wasSuccessful() and not result.skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
