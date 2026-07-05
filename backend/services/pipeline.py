"""Job orchestration for the motivation video pipeline."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.config import JOBS_DIR, VIDEOS_DIR
from backend.services.analyzer import AnalysisError, analyze_moments
from backend.services.clipper import VideoError, download_video, extract_clip, get_video_duration, get_source_video_path
from backend.services.database import register_clip, save_clip_to_disk
from backend.services.transcript import (
    TranscriptError,
    dicts_to_segments,
    extract_video_id,
    fetch_transcript_with_fallback,
    format_transcript_for_analysis,
    segments_to_dicts,
    text_for_range,
)

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


def create_job(youtube_url: str, *, auto_analyze: bool = True) -> dict[str, Any]:
    job_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()

    job = {
        "id": job_id,
        "youtube_url": youtube_url.strip(),
        "video_id": None,
        "status": "queued",
        "stage": "queued",
        "progress": 0,
        "error": None,
        "created_at": now,
        "updated_at": now,
        "video_title": None,
        "language": None,
        "transcript_source": None,
        "transcript": [],
        "source_video_path": None,
        "analysis": None,
        "clips": [],
        "auto_analyze": auto_analyze,
    }

    with _lock:
        _jobs[job_id] = job
        _persist_job(job)

    thread = threading.Thread(target=_run_pipeline, args=(job_id,), daemon=True)
    thread.start()
    return job


def run_ai_analysis(job_id: str) -> None:
    thread = threading.Thread(target=_run_ai_pass, args=(job_id,), daemon=True)
    thread.start()


def create_manual_clip(
    job_id: str,
    start_seconds: float,
    end_seconds: float,
    *,
    title: str = "",
    group: str = "quotable",
    tags: list[str] | None = None,
    quote: str = "",
    save_local: bool = False,
) -> dict[str, Any]:
    job = get_job(job_id)
    if not job:
        raise ValueError("Job not found.")
    if job.get("status") not in {"prepared", "completed"}:
        raise ValueError("Job is not ready for clipping.")

    if end_seconds <= start_seconds:
        raise ValueError("End time must be after start time.")

    source = get_source_video_path(job_id)
    if not source:
        raise VideoError("Source video not found.")

    segments = dicts_to_segments(job.get("transcript") or [])
    if not quote and segments:
        quote = text_for_range(segments, start_seconds, end_seconds)

    moment_id = f"manual-{uuid.uuid4().hex[:8]}"
    clip_path = extract_clip(source, job_id, moment_id, start_seconds, end_seconds)

    clip = {
        "id": moment_id,
        "group": group,
        "title": title or f"Manual clip {format_time(start_seconds)}",
        "quote": quote,
        "start_seconds": round(start_seconds, 2),
        "end_seconds": round(end_seconds, 2),
        "confidence": 1.0,
        "rationale": "Manually clipped from transcript timeline.",
        "source_type": "manual",
        "tags": tags or [],
        "clip_filename": clip_path.name,
        "clip_url": f"/api/clips/{job_id}/{clip_path.name}",
    }

    clips = list(job.get("clips") or [])

    db_entry = register_clip(
        {
            **clip,
            "id": f"{job_id}-{moment_id}",
            "job_id": job_id,
            "moment_id": moment_id,
            "video_title": job.get("video_title"),
            "youtube_url": job.get("youtube_url"),
        }
    )
    clip["id"] = db_entry["id"]
    clips.append(clip)
    _update(job_id, clips=clips)

    if save_local:
        db_entry = save_clip_to_disk(db_entry["id"])

    return {**clip, "database_id": db_entry["id"], "saved_at": db_entry.get("saved_at")}


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        if job:
            return dict(job)

    path = _job_path(job_id)
    if path.exists():
        return json.loads(path.read_text())
    return None


def list_jobs() -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []

    with _lock:
        jobs.extend(dict(job) for job in _jobs.values())

    for path in sorted(JOBS_DIR.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        job = json.loads(path.read_text())
        if job["id"] not in {existing["id"] for existing in jobs}:
            jobs.append(job)

    jobs.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return jobs


def list_studio_jobs() -> list[dict[str, Any]]:
    return [
        job
        for job in list_jobs()
        if job.get("status") in {"prepared", "completed"} and job.get("transcript")
    ]


def _run_pipeline(job_id: str) -> None:
    try:
        job = get_job(job_id)
        if not job:
            return

        _update(job_id, status="running", stage="parsing_url", progress=5)
        video_id = extract_video_id(job["youtube_url"])
        _update(job_id, video_id=video_id, stage="downloading_video", progress=20)

        source_video, video_title = download_video(video_id, job_id)
        duration = get_video_duration(source_video)

        _update(job_id, stage="fetching_transcript", progress=35)
        segments, language, transcript_source = fetch_transcript_with_fallback(source_video, video_id)
        transcript_text = format_transcript_for_analysis(segments)

        _update(
            job_id,
            video_title=video_title,
            language=language,
            transcript_source=transcript_source,
            transcript=segments_to_dicts(segments),
            source_video_path=str(source_video),
            status="prepared",
            stage="prepared",
            progress=50,
        )

        if job.get("auto_analyze", True):
            _run_ai_pass(job_id, transcript_text=transcript_text, duration=duration)
        else:
            _update(job_id, status="prepared", stage="prepared", progress=100)

    except (TranscriptError, AnalysisError, VideoError) as exc:
        _update(job_id, status="failed", stage="error", error=str(exc))
    except Exception as exc:
        _update(job_id, status="failed", stage="error", error=f"Unexpected error: {exc}")


def _run_ai_pass(job_id: str, transcript_text: str | None = None, duration: float | None = None) -> None:
    try:
        job = get_job(job_id)
        if not job:
            return

        segments = dicts_to_segments(job.get("transcript") or [])
        if not transcript_text:
            transcript_text = format_transcript_for_analysis(segments)

        source = get_source_video_path(job_id)
        if duration is None and source:
            duration = get_video_duration(source)

        _update(job_id, status="running", stage="analyzing", progress=60)
        analysis = analyze_moments(transcript_text, duration)
        moments = analysis.get("moments", [])

        _update(job_id, analysis=analysis, stage="extracting_clips", progress=75)

        clips: list[dict[str, Any]] = list(job.get("clips") or [])
        manual_clips = [c for c in clips if c.get("source_type") == "manual"]
        clips = manual_clips

        total = max(len(moments), 1)
        for index, moment in enumerate(moments):
            if not source:
                break
            clip_path = extract_clip(
                source,
                job_id,
                moment["id"],
                moment["start_seconds"],
                moment["end_seconds"],
            )
            clip = {
                **moment,
                "source_type": "ai",
                "tags": moment.get("tags") or [],
                "clip_filename": clip_path.name,
                "clip_url": f"/api/clips/{job_id}/{clip_path.name}",
            }
            db_entry = register_clip(
                {
                    **clip,
                    "id": f"{job_id}-{moment['id']}",
                    "job_id": job_id,
                    "moment_id": moment["id"],
                    "video_title": job.get("video_title"),
                    "youtube_url": job.get("youtube_url"),
                }
            )
            clip["id"] = db_entry["id"]
            clips.append(clip)
            progress = 75 + int(((index + 1) / total) * 20)
            _update(job_id, clips=clips, progress=min(progress, 95))

        _update(job_id, status="completed", stage="done", progress=100, clips=clips)

    except (AnalysisError, VideoError) as exc:
        _update(job_id, status="failed", stage="error", error=str(exc))
    except Exception as exc:
        _update(job_id, status="failed", stage="error", error=f"Unexpected error: {exc}")


def _update(job_id: str, **fields: Any) -> None:
    with _lock:
        job = _jobs.get(job_id) or get_job(job_id)
        if not job:
            return
        job.update(fields)
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        _jobs[job_id] = job
        _persist_job(job)


def _persist_job(job: dict[str, Any]) -> None:
    path = _job_path(job["id"])
    path.write_text(json.dumps(job, indent=2))


def _job_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def format_time(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes}:{secs:02d}"
