"""Download source video and extract clip segments with ffmpeg."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yt_dlp

from backend.config import VIDEOS_DIR, CLIPS_DIR


class VideoError(Exception):
    pass


def get_source_video_path(job_id: str) -> Path | None:
    video_dir = VIDEOS_DIR / job_id
    if not video_dir.exists():
        return None
    for path in video_dir.iterdir():
        if path.suffix.lower() in {".mp4", ".webm", ".mkv"}:
            return path
    return None


def download_video(video_id: str, job_id: str) -> tuple[Path, str]:
    output_dir = VIDEOS_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(output_dir / "source.%(ext)s")

    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": output_template,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }

    url = f"https://www.youtube.com/watch?v={video_id}"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                raise VideoError("Could not download video metadata.")

            title = str(info.get("title") or video_id)
            requested = info.get("requested_downloads") or []
            if requested:
                filepath = requested[0].get("filepath")
                if filepath:
                    return Path(filepath), title

            ext = info.get("ext", "mp4")
            candidate = output_dir / f"source.{ext}"
            if candidate.exists():
                return candidate, title

            for path in output_dir.iterdir():
                if path.suffix.lower() in {".mp4", ".webm", ".mkv"}:
                    return path, title

            raise VideoError("Download finished but no video file was found.")
    except VideoError:
        raise
    except Exception as exc:
        raise VideoError(f"Video download failed: {exc}") from exc


def get_video_duration(path: Path) -> float | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        return None


def extract_clip(
    source_video: Path,
    job_id: str,
    moment_id: str,
    start_seconds: float,
    end_seconds: float,
) -> Path:
    if not _ffmpeg_available():
        raise VideoError("ffmpeg is not installed. Install it with: brew install ffmpeg")

    clip_dir = CLIPS_DIR / job_id
    clip_dir.mkdir(parents=True, exist_ok=True)
    output_path = clip_dir / f"{moment_id}.mp4"

    duration = max(1.0, end_seconds - start_seconds)
    pad_start = max(0.0, start_seconds - 0.3)

    command = [
        "ffmpeg",
        "-y",
        "-ss",
        str(pad_start),
        "-i",
        str(source_video),
        "-t",
        str(duration + 0.6),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise VideoError(f"ffmpeg clip extraction failed: {stderr or exc}") from exc

    if not output_path.exists():
        raise VideoError("Clip file was not created.")

    return output_path


def _ffmpeg_available() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
