"""FastAPI application for the motivation video pipeline."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.config import CLIPS_DIR, DATABASE_CLIPS_DIR, LOGS_DIR, ROOT_DIR, settings
from backend.services.clipper import get_source_video_path
from backend.services.database import (
    all_tags,
    delete_clip,
    get_clip,
    get_saved_clip_path,
    list_clips,
    register_clip,
    save_clip_to_disk,
    update_clip,
)
from backend.services.job_logs import configure_logging, get_job_logs, list_recent_logs
from backend.services.pipeline import (
    create_job,
    create_manual_clip,
    get_job,
    list_jobs,
    list_studio_jobs,
    run_ai_analysis,
)

configure_logging()

FRONTEND_DIR = ROOT_DIR / "frontend"

app = FastAPI(title="Motivation Video Assembler", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    youtube_url: str
    auto_analyze: bool = True


class ManualClipRequest(BaseModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    title: str = ""
    group: str = "quotable"
    tags: list[str] = Field(default_factory=list)
    quote: str = ""
    save_local: bool = False


class ClipUpdateRequest(BaseModel):
    title: str | None = None
    group: str | None = None
    tags: list[str] | None = None
    labels: list[str] | None = None
    quote: str | None = None


class AiAnalysisRequest(BaseModel):
    replace_existing: bool = True


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "openai_configured": bool(settings.openai_api_key),
        "model": settings.openai_model,
        "verify_model": settings.verify_model,
        "database_path": str(ROOT_DIR / "data" / "database"),
        "logs_path": str(LOGS_DIR),
    }


@app.post("/api/analyze")
def analyze_video(payload: AnalyzeRequest) -> dict:
    if not payload.youtube_url.strip():
        raise HTTPException(status_code=400, detail="YouTube URL is required.")

    if payload.auto_analyze and not settings.openai_api_key:
        raise HTTPException(
            status_code=400,
            detail="OPENAI_API_KEY is not configured. Use prepare-only mode or add your key.",
        )

    job = create_job(payload.youtube_url, auto_analyze=payload.auto_analyze)
    return {"job": job}


@app.get("/api/jobs")
def jobs() -> dict:
    return {"jobs": list_jobs()}


@app.get("/api/jobs/studio")
def studio_jobs() -> dict:
    return {"jobs": list_studio_jobs()}


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"job": job}


@app.get("/api/jobs/{job_id}/transcript")
def job_transcript(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {
        "job_id": job_id,
        "language": job.get("language"),
        "transcript_source": job.get("transcript_source"),
        "segments": job.get("transcript") or [],
    }


@app.get("/api/jobs/{job_id}/source")
def job_source_video(job_id: str) -> FileResponse:
    path = get_source_video_path(job_id)
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="Source video not found.")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@app.get("/api/jobs/{job_id}/logs")
def job_logs(job_id: str, limit: int = Query(default=200, ge=1, le=1000)) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"job_id": job_id, "logs": get_job_logs(job_id, limit=limit)}


@app.get("/api/logs/recent")
def recent_logs(limit: int = Query(default=50, ge=1, le=200)) -> dict:
    return {"logs": list_recent_logs(limit=limit)}


@app.post("/api/jobs/{job_id}/analyze-ai")
def trigger_ai_analysis(job_id: str, payload: AiAnalysisRequest | None = None) -> dict:
    if not settings.openai_api_key:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY is not configured.")

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if not job.get("transcript"):
        raise HTTPException(status_code=400, detail="Job has no transcript yet.")
    if job.get("status") == "running":
        raise HTTPException(status_code=409, detail="Job is already running.")

    replace_existing = payload.replace_existing if payload else True
    run_ai_analysis(job_id, replace_existing=replace_existing)
    return {"job_id": job_id, "status": "running", "replace_existing": replace_existing}


@app.post("/api/jobs/{job_id}/clips")
def add_manual_clip(job_id: str, payload: ManualClipRequest) -> dict:
    try:
        clip = create_manual_clip(
            job_id,
            payload.start_seconds,
            payload.end_seconds,
            title=payload.title,
            group=payload.group,
            tags=payload.tags,
            quote=payload.quote,
            save_local=payload.save_local,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"clip": clip}


@app.get("/api/library")
def library(
    q: str = Query(default=""),
    group: str = Query(default="all"),
    tag: str = Query(default=""),
    source_type: str = Query(default=""),
) -> dict:
    clips = list_clips(query=q, group=group, tag=tag, source_type=source_type)
    return {"clips": clips, "groups": _group_labels(), "tags": all_tags()}


@app.get("/api/database/clips/{clip_id}")
def database_clip_detail(clip_id: str) -> dict:
    clip = get_clip(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found.")
    return {"clip": clip}


@app.patch("/api/database/clips/{clip_id}")
def patch_clip(clip_id: str, payload: ClipUpdateRequest) -> dict:
    fields = payload.model_dump(exclude_none=True)
    clip = update_clip(clip_id, **fields)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found.")
    return {"clip": clip}


@app.post("/api/database/clips/{clip_id}/save")
def save_clip_local(clip_id: str) -> dict:
    try:
        clip = save_clip_to_disk(clip_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"clip": clip, "message": "Clip saved to local database folder."}


@app.delete("/api/database/clips/{clip_id}")
def remove_clip(clip_id: str) -> dict:
    if not delete_clip(clip_id):
        raise HTTPException(status_code=404, detail="Clip not found.")
    return {"deleted": clip_id}


@app.get("/api/database/clips/{clip_id}/download")
def download_saved_clip(clip_id: str) -> FileResponse:
    clip = get_clip(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found.")

    saved = get_saved_clip_path(clip_id)
    if saved:
        filename = f"{_safe_filename(clip.get('title', clip_id))}.mp4"
        return FileResponse(saved, media_type="video/mp4", filename=filename)

    source = CLIPS_DIR / clip["job_id"] / clip["clip_filename"]
    if not source.exists():
        raise HTTPException(status_code=404, detail="Clip file not found.")

    filename = f"{_safe_filename(clip.get('title', clip_id))}.mp4"
    return FileResponse(source, media_type="video/mp4", filename=filename)


@app.get("/api/clips/{job_id}/{filename}")
def serve_clip(job_id: str, filename: str) -> FileResponse:
    clip_path = (CLIPS_DIR / job_id / filename).resolve()
    allowed_root = (CLIPS_DIR / job_id).resolve()

    if not str(clip_path).startswith(str(allowed_root)) or not clip_path.exists():
        raise HTTPException(status_code=404, detail="Clip not found.")

    return FileResponse(clip_path, media_type="video/mp4", filename=filename)


def _group_labels() -> dict[str, str]:
    return {
        "hook": "Hook",
        "emotional_peak": "Emotional Peak",
        "wisdom": "Wisdom",
        "story_climax": "Story Climax",
        "call_to_action": "Call to Action",
        "quotable": "Quotable",
        "manual": "Manual",
    }


def _safe_filename(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in value)
    return cleaned.strip()[:80] or "clip"


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
