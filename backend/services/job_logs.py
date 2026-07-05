"""Structured job and application logging."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.config import LOGS_DIR

APP_LOG_PATH = LOGS_DIR / "app.log"
JOB_LOGS_DIR = LOGS_DIR / "jobs"

logger = logging.getLogger("assembler")


def configure_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    JOB_LOGS_DIR.mkdir(parents=True, exist_ok=True)

    if logger.handlers:
        return

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    file_handler = logging.FileHandler(APP_LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_log_path(job_id: str) -> Path:
    return JOB_LOGS_DIR / f"{job_id}.jsonl"


def _json_safe(value: Any) -> Any:
    """Convert arbitrary objects into JSON-serializable values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump())
    if hasattr(value, "dict"):
        try:
            return _json_safe(value.dict())
        except TypeError:
            pass
    return str(value)


def log_job(
    job_id: str,
    level: str,
    event: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry = {
        "ts": _now(),
        "level": level,
        "event": event,
        "message": message,
        "details": _json_safe(details or {}),
    }

    path = _job_log_path(job_id)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    log_line = f"[job:{job_id}] {event}: {message}"
    if level == "error":
        logger.error(log_line)
    elif level == "warning":
        logger.warning(log_line)
    else:
        logger.info(log_line)

    return entry


def get_job_logs(job_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
    path = _job_log_path(job_id)
    if not path.exists():
        return []

    lines = path.read_text(encoding="utf-8").splitlines()
    entries: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            entries.append(
                {
                    "ts": _now(),
                    "level": "warning",
                    "event": "log_parse_error",
                    "message": line[:500],
                    "details": {},
                }
            )
    return entries


def list_recent_logs(*, limit: int = 50) -> list[dict[str, Any]]:
    paths = sorted(JOB_LOGS_DIR.glob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True)
    entries: list[dict[str, Any]] = []

    for path in paths:
        job_id = path.stem
        for entry in reversed(get_job_logs(job_id, limit=20)):
            entry = dict(entry)
            entry["job_id"] = job_id
            entries.append(entry)
            if len(entries) >= limit:
                break
        if len(entries) >= limit:
            break

    entries.sort(key=lambda item: item.get("ts", ""), reverse=True)
    return entries[:limit]
