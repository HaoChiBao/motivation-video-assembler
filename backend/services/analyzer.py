"""Two-pass OpenAI semantic analysis for motivational moments."""

from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from backend.config import settings
from backend.services.job_logs import log_job

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
7. Keep each quote under 140 characters and rationale under 100 characters.
8. You MUST return complete, valid JSON. If space is tight, return fewer moments — never truncate mid-string.

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

Keep quotes under 140 characters. Return complete valid JSON only — never truncate mid-string.

Return the refined list in the same JSON schema. Respond with valid JSON only:
{{
  "video_summary": "one sentence",
  "moments": [ ... ],
  "review_notes": "brief summary of changes made"
}}"""

INCOMPLETE_FINISH_REASONS = {"length", "content_filter"}


class AnalysisError(Exception):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


def analyze_moments(
    transcript_text: str,
    video_duration_hint: float | None = None,
    *,
    job_id: str | None = None,
) -> dict[str, Any]:
    if not settings.openai_api_key:
        raise AnalysisError("OPENAI_API_KEY is not set. Add it to your .env file.")

    client = OpenAI(api_key=settings.openai_api_key)
    duration_note = ""
    if video_duration_hint:
        duration_note = f"\n\nVideo duration is approximately {video_duration_hint:.0f} seconds."

    if job_id:
        log_job(
            job_id,
            "info",
            "analysis_started",
            f"Starting two-pass analysis with {settings.openai_model}",
            details={
                "model": settings.openai_model,
                "verify_model": settings.verify_model,
                "reasoning_effort": settings.openai_reasoning_effort,
                "max_completion_tokens": settings.openai_max_completion_tokens,
            },
        )

    draft = _run_analysis_pass(
        client,
        settings.openai_model,
        "draft",
        ANALYSIS_SYSTEM_PROMPT.format(max_per_group=settings.max_moments_per_group),
        transcript_text,
        duration_note,
        job_id=job_id,
    )

    verified = _run_analysis_pass(
        client,
        settings.verify_model,
        "verify",
        VERIFY_SYSTEM_PROMPT,
        transcript_text,
        duration_note,
        prior_result=draft,
        job_id=job_id,
    )

    verified["analysis_model"] = settings.openai_model
    verified["verify_model"] = settings.verify_model
    verified["draft_moment_count"] = len(draft.get("moments", []))

    if job_id:
        log_job(
            job_id,
            "info",
            "analysis_completed",
            f"Analysis complete — {len(verified.get('moments', []))} moments",
            details={"moment_count": len(verified.get("moments", []))},
        )

    return verified


def _run_analysis_pass(
    client: OpenAI,
    model: str,
    pass_name: str,
    system_prompt: str,
    transcript_text: str,
    duration_note: str,
    prior_result: dict[str, Any] | None = None,
    *,
    job_id: str | None = None,
) -> dict[str, Any]:
    user_content = f"Transcript:\n\n{transcript_text}{duration_note}"
    if prior_result is not None:
        user_content += f"\n\nDraft analysis to verify and refine:\n{json.dumps(prior_result, separators=(',', ':'))}"

    retry_plan = _retry_plan(model)
    last_error: AnalysisError | None = None

    for attempt_index, attempt in enumerate(retry_plan, start=1):
        if job_id and attempt_index > 1:
            log_job(
                job_id,
                "warning",
                "analysis_pass_retry",
                f"Retrying {pass_name} pass (attempt {attempt_index})",
                details={"pass": pass_name, "model": model, **attempt},
            )

        if job_id:
            log_job(
                job_id,
                "info",
                "analysis_pass_started",
                f"{pass_name} pass with {model}",
                details={
                    "pass": pass_name,
                    "model": model,
                    "transcript_chars": len(transcript_text),
                    "attempt": attempt_index,
                    **attempt,
                },
            )

        prompt = system_prompt
        if attempt.get("max_per_group") and pass_name == "draft":
            prompt = ANALYSIS_SYSTEM_PROMPT.format(max_per_group=attempt["max_per_group"])

        try:
            response = client.chat.completions.create(
                **_completion_params(model, **attempt),
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_content},
                ],
            )
        except Exception as exc:
            if job_id:
                log_job(
                    job_id,
                    "error",
                    "analysis_api_error",
                    str(exc),
                    details={
                        "pass": pass_name,
                        "model": model,
                        "attempt": attempt_index,
                        "error_type": type(exc).__name__,
                    },
                )
            raise AnalysisError(
                f"OpenAI API error during {pass_name} pass: {exc}",
                details={"pass": pass_name, "model": model},
            ) from exc

        choice = response.choices[0]
        content = _message_content(choice.message)
        finish_reason = getattr(choice, "finish_reason", None)
        usage = _usage_dict(response)

        if job_id:
            log_job(
                job_id,
                "info",
                "analysis_pass_response",
                f"{pass_name} pass returned {len(content)} chars",
                details={
                    "pass": pass_name,
                    "model": model,
                    "attempt": attempt_index,
                    "finish_reason": finish_reason,
                    "content_length": len(content),
                    "usage": usage,
                    "content_preview": content[:400],
                },
            )

        truncated = _looks_truncated(content, finish_reason)
        try:
            parsed = _parse_json(content)
        except AnalysisError as exc:
            last_error = exc
            if truncated or attempt_index < len(retry_plan):
                if job_id:
                    log_job(
                        job_id,
                        "warning",
                        "analysis_json_parse_failed",
                        str(exc),
                        details={
                            "pass": pass_name,
                            "model": model,
                            "attempt": attempt_index,
                            "finish_reason": finish_reason,
                            "truncated": truncated,
                            "usage": usage,
                            "raw_content": content[:4000],
                            **exc.details,
                        },
                    )
                continue

            if job_id:
                log_job(
                    job_id,
                    "error",
                    "analysis_json_parse_failed",
                    str(exc),
                    details={
                        "pass": pass_name,
                        "model": model,
                        "finish_reason": finish_reason,
                        "usage": usage,
                        "raw_content": content[:4000],
                        **exc.details,
                    },
                )
            raise

        if truncated and attempt_index < len(retry_plan):
            last_error = AnalysisError(
                "Model returned truncated JSON.",
                details={"finish_reason": finish_reason, "content_length": len(content)},
            )
            if job_id:
                log_job(
                    job_id,
                    "warning",
                    "analysis_response_truncated",
                    "Parsed JSON but response looked truncated — retrying with safer settings",
                    details={"pass": pass_name, "finish_reason": finish_reason},
                )
            continue

        parsed["moments"] = _normalize_moments(parsed.get("moments", []))
        return parsed

    if last_error:
        raise last_error
    raise AnalysisError(f"{pass_name} pass failed after retries.")


def _retry_plan(model: str) -> list[dict[str, Any]]:
    if not model.startswith("gpt-5"):
        return [{"reasoning_effort": None, "max_per_group": None}]

    return [
        {"reasoning_effort": settings.openai_reasoning_effort, "max_per_group": None},
        {"reasoning_effort": "low", "max_per_group": None},
        {"reasoning_effort": "none", "max_per_group": max(1, settings.max_moments_per_group - 1)},
    ]


def _looks_truncated(content: str, finish_reason: str | None) -> bool:
    if finish_reason in INCOMPLETE_FINISH_REASONS:
        return True
    text = content.strip()
    if not text:
        return True
    if not text.endswith("}"):
        return True
    try:
        json.loads(_extract_json_text(text))
        return False
    except json.JSONDecodeError:
        return True


def _message_content(message: Any) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text") or block.get("content")
                if text:
                    parts.append(str(text))
            else:
                text = getattr(block, "text", None)
                if text:
                    parts.append(str(text))
        return "\n".join(parts).strip()

    parsed = getattr(message, "parsed", None)
    if parsed is not None:
        if isinstance(parsed, dict):
            return json.dumps(parsed)
        return str(parsed)

    refusal = getattr(message, "refusal", None)
    if refusal:
        raise AnalysisError(
            "Model refused the analysis request.",
            details={"refusal": str(refusal)},
        )

    return ""


def _usage_dict(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    if not usage:
        return {}

    details: dict[str, Any] = {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }

    for key in ("completion_tokens_details", "prompt_tokens_details"):
        value = getattr(usage, key, None)
        if value is None:
            continue
        if hasattr(value, "model_dump"):
            details[key] = value.model_dump()
        elif isinstance(value, dict):
            details[key] = value
        else:
            reasoning = getattr(value, "reasoning_tokens", None)
            if reasoning is not None:
                details["reasoning_tokens"] = reasoning

    return details


def _completion_params(model: str, *, reasoning_effort: str | None = None, max_per_group: int | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {
        "model": model,
        "max_completion_tokens": settings.openai_max_completion_tokens,
    }
    if model.startswith("gpt-5"):
        effort = reasoning_effort if reasoning_effort is not None else settings.openai_reasoning_effort
        if effort and effort != "none":
            params["reasoning_effort"] = effort
    else:
        params["temperature"] = 0.2
        params.pop("max_completion_tokens", None)
        params["max_tokens"] = settings.openai_max_completion_tokens
    return params


def _extract_json_text(content: str) -> str:
    text = content.strip()
    if not text:
        return text

    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()

    if text.startswith("{") and text.endswith("}"):
        return text

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]

    return text


def _parse_json(content: str) -> dict[str, Any]:
    if not content.strip():
        raise AnalysisError(
            "Model returned empty content.",
            details={"content_length": 0},
        )

    candidates = [content, _extract_json_text(content)]
    seen: set[str] = set()
    errors: list[str] = []

    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
            errors.append("Top-level JSON value was not an object.")
        except json.JSONDecodeError as exc:
            errors.append(str(exc))

    salvaged = _salvage_partial_moments(content)
    if salvaged is not None:
        return salvaged

    preview = content[:500].replace("\n", "\\n")
    raise AnalysisError(
        "Model returned invalid JSON.",
        details={
            "parse_errors": errors,
            "content_preview": preview,
            "content_length": len(content),
        },
    )


def _salvage_partial_moments(content: str) -> dict[str, Any] | None:
    """Recover complete moment objects from truncated JSON responses."""
    summary_match = re.search(r'"video_summary"\s*:\s*"((?:[^"\\]|\\.)*)"', content)
    video_summary = summary_match.group(1) if summary_match else "Partial analysis recovered from truncated model output."

    moment_pattern = re.compile(
        r'\{\s*"id"\s*:\s*"[^"]+"\s*,\s*"group"\s*:\s*"[^"]+"'
        r'(?:\s*,\s*"(?:title|quote|start_seconds|end_seconds|confidence|rationale)"\s*:\s*'
        r'(?:-?\d+(?:\.\d+)?|"[^"]*"))+\s*\}',
        re.DOTALL,
    )

    moments: list[dict[str, Any]] = []
    for match in moment_pattern.finditer(content):
        try:
            item = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and "start_seconds" in item and "end_seconds" in item:
            moments.append(item)

    if not moments:
        return None

    return {"video_summary": video_summary, "moments": moments}


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
                "quote": str(item.get("quote") or "").strip()[:140],
                "start_seconds": round(start, 2),
                "end_seconds": round(end, 2),
                "confidence": float(item.get("confidence", 0.8)),
                "rationale": str(item.get("rationale") or "").strip()[:100],
            }
        )

    normalized.sort(key=lambda moment: moment["start_seconds"])
    return normalized
