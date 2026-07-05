"""Local motivation clip database — indexed, labeled, searchable."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.config import CLIPS_DIR, DATABASE_CLIPS_DIR, DATABASE_DIR, DATABASE_INDEX, ROOT_DIR

_lock = __import__("threading").Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_index() -> dict[str, Any]:
    if not DATABASE_INDEX.exists():
        return {"version": 1, "clips": []}
    return json.loads(DATABASE_INDEX.read_text())


def _save_index(index: dict[str, Any]) -> None:
    DATABASE_INDEX.write_text(json.dumps(index, indent=2))


def register_clip(entry: dict[str, Any]) -> dict[str, Any]:
    """Add or update a clip in the database index."""
    clip_id = entry.get("id") or entry.get("moment_id") or uuid.uuid4().hex[:12]
    now = _now()

    record = {
        "id": clip_id,
        "job_id": entry["job_id"],
        "moment_id": entry.get("moment_id", clip_id),
        "title": entry.get("title", "Untitled clip"),
        "quote": entry.get("quote", ""),
        "group": entry.get("group", "quotable"),
        "tags": entry.get("tags") or [],
        "labels": entry.get("labels") or [],
        "start_seconds": float(entry.get("start_seconds", 0)),
        "end_seconds": float(entry.get("end_seconds", 0)),
        "source_type": entry.get("source_type", "ai"),
        "video_title": entry.get("video_title"),
        "youtube_url": entry.get("youtube_url"),
        "clip_filename": entry.get("clip_filename"),
        "clip_url": entry.get("clip_url"),
        "local_path": entry.get("local_path"),
        "saved_at": entry.get("saved_at"),
        "created_at": entry.get("created_at", now),
        "updated_at": now,
    }

    with _lock:
        index = _load_index()
        clips = index.get("clips", [])
        existing = next((i for i, c in enumerate(clips) if c["id"] == clip_id), None)
        if existing is not None:
            record["created_at"] = clips[existing].get("created_at", now)
            record["saved_at"] = clips[existing].get("saved_at") or record.get("saved_at")
            clips[existing] = record
        else:
            clips.append(record)
        index["clips"] = clips
        _save_index(index)

    return record


def get_clip(clip_id: str) -> dict[str, Any] | None:
    index = _load_index()
    return next((c for c in index.get("clips", []) if c["id"] == clip_id), None)


def update_clip(clip_id: str, **fields: Any) -> dict[str, Any] | None:
    with _lock:
        index = _load_index()
        clips = index.get("clips", [])
        for clip in clips:
            if clip["id"] == clip_id:
                for key, value in fields.items():
                    if value is not None:
                        clip[key] = value
                clip["updated_at"] = _now()
                _save_index(index)
                return dict(clip)
    return None


def delete_clips_for_job(job_id: str, *, source_type: str = "") -> int:
    """Remove indexed clips for a job, optionally filtered by source_type."""
    removed = 0
    with _lock:
        index = _load_index()
        clips = index.get("clips", [])
        kept: list[dict[str, Any]] = []
        for clip in clips:
            if clip.get("job_id") == job_id and (not source_type or clip.get("source_type") == source_type):
                _remove_clip_files(clip)
                removed += 1
            else:
                kept.append(clip)
        if removed:
            index["clips"] = kept
            _save_index(index)
    return removed


def _remove_clip_files(clip: dict[str, Any]) -> None:
    clip_id = clip.get("id")
    if clip_id:
        saved = DATABASE_CLIPS_DIR / f"{clip_id}.mp4"
        if saved.exists():
            saved.unlink()

    filename = clip.get("clip_filename")
    job_id = clip.get("job_id")
    if filename and job_id:
        source = CLIPS_DIR / job_id / filename
        if source.exists():
            source.unlink()


def delete_clip(clip_id: str) -> bool:
    with _lock:
        index = _load_index()
        clips = index.get("clips", [])
        target = next((c for c in clips if c["id"] == clip_id), None)
        kept = [c for c in clips if c["id"] != clip_id]
        if len(kept) == len(clips):
            return False
        index["clips"] = kept
        _save_index(index)

    if target:
        _remove_clip_files(target)
    return True


def list_clips(
    *,
    query: str = "",
    group: str = "",
    tag: str = "",
    source_type: str = "",
    job_id: str = "",
) -> list[dict[str, Any]]:
    clips = _load_index().get("clips", [])
    results = clips

    if group and group != "all":
        results = [c for c in results if c.get("group") == group]
    if tag:
        results = [c for c in results if tag.lower() in [t.lower() for t in c.get("tags", [])]]
    if source_type:
        results = [c for c in results if c.get("source_type") == source_type]
    if job_id:
        results = [c for c in results if c.get("job_id") == job_id]
    if query:
        q = query.lower()
        results = [
            c
            for c in results
            if q in c.get("title", "").lower()
            or q in c.get("quote", "").lower()
            or q in c.get("video_title", "").lower()
            or any(q in t.lower() for t in c.get("tags", []))
            or any(q in label.lower() for label in c.get("labels", []))
        ]

    results.sort(key=lambda c: c.get("created_at", ""), reverse=True)
    return results


def all_tags() -> list[str]:
    tags: set[str] = set()
    for clip in _load_index().get("clips", []):
        tags.update(clip.get("tags") or [])
    return sorted(tags)


def save_clip_to_disk(clip_id: str) -> dict[str, Any]:
    """Copy clip MP4 into data/database/clips/ for permanent local storage."""
    clip = get_clip(clip_id)
    if not clip:
        raise FileNotFoundError("Clip not found in database index.")

    source = CLIPS_DIR / clip["job_id"] / clip["clip_filename"]
    if not source.exists():
        raise FileNotFoundError("Clip file missing on disk.")

    dest = DATABASE_CLIPS_DIR / f"{clip_id}.mp4"
    shutil.copy2(source, dest)

    return update_clip(
        clip_id,
        local_path=str(dest.relative_to(ROOT_DIR)),
        saved_at=_now(),
    ) or clip


def get_saved_clip_path(clip_id: str) -> Path | None:
    clip = get_clip(clip_id)
    if not clip:
        return None
    path = DATABASE_CLIPS_DIR / f"{clip_id}.mp4"
    return path if path.exists() else None
