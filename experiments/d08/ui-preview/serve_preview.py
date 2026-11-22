"""Serve a local D08 task-console preview with synthetic data.

The preview reuses the 1280 capture seed, starts ``ecom-crawler serve`` on
loopback and keeps running until Ctrl+C. It does not fetch sites, start a
worker or write into the repository.

Run from the repository root:

    app/.venv/Scripts/python.exe experiments/d08/ui-preview/serve_preview.py --port 8775
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

CAPTURE_PATH = Path(__file__).resolve().parents[1] / "ui-1280" / "capture.py"


def _load_capture():
    spec = importlib.util.spec_from_file_location(
        "ui_1280_capture", CAPTURE_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {CAPTURE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8775)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    capture = _load_capture()
    temporary = tempfile.TemporaryDirectory(prefix="ecom-d08-preview-")
    root = Path(temporary.name)
    db = root / "tasks.db"
    out_root = root / "tasks"
    out_root.mkdir()
    capture.seed(db, out_root)

    url = f"http://{args.host}:{args.port}"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "ecom_crawler",
            "serve",
            "--db",
            str(db),
            "--out-root",
            str(out_root),
            "--rules-dir",
            str(capture.RULES_DIR),
            "--no-worker",
            "--host",
            args.host,
            "--port",
            str(args.port),
        ],
        cwd=Path.cwd(),
    )
    try:
        capture.wait_ready(url)
        print(f"preview: {url}", flush=True)
        print("synthetic data; Ctrl+C stops the preview", flush=True)
        return process.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
