"""Fetch, normalize, and transcribe speech with timestamps."""

from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from openai import OpenAI
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

from backend.config import settings

_api = YouTubeTranscriptApi()


@dataclass
class TranscriptSegment:
    start: float
    duration: float
    text: str

    @property
    def end(self) -> float:
        return self.start + self.duration


class TranscriptError(Exception):
    pass


def extract_video_id(url: str) -> str:
    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url.strip())
        if match:
            return match.group(1)
    raise TranscriptError("Could not parse a YouTube video ID from the URL.")


def fetch_transcript(video_id: str) -> tuple[list[TranscriptSegment], str, str]:
    """Returns segments, language, and source ('youtube' or 'whisper')."""
    try:
        segments, language = _fetch_youtube_transcript(video_id)
        if segments:
            return segments, language, "youtube"
    except TranscriptError:
        pass

    raise TranscriptError(
        "No YouTube captions found. Prepare the video first, then use Whisper transcription."
    )


def fetch_transcript_with_fallback(video_path: Path, video_id: str) -> tuple[list[TranscriptSegment], str, str]:
    try:
        segments, language = _fetch_youtube_transcript(video_id)
        if segments:
            return segments, language, "youtube"
    except TranscriptError:
        pass

    if not settings.openai_api_key:
        raise TranscriptError(
            "No YouTube captions and OPENAI_API_KEY is missing for Whisper fallback."
        )

    segments = transcribe_with_whisper(video_path)
    return segments, "en", "whisper"


def _fetch_youtube_transcript(video_id: str) -> tuple[list[TranscriptSegment], str]:
    try:
        transcript_list = _api.list(video_id)
        transcript = None
        language = "en"

        try:
            transcript = transcript_list.find_transcript(["en", "en-US", "en-GB"])
            language = transcript.language_code
        except NoTranscriptFound:
            for item in transcript_list:
                if not item.is_generated:
                    transcript = item
                    language = item.language_code
                    break
            if transcript is None:
                transcript = next(iter(transcript_list))
                language = transcript.language_code

        fetched = transcript.fetch()
    except TranscriptsDisabled as exc:
        raise TranscriptError("Captions are disabled for this video.") from exc
    except VideoUnavailable as exc:
        raise TranscriptError("Video is unavailable.") from exc
    except Exception as exc:
        raise TranscriptError(f"Failed to fetch transcript: {exc}") from exc

    segments = [
        TranscriptSegment(
            start=float(snippet.start),
            duration=float(snippet.duration),
            text=str(snippet.text).strip(),
        )
        for snippet in fetched
        if str(snippet.text).strip()
    ]

    if not segments:
        raise TranscriptError("Transcript is empty.")

    return segments, language


def transcribe_with_whisper(video_path: Path) -> list[TranscriptSegment]:
    audio_path = _extract_audio(video_path)
    client = OpenAI(api_key=settings.openai_api_key)

    with audio_path.open("rb") as audio_file:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )

    segments: list[TranscriptSegment] = []
    raw_segments = getattr(result, "segments", None) or []

    for item in raw_segments:
        start = float(item.get("start", 0) if isinstance(item, dict) else getattr(item, "start", 0))
        end = float(item.get("end", start) if isinstance(item, dict) else getattr(item, "end", start))
        text = str(item.get("text", "") if isinstance(item, dict) else getattr(item, "text", "")).strip()
        if text:
            segments.append(TranscriptSegment(start=start, duration=max(0.1, end - start), text=text))

    if not segments and getattr(result, "text", ""):
        segments.append(TranscriptSegment(start=0.0, duration=1.0, text=str(result.text).strip()))

    if not segments:
        raise TranscriptError("Whisper returned an empty transcript.")

    return segments


def _extract_audio(video_path: Path) -> Path:
    temp = Path(tempfile.mkdtemp()) / "audio.mp3"
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "libmp3lame",
        "-q:a",
        "4",
        str(temp),
    ]
    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        raise TranscriptError(f"Audio extraction failed: {exc.stderr or exc}") from exc
    return temp


def segments_to_dicts(segments: list[TranscriptSegment]) -> list[dict]:
    return [asdict(segment) for segment in segments]


def dicts_to_segments(raw: list[dict]) -> list[TranscriptSegment]:
    return [
        TranscriptSegment(
            start=float(item["start"]),
            duration=float(item["duration"]),
            text=str(item["text"]),
        )
        for item in raw
    ]


def text_for_range(segments: list[TranscriptSegment], start: float, end: float) -> str:
    parts = [
        segment.text
        for segment in segments
        if segment.end >= start and segment.start <= end
    ]
    return " ".join(parts).strip()


def format_transcript_for_analysis(segments: list[TranscriptSegment]) -> str:
    lines: list[str] = []
    for segment in segments:
        start = _format_timestamp(segment.start)
        end = _format_timestamp(segment.end)
        lines.append(f"[{start} → {end}] {segment.text}")
    return "\n".join(lines)


def _format_timestamp(seconds: float) -> str:
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
