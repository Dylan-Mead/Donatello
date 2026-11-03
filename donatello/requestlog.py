"""Per-request logging of plans and sub tasks to a log file in the repo base folder."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_LOG_PATH = Path(__file__).resolve().parent.parent / "donatello.log"


def _shorten_home(value: Any) -> Any:
    """Recursively replace the user's home directory with "~" in logged strings."""
    home = str(Path.home())
    if isinstance(value, str):
        return re.sub(re.escape(home) + r"(?=/|$|\W)", "~", value) if home not in ("", "/") else value
    if isinstance(value, list):
        return [_shorten_home(item) for item in value]
    if isinstance(value, dict):
        return {key: _shorten_home(item) for key, item in value.items()}
    return value


def new_request_id() -> str:
    return uuid.uuid4().hex


class RequestLog:
    """Appends one indented JSON entry per plan/task event, tagged with a request ID."""

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
                handle.write(json.dumps(_shorten_home(record), indent=2) + "\n")
        except OSError:
            pass

    def plan(
        self,
        plan: dict[str, Any] | None,
        duration_seconds: float,
        error: str | None = None,
        request: dict[str, Any] | None = None,
    ) -> None:
        """Log a plan; `request` holds the original request text and CLI arguments."""
        fields: dict[str, Any] = dict(request or {})
        fields.update({"plan": plan, "duration_seconds": round(duration_seconds, 3)})
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
