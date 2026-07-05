"""Two-pass OpenAI semantic analysis for motivational moments."""

from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from backend.config import settings

MOMENT_GROUPS = [
    "hook",
    "emotional_peak",
    "wisdom",
    "story_climax",
    "call_to_action",
    "quotable",
]

ANALYSIS_SYSTEM_PROMPT = """You are an expert editor of motivational and speech content.
Your job is to read a timestamped transcript and identify the strongest clip-worthy moments.

Group moments into these categories:
- hook: Opening lines that grab attention immediately
- emotional_peak: The most emotionally charged delivery
- wisdom: Clear, memorable insight or lesson
- story_climax: Peak of a narrative arc or personal story
- call_to_action: Direct challenge or invitation to act
- quotable: Standalone lines people would share or quote

Rules:
1. Use ONLY timestamps that appear in the transcript.
2. Each moment needs start_seconds, end_seconds (end > start), title, quote, group, and rationale.
3. Clips should be 8–45 seconds — long enough to land, short enough for social.
4. Prefer contiguous transcript lines; do not invent text.
5. Return at most {max_per_group} moments per group.
6. Skip weak filler; prioritize density of impact over quantity.

Respond with valid JSON only:
{{
  "video_summary": "one sentence",
  "moments": [
    {{
      "id": "hook-1",
      "group": "hook",
      "title": "short label",
      "quote": "exact or lightly trimmed quote from transcript",
      "start_seconds": 0.0,
      "end_seconds": 12.5,
      "confidence": 0.0,
      "rationale": "why this moment works"
    }}
  ]
}}"""

VERIFY_SYSTEM_PROMPT = """You are a senior editorial QA reviewer for motivational video clips.
You receive a transcript and a draft list of clip moments.

Double-check each moment:
- Timestamps must align with the transcript content
- Quotes must match what is actually said
- Clips must be self-contained and compelling
- Remove duplicates or overlapping moments (keep the stronger one)
- Fix miscategorized groups when obvious
- Adjust boundaries so clips start/end cleanly

Return the refined list in the same JSON schema. Respond with valid JSON only:
{{
  "video_summary": "one sentence",
  "moments": [ ... ],
  "review_notes": "brief summary of changes made"
}}"""


class AnalysisError(Exception):
    pass


def analyze_moments(transcript_text: str, video_duration_hint: float | None = None) -> dict[str, Any]:
    if not settings.openai_api_key:
        raise AnalysisError("OPENAI_API_KEY is not set. Add it to your .env file.")

    client = OpenAI(api_key=settings.openai_api_key)
    duration_note = ""
    if video_duration_hint:
        duration_note = f"\n\nVideo duration is approximately {video_duration_hint:.0f} seconds."

    draft = _run_analysis_pass(
        client,
        settings.openai_model,
        ANALYSIS_SYSTEM_PROMPT.format(max_per_group=settings.max_moments_per_group),
        transcript_text,
        duration_note,
    )

    verified = _run_analysis_pass(
        client,
        settings.verify_model,
        VERIFY_SYSTEM_PROMPT,
        transcript_text,
        duration_note,
        prior_result=draft,
    )

    verified["analysis_model"] = settings.openai_model
    verified["verify_model"] = settings.verify_model
    verified["draft_moment_count"] = len(draft.get("moments", []))
    return verified


def _run_analysis_pass(
    client: OpenAI,
    model: str,
    system_prompt: str,
    transcript_text: str,
    duration_note: str,
    prior_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    user_content = f"Transcript:\n\n{transcript_text}{duration_note}"
    if prior_result is not None:
        user_content += f"\n\nDraft analysis to verify and refine:\n{json.dumps(prior_result, indent=2)}"

    response = client.chat.completions.create(
        model=model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )

    content = response.choices[0].message.content or ""
    parsed = _parse_json(content)
    parsed["moments"] = _normalize_moments(parsed.get("moments", []))
    return parsed


def _parse_json(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise AnalysisError("Model returned invalid JSON.") from None


def _normalize_moments(raw_moments: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()

    for index, item in enumerate(raw_moments):
        if not isinstance(item, dict):
            continue

        group = str(item.get("group", "quotable")).lower().strip()
        if group not in MOMENT_GROUPS:
            group = "quotable"

        start = max(0.0, float(item.get("start_seconds", 0)))
        end = max(start + 3.0, float(item.get("end_seconds", start + 10)))

        if end - start > 60:
            end = start + 45
        if end - start < 5:
            end = start + 8

        key = (int(start), int(end))
        if key in seen:
            continue
        seen.add(key)

        normalized.append(
            {
                "id": str(item.get("id") or f"{group}-{index + 1}"),
                "group": group,
                "title": str(item.get("title") or f"{group.replace('_', ' ').title()} moment").strip(),
                "quote": str(item.get("quote") or "").strip(),
                "start_seconds": round(start, 2),
                "end_seconds": round(end, 2),
                "confidence": float(item.get("confidence", 0.8)),
                "rationale": str(item.get("rationale") or "").strip(),
            }
        )

    normalized.sort(key=lambda moment: moment["start_seconds"])
    return normalized
