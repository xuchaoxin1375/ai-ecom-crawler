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
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from ecom_crawler.harness import BuildTask, OpenCodeHttpAdapter
from ecom_crawler.harness.adapter import HarnessStateError


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
        "--cancel-after-start",
        action="store_true",
        help="cancel/interrupt after the first execution-started event",
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

        if args.permission_probe:
            assert adapter.client is not None and session.session_id
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
            deadline_events = 0
            for event in adapter.stream_events(session.build_id):
                deadline_events += 1
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
                if deadline_events > 500:
                    print("event limit reached")
                    break
        else:
            # A live-only subscription receives server.connected immediately.
            stream = adapter.stream_events(session.build_id)
            try:
                for _ in range(1):
                    event = next(stream)
                    print(f"event: {event.type} ({event.source_type})")
            finally:
                stream.close()
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
