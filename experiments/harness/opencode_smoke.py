"""Local OpenCode HTTP/SSE adapter smoke (ADR 0006).

Without ``--prompt`` this creates a session, subscribes to the event stream,
collects artifacts and closes the server; it does not invoke the model, so it
does not consume model tokens.  With ``--prompt`` it runs one real build turn;
use it only after the model/cost scope is approved.

Run with the app environment:

    python -m uv run --project app python experiments/harness/opencode_smoke.py
"""

from __future__ import annotations

import argparse
import json
import queue
import shutil
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from ecom_crawler.harness import BuildTask, OpenCodeHttpAdapter
from ecom_crawler.harness.adapter import HarnessStateError


def _start_event_pump(adapter: OpenCodeHttpAdapter, build_id: str) -> queue.Queue:
    events: queue.Queue = queue.Queue()

    def pump() -> None:
        try:
            for event in adapter.stream_events(build_id):
                events.put(("event", event))
        except Exception as exc:  # noqa: BLE001 - background pump boundary
            events.put(("error", exc))
        finally:
            events.put(("end", None))

    threading.Thread(
        target=pump,
        name="harness-event-pump",
        daemon=True,
    ).start()
    return events


def _next_event(events: queue.Queue, deadline: float):
    while time.monotonic() < deadline:
        try:
            return events.get(timeout=0.5)
        except queue.Empty:
            continue
    return ("timeout", None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", type=Path, default=None)
    parser.add_argument("--build-id", default=None)
    parser.add_argument("--prompt", default=None)
    parser.add_argument("--model-provider", default=None)
    parser.add_argument("--model-id", default=None)
    parser.add_argument("--model-variant", default=None)
    parser.add_argument(
        "--permission",
        choices=("reject", "once", "always"),
        default="reject",
        help="reply used for permission requests during a prompted run",
    )
    parser.add_argument(
        "--permission-probe",
        action="store_true",
        help="create and answer one real permission request without a model call",
    )
    parser.add_argument(
        "--ask-shell",
        action="store_true",
        help="create the session with a shell=ask permission rule for the probe",
    )
    parser.add_argument(
        "--allow-shell",
        action="store_true",
        help="create the session with a shell=allow rule for the pause-gate probe",
    )
    parser.add_argument(
        "--cancel-after-start",
        action="store_true",
        help="cancel/interrupt after the first execution-started event",
    )
    parser.add_argument(
        "--pause-after-prompt",
        action="store_true",
        help="pause the build immediately after prompt admission to test pause-gate",
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    build_id = args.build_id or (
        "harness-smoke-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    )
    temporary_created = args.workspace_root is None
    if args.workspace_root is None:
        workspace_root = Path(tempfile.mkdtemp(prefix="ecom-harness-"))
    else:
        workspace_root = args.workspace_root

    model = None
    if args.model_provider and args.model_id:
        model = {"providerID": args.model_provider, "id": args.model_id}
        if args.model_variant:
            model["variant"] = args.model_variant
    task = BuildTask(
        build_id=build_id,
        site={"entry_url": "https://example.com/"},
        scope={"max_pages": 1},
        market="GB",
        locale="en-GB",
        model=model,
        notes="Adapter smoke only; not a real site build.",
    )

    permissions = None
    if args.ask_shell:
        permissions = [{"action": "shell", "resource": "*", "effect": "ask"}]
    elif args.allow_shell:
        permissions = [{"action": "shell", "resource": "*", "effect": "allow"}]
    adapter = OpenCodeHttpAdapter(
        workspace_root,
        permissions=permissions,
        event_timeout=args.timeout,
    )
    session = None
    try:
        session = adapter.start_build(task)
        print(f"build: {session.build_id}")
        print(f"session: {session.session_id}")
        print(f"workspace: {session.workspace.root}")
        print(
            "harness: "
            f"{session.harness.get('name')} "
            f"{session.harness.get('version')} "
            f"adapter={session.harness.get('adapter_version')}"
        )

        assert adapter.client is not None and session.session_id
        try:
            live = adapter.client.get_session(session.session_id)
            print(f"model: {live.get('model')}")
        except Exception as exc:  # noqa: BLE001 - informational only
            print(f"model info unavailable: {type(exc).__name__}: {exc}")

        # Subscribe before sending the prompt so early events such as
        # session.execution.started are not lost.
        events = _start_event_pump(adapter, session.build_id)
        first = _next_event(events, time.monotonic() + args.timeout)
        if first[0] == "error":
            raise first[1]
        if first[0] == "event":
            print(f"event: {first[1].type} ({first[1].source_type})")
        elif first[0] == "timeout":
            print("event: no initial event within timeout")

        if args.permission_probe:
            created = adapter.client.create_permission_request(
                session.session_id,
                action="shell",
                resources=["echo harness-smoke"],
            )
            print(
                f"permission probe: id={created.get('id')} "
                f"effect={created.get('effect')}"
            )
            pending = adapter.client.list_permissions(session.session_id)
            print(f"permission pending: {len(pending)}")
            for item in pending:
                request_id = item.get("id")
                if request_id:
                    adapter.reply_permission(
                        session.build_id,
                        str(request_id),
                        args.permission,
                    )
                    print(
                        f"permission: {request_id} -> {args.permission}"
                    )

        if args.prompt:
            response = adapter.send_prompt(session.build_id, args.prompt)
            print(f"prompt admitted: {response.get('id')}")
            if args.pause_after_prompt:
                paused = adapter.pause(session.build_id)
                print(f"paused: {paused.state}")
            deadline = time.monotonic() + args.timeout
            seen = 0
            while time.monotonic() < deadline:
                kind, item = _next_event(events, deadline)
                if kind == "timeout":
                    print("event: timeout")
                    break
                if kind == "end":
                    break
                if kind == "error":
                    raise item
                event = item
                seen += 1
                print(f"event: {event.type} ({event.source_type})")
                if args.cancel_after_start and event.type == "phase_changed":
                    canceled = adapter.cancel(session.build_id)
                    print(f"cancelled: {canceled.state}/{canceled.outcome}")
                    break
                if event.type == "permission_requested":
                    request_id = event.data.get("id")
                    if request_id:
                        adapter.reply_permission(
                            session.build_id,
                            str(request_id),
                            args.permission,
                        )
                        print(
                            f"permission: {request_id} -> {args.permission}"
                        )
                if event.type in {"finished", "error"}:
                    break
                if seen > 500:
                    print("event limit reached")
                    break
        else:
            print("prompt: skipped (no model call)")

        artifacts = adapter.collect_artifacts(session.build_id)
        print(f"artifacts: {len(artifacts)}")
    except (HarnessStateError, Exception) as exc:  # noqa: BLE001 - smoke boundary
        print(f"ERROR: {type(exc).__name__}: {exc}")
        if adapter.server is not None and adapter.server.logs:
            print("server log tail:")
            for line in list(adapter.server.logs)[-15:]:
                print(f"  {line}")
        return 1
    finally:
        if session is not None:
            try:
                closed = adapter.close(session.build_id)
                print(f"closed: {closed.state}/{closed.outcome}")
                if args.pause_after_prompt:
                    log = closed.workspace.control_dir / "pause-gate.log"
                    if log.is_file():
                        print("pause-gate log:")
                        print(log.read_text(encoding="utf-8"))
                result = closed.workspace.read_result()
                print(json.dumps(result, ensure_ascii=False, indent=2)[:4000])
            except Exception as exc:  # noqa: BLE001 - cleanup boundary
                print(f"close ERROR: {type(exc).__name__}: {exc}")
        if adapter.server is not None:
            adapter.server.stop()
        if args.keep:
            print(f"kept: {workspace_root}")
        elif temporary_created:
            shutil.rmtree(workspace_root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
