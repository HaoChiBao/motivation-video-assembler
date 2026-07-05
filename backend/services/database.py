"""Local motivation clip database — indexed, labeled, searchable."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.config import CLIPS_DIR, DATABASE_CLIPS_DIR, DATABASE_DIR, DATABASE_INDEX, DATABASE_VIDEOS_DIR, JOBS_DIR, ROOT_DIR
from backend.services.clipper import get_source_video_path

_lock = __import__("threading").Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_index() -> dict[str, Any]:
    if not DATABASE_INDEX.exists():
        return {"version": 2, "clips": [], "sources": []}
    index = json.loads(DATABASE_INDEX.read_text())
    index.setdefault("clips", [])
    index.setdefault("sources", [])
    return index


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
        "rationale": entry.get("rationale", ""),
        "review_status": entry.get("review_status") or ("accepted" if entry.get("source_type") == "manual" else "pending"),
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
    review_status: str = "",
    include_pending: bool = False,
) -> list[dict[str, Any]]:
    clips = _load_index().get("clips", [])
    results = clips

    if not include_pending and not review_status:
        results = [c for c in results if c.get("review_status", "accepted") == "accepted"]
    elif review_status:
        results = [c for c in results if c.get("review_status", "accepted") == review_status]

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


def accept_clip(clip_id: str, *, save_local: bool = True) -> dict[str, Any]:
    """Mark a pending AI clip as accepted and optionally persist to the database folder."""
    clip = get_clip(clip_id)
    if not clip:
        raise FileNotFoundError("Clip not found in database index.")

    clip = update_clip(clip_id, review_status="accepted") or clip
    if save_local:
        clip = save_clip_to_disk(clip_id)
    return clip


def all_tags() -> list[str]:
    tags: set[str] = set()
    for clip in _load_index().get("clips", []):
        if clip.get("review_status", "accepted") != "accepted":
            continue
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


def register_source(entry: dict[str, Any]) -> dict[str, Any]:
    """Add or update a full source video in the database index."""
    source_id = entry.get("id") or entry.get("job_id")
    if not source_id:
        raise ValueError("Source id or job_id is required.")

    now = _now()
    record = {
        "id": source_id,
        "job_id": entry["job_id"],
        "video_title": entry.get("video_title"),
        "youtube_url": entry.get("youtube_url"),
        "video_id": entry.get("video_id"),
        "duration_seconds": float(entry["duration_seconds"]) if entry.get("duration_seconds") is not None else None,
        "language": entry.get("language"),
        "transcript_source": entry.get("transcript_source"),
        "local_path": entry.get("local_path"),
        "saved_at": entry.get("saved_at"),
        "created_at": entry.get("created_at", now),
        "updated_at": now,
    }

    with _lock:
        index = _load_index()
        sources = index.get("sources", [])
        existing = next((i for i, s in enumerate(sources) if s["id"] == source_id), None)
        if existing is not None:
            record["created_at"] = sources[existing].get("created_at", now)
            record["saved_at"] = sources[existing].get("saved_at") or record.get("saved_at")
            sources[existing] = record
        else:
            sources.append(record)
        index["sources"] = sources
        _save_index(index)

    return record


def get_source(source_id: str) -> dict[str, Any] | None:
    index = _load_index()
    return next((s for s in index.get("sources", []) if s["id"] == source_id), None)


def list_sources(*, query: str = "", job_id: str = "") -> list[dict[str, Any]]:
    sources = _load_index().get("sources", [])
    results = sources

    if job_id:
        results = [s for s in results if s.get("job_id") == job_id]
    if query:
        q = query.lower()
        results = [
            s
            for s in results
            if q in (s.get("video_title") or "").lower()
            or q in (s.get("youtube_url") or "").lower()
            or q in (s.get("video_id") or "").lower()
        ]

    results.sort(key=lambda item: item.get("saved_at") or item.get("created_at", ""), reverse=True)
    return results


def save_source_to_disk(job_id: str, *, job: dict[str, Any] | None = None) -> dict[str, Any]:
    """Copy the job's full source MP4 into data/database/videos/."""
    if job is None:
        job_path = JOBS_DIR / f"{job_id}.json"
        if not job_path.exists():
            raise FileNotFoundError("Job not found.")
        job = json.loads(job_path.read_text())

    source = get_source_video_path(job_id)
    if not source or not source.exists():
        raise FileNotFoundError("Source video file missing on disk.")

    DATABASE_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    dest = DATABASE_VIDEOS_DIR / f"{job_id}.mp4"
    shutil.copy2(source, dest)

    return register_source(
        {
            "id": job_id,
            "job_id": job_id,
            "video_title": job.get("video_title"),
            "youtube_url": job.get("youtube_url"),
            "video_id": job.get("video_id"),
            "duration_seconds": job.get("duration_seconds"),
            "language": job.get("language"),
            "transcript_source": job.get("transcript_source"),
            "local_path": str(dest.relative_to(ROOT_DIR)),
            "saved_at": _now(),
        }
    )


def get_saved_source_path(source_id: str) -> Path | None:
    source = get_source(source_id)
    if not source:
        return None
    path = DATABASE_VIDEOS_DIR / f"{source_id}.mp4"
    return path if path.exists() else None
