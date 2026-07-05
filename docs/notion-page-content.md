<callout icon="🎬" color="green_bg">
**Motivation Video Assembler** — paste a motivational YouTube URL, find the best moments with a two-pass OpenAI analysis, cut preview clips with ffmpeg, and browse them in a clean product UI.
</callout>

<callout icon="📌" color="blue_bg">
**Status — July 5, 2026:** Phase 1.5 shipped. **Wispr Flow** UI, **ClipTimeline** dual-bar scrubber, **GPT-5.5** analysis with retry/logging, optional AI on import, re-run AI on any saved video. Next: montage export + full E2E QA on 3 speeches.
</callout>

<table_of_contents/>

---

## Quick links

<columns>
	<column>
		<callout icon="🐙" color="gray_bg">
			**GitHub**
			https://github.com/HaoChiBao/motivation-video-assembler
			Python · FastAPI · GPT-5.5 · ffmpeg
		</callout>
	</column>
	<column>
		<callout icon="📐" color="gray_bg">
			**Linear**
			Project: Motivation Video Assembler
			All tickets assigned to James Yang
		</callout>
	</column>
</columns>

---

## Overview

Motivation Video Assembler is a local-first pipeline for turning long motivational speeches on YouTube into a **library of short, high-impact clips** grouped by semantic category.

**Primary user flow**
1. Paste a YouTube URL on **Analyze** (optional AI auto-clip)
2. Pipeline downloads video + extracts timestamped transcript (captions or Whisper)
3. **Studio** — manually clip from transcript timeline with labels/tags
4. **Database** — search, filter, preview, download MP4s saved locally

**Why this exists**
- Manual scrubbing through 20–60 minute speeches is slow
- Social clips need **self-contained moments** with clean in/out points
- A two-pass LLM workflow reduces timestamp drift and bad quotes

---

## Goals

### Phase 1 — MVP (shipped)
- Pull timestamped YouTube captions (+ Whisper fallback)
- Two-pass OpenAI analysis for 6 moment categories
- Download source video + ffmpeg clip extraction
- FastAPI backend with job polling
- Product UI: Analyze + Studio + Database

### Phase 1.5 — Clip database + Studio (shipped)
- Indexed clip store (`data/database/index.json`)
- Manual clipping in Studio with **ClipTimeline** (playhead bar + clip-range sub-bar)
- Transcript-synced in/out, shift+click range selection
- Tags, categories, search, metadata editing
- Local save to `data/database/clips/` + browser download
- AI auto-clip optional on import; re-run AI on any prepared video
- Structured job logs (`data/logs/jobs/`) + UI log panels

### Phase 2 — Observability + AI hardening (shipped)
- GPT-5.5 default model with `max_completion_tokens` + retry on truncated JSON
- Per-job JSONL logs, `GET /api/jobs/{id}/logs`
- AI failures keep video in `prepared` state (manual clip still works)

### Phase 3 — Assembly
- Select clips from library → stitch into one export MP4
- Optional title card / simple transitions
- Batch job queue + history UI

---

## Architecture

```mermaid
flowchart LR
  UI["Frontend<br/>HTML/CSS/JS"] --> API["FastAPI<br/>backend/app.py"]
  API --> Pipeline["Job orchestrator<br/>pipeline.py"]
  Pipeline --> Transcript["Transcript service<br/>youtube-transcript-api"]
  Pipeline --> Download["Video download<br/>yt-dlp"]
  Pipeline --> Analyzer["Two-pass OpenAI<br/>analyzer.py"]
  Pipeline --> Clipper["Clip extraction<br/>ffmpeg"]
  Clipper --> Storage["data/clips/"]
  Storage --> UI
```

---

## Pipeline stages

