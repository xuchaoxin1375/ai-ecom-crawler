"""Per-build workspace layout from ADR 0005."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import BuildTask, HarnessEvent, utc_now


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


@dataclass
class BuildWorkspace:
    root: Path
    build_id: str

    @property
    def input_dir(self) -> Path:
        return self.root / "input"

    @property
    def work_dir(self) -> Path:
        return self.root / "work"

    @property
    def out_dir(self) -> Path:
        return self.root / "out"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def control_dir(self) -> Path:
        return self.root / "control"

    @property
    def task_path(self) -> Path:
        return self.input_dir / "build-task.json"

    @property
    def pause_path(self) -> Path:
        return self.control_dir / "pause.json"

    @property
    def session_path(self) -> Path:
        return self.out_dir / "session.ndjson"

    @property
    def result_path(self) -> Path:
        return self.out_dir / "result.json"

    @classmethod
    def create(
        cls,
        workspace_root: str | Path,
        task: BuildTask,
        *,
        force: bool = False,
    ) -> BuildWorkspace:
        base = Path(workspace_root).resolve()
        root = base / task.build_id
        if root.exists() and (
            not root.is_dir() or (any(root.iterdir()) and not force)
        ):
            raise FileExistsError(f"build workspace already exists: {root}")
        workspace = cls(root=root, build_id=task.build_id)
        for directory in (
            workspace.input_dir,
            workspace.work_dir,
            workspace.out_dir,
            workspace.logs_dir,
            workspace.control_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        workspace.write_task(task)
        workspace.set_paused(False)
        workspace.session_path.touch(exist_ok=True)
        workspace.write_result(
            {
                "build_id": task.build_id,
                "state": "CREATED",
                "outcome": None,
                "created_at": utc_now(),
                "updated_at": utc_now(),
                "artifacts": {},
                "errors": [],
                "limitations": [
                    "Build workspace only; plan verification and business sign-off are separate.",
                ],
            }
        )
        return workspace

    def write_task(self, task: BuildTask) -> None:
        _atomic_json(self.task_path, task.to_dict())

    def set_paused(self, paused: bool) -> None:
        _atomic_json(
            self.pause_path,
            {"paused": bool(paused), "updated_at": utc_now()},
        )

    def is_paused(self) -> bool:
        try:
            payload = json.loads(self.pause_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return True  # fail closed for the pause gate
        return bool(payload.get("paused"))

    def append_event(self, event: HarnessEvent) -> None:
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        with self.session_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    def write_result(self, payload: dict[str, Any]) -> None:
        payload = dict(payload)
        payload.setdefault("build_id", self.build_id)
        payload["updated_at"] = utc_now()
        _atomic_json(self.result_path, payload)

    def update_result(self, **fields: Any) -> dict[str, Any]:
        payload = self.read_result()
        payload.update(fields)
        self.write_result(payload)
        return payload

    def read_result(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def artifact_map(self) -> dict[str, str]:
        artifacts: dict[str, str] = {}
        if not self.out_dir.is_dir():
            return artifacts
        for path in sorted(self.out_dir.rglob("*")):
            if path.is_file():
                artifacts[path.relative_to(self.root).as_posix()] = str(path)
        return artifacts
