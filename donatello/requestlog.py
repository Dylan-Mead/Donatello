"""Per-request logging of plans and sub tasks to a log file in the repo base folder."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_LOG_PATH = Path(__file__).resolve().parent.parent / "donatello.log"


def new_request_id() -> str:
    return uuid.uuid4().hex


class RequestLog:
    """Appends one JSON line per plan/task event, tagged with a request ID."""

    def __init__(self, request_id: str | None = None, path: Path | None = None) -> None:
        self.request_id = request_id or new_request_id()
        self.path = Path(path or os.getenv("DONATELLO_LOG_FILE") or DEFAULT_LOG_PATH)

    def _write(self, event: str, **fields: Any) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": self.request_id,
            "event": event,
            **fields,
        }
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
        except OSError:
            pass

    def plan(self, plan: dict[str, Any] | None, duration_seconds: float, error: str | None = None) -> None:
        fields: dict[str, Any] = {"plan": plan, "duration_seconds": round(duration_seconds, 3)}
        if error:
            fields["error"] = error
        self._write("plan", **fields)

    def task(
        self,
        title: str,
        duration_seconds: float,
        files: list[str],
        error: str | None = None,
    ) -> None:
        fields: dict[str, Any] = {
            "task": title,
            "duration_seconds": round(duration_seconds, 3),
            "files_written": files,
        }
        if error:
            fields["error"] = error
        self._write("task", **fields)