<table header-row="true" fit-page-width="true">
	<tr>
		<td>Stage</td>
		<td>Service</td>
		<td>Output</td>
	</tr>
	<tr>
		<td>1. Parse URL</td>
		<td>transcript.py</td>
		<td>YouTube video ID</td>
	</tr>
	<tr>
		<td>2. Fetch transcript</td>
		<td>youtube-transcript-api</td>
		<td>Timestamped segments</td>
	</tr>
	<tr>
		<td>3. Download video</td>
		<td>yt-dlp</td>
		<td>data/videos/{job_id}/source.mp4</td>
	</tr>
	<tr>
		<td>4. Analyze (pass 1)</td>
		<td>OpenAI</td>
		<td>Draft moments by category</td>
	</tr>
	<tr>
		<td>5. Verify (pass 2)</td>
		<td>OpenAI</td>
		<td>Refined moments + review notes</td>
	</tr>
	<tr>
		<td>6. Extract clips</td>
		<td>ffmpeg</td>
		<td>data/clips/{job_id}/*.mp4</td>
	</tr>
	<tr>
		<td>7. Library</td>
		<td>Frontend</td>
		<td>Filter + preview UI</td>
	</tr>
</table>

---

## Moment categories

<table header-row="true" fit-page-width="true">
	<tr>
		<td>Group ID</td>
		<td>Label</td>
		<td>What to look for</td>
	</tr>
	<tr>
		<td>hook</td>
		<td>Hook</td>
		<td>Opening lines that grab attention immediately</td>
	</tr>
	<tr>
		<td>emotional_peak</td>
		<td>Emotional Peak</td>
		<td>Most emotionally charged delivery</td>
	</tr>
	<tr>
		<td>wisdom</td>
		<td>Wisdom</td>
		<td>Clear, memorable insight or lesson</td>
	</tr>
	<tr>
		<td>story_climax</td>
		<td>Story Climax</td>
		<td>Peak of a narrative arc or personal story</td>
	</tr>
	<tr>
		<td>call_to_action</td>
		<td>Call to Action</td>
		<td>Direct challenge or invitation to act</td>
	</tr>
	<tr>
		<td>quotable</td>
		<td>Quotable</td>
		<td>Standalone shareable line</td>
	</tr>
</table>

**Clip rules (enforced in analyzer)**
- Duration: 8–45 seconds (hard cap 60s trimmed)
- Timestamps must match transcript lines
- Quotes must reflect actual speech
- Max 3 moments per group (configurable via `MAX_MOMENTS_PER_GROUP`)

---

## Tech stack

<table header-row="true" fit-page-width="true">
	<tr>
		<td>Layer</td>
		<td>Choice</td>
		<td>Notes</td>
	</tr>
	<tr>
		<td>Backend</td>
		<td>Python 3.11+ · FastAPI · uvicorn</td>
		<td>Serves API + static frontend</td>
	</tr>
	<tr>
		<td>AI</td>
		<td>OpenAI Chat Completions (JSON mode)</td>
		<td>Two-pass: analyze + verify</td>
	</tr>
	<tr>
		<td>Transcript</td>
		<td>youtube-transcript-api</td>
		<td>Requires captions on video</td>
	</tr>
	<tr>
		<td>Video</td>
		<td>yt-dlp + ffmpeg</td>
		<td>Download once, cut many clips</td>
	</tr>
	<tr>
		<td>Frontend</td>
		<td>Vanilla HTML/CSS/JS</td>
		<td>No build step</td>
	</tr>
	<tr>
		<td>Design</td>
		<td>Wispr Flow design system</td>
		<td>See DESIGN.md — cream #ffffeb, lavender CTA, deep teal, EB Garamond + Figtree</td>
	</tr>
</table>

---

## API reference

<table header-row="true" fit-page-width="true">
	<tr>
		<td>Method</td>
		<td>Path</td>
		<td>Purpose</td>
	</tr>
	<tr>
		<td>GET</td>
		<td>/api/health</td>
		<td>Server + OpenAI config status</td>
	</tr>
	<tr>
		<td>POST</td>
		<td>/api/analyze</td>
		<td>Start job — `{ "youtube_url": "...", "auto_analyze": true }`</td>
	</tr>
	<tr>
		<td>GET</td>
		<td>/api/jobs/studio</td>
		<td>Prepared videos for Studio</td>
	</tr>
	<tr>
		<td>POST</td>
		<td>/api/jobs/{id}/analyze-ai</td>
		<td>Re-run AI analysis — `{ "replace_existing": true }`</td>
	</tr>
	<tr>
		<td>POST</td>
		<td>/api/jobs/{id}/clips</td>
		<td>Manual clip from Studio</td>
	</tr>
	<tr>
		<td>GET</td>
		<td>/api/jobs/{id}/logs</td>
		<td>Structured job logs (JSONL-backed)</td>
	</tr>
	<tr>
		<td>GET</td>
		<td>/api/library</td>
		<td>Search/filter clip database</td>
	</tr>
	<tr>
		<td>GET</td>
		<td>/api/clips/{job_id}/{filename}</td>
		<td>Stream clip MP4</td>
	</tr>
</table>

---

## Frontend IA

<details>
<summary>Analyze tab</summary>
	- URL input + Analyze button
	- Inline status (info / success / error)
	- Pipeline card (hidden until job starts): stepper + progress %
	- "Open library" CTA on completion
</details>

<details>
<summary>Studio tab</summary>
	- Source video picker (any imported/prepared video)
	- **ClipTimeline:** main playhead bar + clip-range sub-bar with draggable in/out handles
	- Transcript panel with shift+click range; syncs to timeline
	- Save clip form (title, category, tags, local save)
	- Re-run AI analysis; job log panel
</details>

<details>
<summary>Database tab</summary>
	- Left sidebar: search, category/tag filters, clip list
	- Right detail pane: video player + quote + metadata + download
	- Edit title/tags; save to local folder
</details>

**UX principles (UIUX_PROMPT.md + DESIGN.md)**
- Product tool, not marketing landing page
- Wispr Flow: cream canvas, lavender for primary CTA only, teal for progress/badges
- EB Garamond display headlines; Figtree UI
- One player in database view; tight spacing, scannable metadata

---

## Data model

**Job** (`data/jobs/{id}.json`)
- id, youtube_url, video_id, status, stage, progress, auto_analyze
- video_title, language, transcript, analysis, analysis_error, clips[]

**Logs** (`data/logs/jobs/{id}.jsonl`)
- Structured events: pipeline stages, AI passes, JSON errors with raw preview

**Clip moment**
- id, group, title, quote, start_seconds, end_seconds
- confidence, rationale, clip_filename, clip_url

**On disk**
- `data/videos/{job_id}/source.mp4`
- `data/clips/{job_id}/{moment_id}.mp4`

---

## Environment setup

```bash
cd motivation-video-assembler
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env
# Add OPENAI_API_KEY
brew install ffmpeg   # if needed
python -m uvicorn backend.app:app --reload --port 8000
```

**.env variables**
<table header-row="true">
	<tr>
		<td>Variable</td>
		<td>Required</td>
		<td>Description</td>
	</tr>
	<tr>
		<td>OPENAI_API_KEY</td>
		<td>Yes</td>
		<td>OpenAI API key</td>
	</tr>
	<tr>
		<td>OPENAI_MODEL</td>
		<td>No</td>
		<td>Default gpt-5.5</td>
	</tr>
	<tr>
		<td>OPENAI_VERIFY_MODEL</td>
		<td>No</td>
		<td>Second-pass model</td>
	</tr>
	<tr>
		<td>OPENAI_REASONING_EFFORT</td>
		<td>No</td>
		<td>GPT-5.x: none, low, medium, high</td>
	</tr>
	<tr>
		<td>OPENAI_MAX_COMPLETION_TOKENS</td>
		<td>No</td>
		<td>Output budget (default 16384)</td>
	</tr>
	<tr>
		<td>LINEAR_API_KEY</td>
		<td>No</td>
		<td>For scripts/setup_tracking.py</td>
	</tr>
	<tr>
		<td>NOTION_TOKEN</td>
		<td>No</td>
		<td>Notion sync (optional)</td>
	</tr>
	<tr>
		<td>MAX_MOMENTS_PER_GROUP</td>
		<td>No</td>
		<td>Cap per category (default 3)</td>
	</tr>
</table>

---

## Linear ticket map

<table header-row="true" fit-page-width="true">
	<tr>
		<td>Ticket theme</td>
		<td>Priority</td>
		<td>State</td>
		<td>Owner</td>
	</tr>
	<tr>
		<td>Transcript ingestion</td>
		<td>High</td>
		<td>Done</td>
		<td>James Yang</td>
	</tr>
	<tr>
		<td>Two-pass OpenAI analysis</td>
		<td>High</td>
		<td>Done</td>
		<td>James Yang</td>
	</tr>
	<tr>
		<td>ffmpeg clip extraction</td>
		<td>High</td>
		<td>Done</td>
		<td>James Yang</td>
	</tr>
	<tr>
		<td>FastAPI + job orchestration</td>
		<td>High</td>
		<td>Done</td>
		<td>James Yang</td>
	</tr>
	<tr>
		<td>Analyze UI + pipeline stepper</td>
		<td>High</td>
		<td>Done</td>
		<td>James Yang</td>
	</tr>
	<tr>
		<td>Library master-detail UI</td>
		<td>High</td>
		<td>Done</td>
		<td>James Yang</td>
	</tr>
	<tr>
		<td>Goated / Wispr Flow UI overhaul</td>
		<td>Medium</td>
		<td>Done</td>
		<td>James Yang</td>
	</tr>
	<tr>
		<td>ClipTimeline dual-bar scrubber</td>
		<td>High</td>
		<td>Done</td>
		<td>James Yang</td>
	</tr>
	<tr>
		<td>Job logging + logs UI</td>
		<td>Medium</td>
		<td>Done</td>
		<td>James Yang</td>
	</tr>
	<tr>
		<td>Optional AI + re-run analysis</td>
		<td>High</td>
		<td>Done</td>
		<td>James Yang</td>
	</tr>
	<tr>
		<td>GPT-5.5 + JSON retry</td>
		<td>High</td>
		<td>Done</td>
		<td>James Yang</td>
	</tr>
	<tr>
		<td>OpenAI + dev env setup</td>
		<td>High</td>
		<td>In Progress</td>
		<td>James Yang</td>
	</tr>
	<tr>
		<td>End-to-end QA (3 real speeches)</td>
		<td>Urgent</td>
		<td>Todo</td>
		<td>James Yang</td>
	</tr>
	<tr>
		<td>Re-trim existing database clips</td>
		<td>Medium</td>
		<td>Todo</td>
		<td>James Yang</td>
	</tr>
	<tr>
		<td>Montage assembly export</td>
		<td>High</td>
		<td>Todo</td>
		<td>James Yang</td>
	</tr>
	<tr>
		<td>Job history + batch queue</td>
		<td>Low</td>
		<td>Todo</td>
		<td>James Yang</td>
	</tr>
</table>

---

## Acceptance criteria (Phase 2)

- [ ] Analyze completes on 3 real motivational videos without manual fixes
- [ ] Library filters work across all 6 categories
- [ ] Clips play in detail pane with correct in/out points
- [ ] Failed jobs show actionable errors (missing captions, ffmpeg missing, etc.)
- [ ] Notion spec + Linear tickets stay in sync with shipped code

---

## Risks & mitigations

<table header-row="true" fit-page-width="true">
	<tr>
		<td>Risk</td>
		<td>Impact</td>
		<td>Mitigation</td>
	</tr>
	<tr>
		<td>No YouTube captions</td>
		<td>Pipeline fails at transcript</td>
		<td>Whisper fallback via OpenAI (shipped)</td>
	</tr>
	<tr>
		<td>GPT-5.5 JSON truncation</td>
		<td>AI analysis fails mid-response</td>
		<td>max_completion_tokens + retry + job logs (shipped)</td>
	</tr>
	<tr>
		<td>LLM timestamp drift</td>
		<td>Bad clips</td>
		<td>Two-pass verify + boundary normalization</td>
	</tr>
	<tr>
		<td>yt-dlp blocked</td>
		<td>No source video</td>
		<td>Retry + cookie config docs</td>
	</tr>
	<tr>
		<td>Long videos / cost</td>
		<td>Slow + expensive</td>
		<td>Transcript chunking (future)</td>
	</tr>
</table>

---

## Repo layout

```
backend/
  app.py
  config.py
  services/
    transcript.py
    analyzer.py
    clipper.py
    pipeline.py
frontend/
  index.html
  styles.css
  app.js
  clip-timeline.js
data/          # runtime — jobs, clips, videos, logs, database
DESIGN.md
UIUX_PROMPT.md
scripts/setup_tracking.py
```
