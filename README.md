# Motivation Video Assembler

A simple pipeline that analyzes motivational YouTube speeches, finds great moments by semantic category using a two-pass OpenAI workflow, cuts preview clips with ffmpeg, and lets you browse them in a warm editorial web UI.

## What it does

1. **Transcript** — pulls timestamped captions from YouTube
2. **Think pass** — OpenAI identifies clip-worthy moments grouped by:
   - Hook
   - Emotional peak
   - Wisdom
   - Story climax
   - Call to action
   - Quotable
3. **Verify pass** — second OpenAI pass double-checks timestamps, quotes, and boundaries
4. **Clip extraction** — downloads the source video with `yt-dlp`, cuts segments with `ffmpeg`
5. **Library** — preview clips in a simple HTML/CSS/JS frontend styled with the Goated design system

## Prerequisites

- Python 3.11+
- [ffmpeg](https://ffmpeg.org/) (`brew install ffmpeg`)
- OpenAI API key

## Setup

```bash
cd motivation-video-assembler
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env
```

Edit `.env`:

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.5
# Optional second-pass model for verification
OPENAI_VERIFY_MODEL=
# Reasoning effort for GPT-5.x: none, low, medium, high, xhigh
OPENAI_REASONING_EFFORT=medium
# Output token budget (GPT-5.x counts reasoning tokens against this — keep high)
OPENAI_MAX_COMPLETION_TOKENS=16384
```

Use `OPENAI_VERIFY_MODEL` to run the QA pass on a different model (e.g. `gpt-5.5-pro` for higher accuracy).

## Run

From the project root:

```bash
source .venv/bin/activate
python -m uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Usage

### Import + auto-clip
1. Paste a YouTube URL on **Analyze**
2. Leave **Auto-find clips with AI** checked (or uncheck to prepare transcript only)
3. When done, clips appear in **Database**

### Manual clipping (Studio)
1. Open **Studio** after a video is prepared
2. Click transcript lines to seek; **Shift+click** to extend a range
3. Set start/end from playhead or type timestamps
4. Add title, category, tags → **Save clip**
5. Clips save to `data/database/clips/` when "Save to local database folder" is checked

### Transcript sources
- **YouTube captions** (preferred, fast)
- **Whisper** fallback via OpenAI when captions are missing (requires `OPENAI_API_KEY`)

### Local storage
- Index: `data/database/index.json`
- Saved clips: `data/database/clips/{clip_id}.mp4`
- Working clips: `data/clips/{job_id}/`

## Project layout

```
backend/
  app.py                 # FastAPI server + static frontend
  config.py              # env + data directories
  services/
    transcript.py        # YouTube captions
    analyzer.py            # two-pass OpenAI analysis
    clipper.py             # yt-dlp + ffmpeg
    pipeline.py            # job orchestration
frontend/
  index.html
  styles.css
  app.js
data/                    # created at runtime (jobs, clips, videos)
```

## Tracking (Linear + Notion)

Sync project tickets and Notion spec from the repo:

```bash
# Add to .env: LINEAR_API_KEY, optional NOTION_TOKEN + NOTION_PAGE_ID
python scripts/setup_tracking.py
```

Updates existing Linear issues by title (no duplicates). Full spec: `docs/notion-page-content.md`.

## Notes

- Clips are extracted from the downloaded source video, not re-encoded from scratch — fast and good enough for preview/library use.
- Jobs and clip metadata persist under `data/` so refreshes keep your library.
- Future assembly/editing can build on the same clip files and moment metadata.

## API

- `GET /api/health`
- `POST /api/analyze` `{ "youtube_url": "..." }`
- `GET /api/jobs`
- `GET /api/jobs/{job_id}`
- `GET /api/library`
- `GET /api/clips/{job_id}/{filename}`
