#!/usr/bin/env python3
"""Sync Linear project + issues and optionally update Notion spec page.

Requires:
  LINEAR_API_KEY  — https://linear.app/settings/api
  NOTION_TOKEN    — optional, for Notion page creation/update
  NOTION_PARENT_PAGE_ID — optional parent for new Notion page
  NOTION_PAGE_ID  — optional existing spec page to append updates
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LINEAR_API = "https://api.linear.app/graphql"
NOTION_API = "https://api.notion.com/v1"

TEAM_NAME = "Yang Space"
PROJECT_NAME = "Motivation Video Assembler"
PROJECT_ICON = "Clapperboard"
GITHUB_REPO = "https://github.com/HaoChiBao/motivation-video-assembler"


def linear_request(query: str, variables: dict | None = None) -> dict:
    key = os.environ.get("LINEAR_API_KEY", "").strip()
    if not key:
        raise SystemExit("LINEAR_API_KEY is not set. Add it to .env or your shell.")

    payload = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        LINEAR_API,
        data=payload,
        headers={"Authorization": key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
    if data.get("errors"):
        raise RuntimeError(json.dumps(data["errors"], indent=2))
    return data["data"]


def notion_request(method: str, path: str, body: dict | None = None) -> dict:
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        raise SystemExit("NOTION_TOKEN is not set.")

    url = f"{NOTION_API}/{path.lstrip('/')}"
    payload = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def get_team_and_viewer() -> tuple[str, str]:
    data = linear_request(
        """
        query {
          viewer { id name email }
          teams { nodes { id name } }
        }
        """
    )
    viewer_id = data["viewer"]["id"]
    team = next((t for t in data["teams"]["nodes"] if t["name"] == TEAM_NAME), None)
    if not team:
        names = [t["name"] for t in data["teams"]["nodes"]]
        raise SystemExit(f"Team '{TEAM_NAME}' not found. Available: {names}")
    return team["id"], viewer_id


def get_status_map(team_id: str) -> dict[str, str]:
    data = linear_request(
        """
        query($teamId: String!) {
          team(id: $teamId) {
            states { nodes { id name type } }
          }
        }
        """,
        {"teamId": team_id},
    )
    return {state["name"].lower(): state["id"] for state in data["team"]["states"]["nodes"]}


def find_project(name: str) -> dict | None:
    data = linear_request(
        """
        query($filter: ProjectFilter) {
          projects(filter: $filter, first: 5) {
            nodes { id name url slugId }
          }
        }
        """,
        {"filter": {"name": {"eq": name}}},
    )
    nodes = data.get("projects", {}).get("nodes", [])
    return nodes[0] if nodes else None


def update_project(project_id: str) -> None:
    linear_request(
        """
        mutation($id: String!, $input: ProjectUpdateInput!) {
          projectUpdate(id: $id, input: $input) { project { id url } }
        }
        """,
        {
            "id": project_id,
            "input": {
                "summary": "YouTube speech → transcript → AI/manual clips → local database.",
                "description": (
                    "## Motivation Video Assembler\n\n"
                    "Import motivational YouTube URLs, extract timestamped transcripts, "
                    "clip manually in Studio (dual-bar timeline) or via GPT-5.5 two-pass AI, "
                    "and browse/search/download from a local clip database.\n\n"
                    f"**Repo:** {GITHUB_REPO}\n\n"
                    "**Stack:** Python · FastAPI · OpenAI GPT-5.5 · yt-dlp · ffmpeg · Wispr Flow UI\n\n"
                    "**Latest (Jul 2026):** Wispr Flow design, ClipTimeline scrubber, job logs, "
                    "optional AI on import, re-run analysis on any saved video."
                ),
            },
        },
    )


def create_project(team_id: str, lead_id: str) -> dict:
    data = linear_request(
        """
        mutation($input: ProjectCreateInput!) {
          projectCreate(input: $input) {
            project { id name url slugId }
          }
        }
        """,
        {
            "input": {
                "name": PROJECT_NAME,
                "icon": PROJECT_ICON,
                "teamIds": [team_id],
                "leadId": lead_id,
                "summary": "YouTube speech → transcript → AI/manual clips → local database.",
                "description": f"**Repo:** {GITHUB_REPO}",
            }
        },
    )
    return data["projectCreate"]["project"]


def list_project_issues(project_id: str) -> dict[str, dict]:
    data = linear_request(
        """
        query($filter: IssueFilter, $after: String) {
          issues(filter: $filter, first: 100, after: $after) {
            nodes { id identifier title url state { name } }
            pageInfo { hasNextPage endCursor }
          }
        }
        """,
        {"filter": {"project": {"id": {"eq": project_id}}}, "after": None},
    )
    by_title: dict[str, dict] = {}
    for issue in data["issues"]["nodes"]:
        by_title[issue["title"]] = issue
    return by_title


def ensure_label(team_id: str, name: str, cache: dict[str, str]) -> str:
    if name in cache:
        return cache[name]
    data = linear_request(
        """
        mutation($teamId: String!, $name: String!) {
          issueLabelCreate(input: { teamId: $teamId, name: $name }) {
            issueLabel { id name }
          }
        }
        """,
        {"teamId": team_id, "name": name},
    )
    label_id = data["issueLabelCreate"]["issueLabel"]["id"]
    cache[name] = label_id
    return label_id


def upsert_issue(
    team_id: str,
    project_id: str,
    assignee_id: str,
    status_map: dict[str, str],
    label_cache: dict[str, str],
    existing: dict[str, dict],
    ticket: dict,
) -> dict:
    state_name = ticket.get("state", "Todo").lower()
    state_id = status_map.get(state_name) or status_map.get("todo") or status_map.get("backlog")
    label_ids = [ensure_label(team_id, label, label_cache) for label in ticket.get("labels", [])]

    if ticket["title"] in existing:
        issue_id = existing[ticket["title"]]["id"]
        data = linear_request(
            """
            mutation($id: String!, $input: IssueUpdateInput!) {
              issueUpdate(id: $id, input: $input) {
                issue { id identifier title url priority priorityLabel state { name } }
              }
            }
            """,
            {
                "id": issue_id,
                "input": {
                    "description": ticket["description"],
                    "priority": ticket["priority"],
                    "stateId": state_id,
                    "labelIds": label_ids or None,
                    "projectId": project_id,
                    "assigneeId": assignee_id,
                },
            },
        )
        return data["issueUpdate"]["issue"]

    data = linear_request(
        """
        mutation($input: IssueCreateInput!) {
          issueCreate(input: $input) {
            issue { id identifier title url priority priorityLabel state { name } }
          }
        }
        """,
        {
            "input": {
                "teamId": team_id,
                "projectId": project_id,
                "assigneeId": assignee_id,
                "title": ticket["title"],
                "description": ticket["description"],
                "priority": ticket["priority"],
                "stateId": state_id,
                "labelIds": label_ids or None,
            }
        },
    )
    return data["issueCreate"]["issue"]


TICKETS = [
    {
        "title": "YouTube transcript ingestion with timestamp normalization",
        "state": "Done",
        "priority": 2,
        "labels": ["backend", "pipeline"],
        "description": "**Shipped.** Captions via youtube-transcript-api + Whisper fallback.\n\n**Files:** `backend/services/transcript.py`",
    },
    {
        "title": "Two-pass OpenAI moment analysis (find + verify)",
        "state": "Done",
        "priority": 2,
        "labels": ["ai", "backend"],
        "description": "**Shipped.** GPT-5.5 two-pass analysis with JSON retry, truncation handling, `max_completion_tokens`, optional import flag.\n\n**Files:** `backend/services/analyzer.py`",
    },
    {
        "title": "Source video download + ffmpeg clip extraction",
        "state": "Done",
        "priority": 2,
        "labels": ["backend", "video"],
        "description": "**Shipped.** yt-dlp download + ffmpeg cuts with audio.\n\n**Files:** `backend/services/clipper.py`",
    },
    {
        "title": "FastAPI backend + background job orchestration",
        "state": "Done",
        "priority": 2,
        "labels": ["backend", "api"],
        "description": "**Shipped.** Jobs, optional AI, re-run analysis, manual clips, structured job logs.\n\n**Files:** `backend/app.py`, `backend/services/pipeline.py`, `backend/services/job_logs.py`",
    },
    {
        "title": "Motivation clip database — index, tags, local save",
        "state": "Done",
        "priority": 2,
        "labels": ["backend", "database"],
        "description": "**Shipped.** Searchable index, tags, PATCH metadata, download, local save folder.\n\n**Files:** `backend/services/database.py`",
    },
    {
        "title": "Studio — manual transcript-synced clipper",
        "state": "Done",
        "priority": 2,
        "labels": ["frontend", "backend", "ux"],
        "description": "**Shipped.** Source video + transcript timeline, shift+click range, save with labels/tags.\n\n**Files:** `frontend/app.js`, `POST /api/jobs/{id}/clips`",
    },
    {
        "title": "ClipTimeline — dual-bar video scrubber with in/out handles",
        "state": "Done",
        "priority": 2,
        "labels": ["frontend", "ux", "video"],
        "description": "**Shipped.** Main playhead bar + clip-range sub-bar, draggable handles, preview clip, works on any imported video in Studio.\n\n**Files:** `frontend/clip-timeline.js`, `frontend/styles.css`",
    },
    {
        "title": "Database UI — search, filter, download, edit labels",
        "state": "Done",
        "priority": 2,
        "labels": ["frontend", "ux"],
        "description": "**Shipped.** Master-detail database view, search, tag filters, download MP4, edit title/tags.\n\n**Files:** `frontend/app.js`",
    },
    {
        "title": "Wispr Flow design system + product UI overhaul",
        "state": "Done",
        "priority": 3,
        "labels": ["frontend", "design"],
        "description": "**Shipped.** Cream/lavender/teal Wispr Flow tokens per DESIGN.md + ruthless product UX per UIUX_PROMPT.md. Analyze / Studio / Database tabs.\n\n**Files:** `DESIGN.md`, `frontend/styles.css`, `frontend/index.html`",
    },
    {
        "title": "Job logging — structured logs API + Studio/Analyze UI",
        "state": "Done",
        "priority": 3,
        "labels": ["backend", "frontend", "observability"],
        "description": "**Shipped.** Per-job JSONL logs at `data/logs/jobs/`, `GET /api/jobs/{id}/logs`, log panels in Analyze + Studio for AI/debug failures.\n\n**Files:** `backend/services/job_logs.py`",
    },
    {
        "title": "Optional AI on import + re-run analysis on saved videos",
        "state": "Done",
        "priority": 2,
        "labels": ["backend", "frontend", "ai"],
        "description": "**Shipped.** Uncheck auto-analyze to import transcript only. Studio re-runs AI on any prepared video; replaces prior AI clips, keeps manual clips.\n\n**Endpoint:** `POST /api/jobs/{id}/analyze-ai`",
    },
    {
        "title": "Configure OpenAI + run end-to-end QA on real speeches",
        "state": "In Progress",
        "priority": 1,
        "labels": ["qa", "infra"],
        "description": "**Assignee: James Yang.** GPT-5.5 configured. Test 3 real motivational videos (short/medium/long). Document failure modes (JSON truncation, content_filter, Whisper fallback).\n\n**Acceptance:** Full flow on 3 videos including manual clip + AI re-run.",
    },
    {
        "title": "Montage assembly — stitch selected clips into one export",
        "state": "Todo",
        "priority": 2,
        "labels": ["video", "backend"],
        "description": "**Assignee: James Yang.** Select clips from database, order them, ffmpeg concat export.\n\n**Acceptance:** Single MP4 download from UI.",
    },
    {
        "title": "Re-trim existing database clips from source video",
        "state": "Todo",
        "priority": 3,
        "labels": ["frontend", "backend", "video"],
        "description": "**Assignee: James Yang.** Open saved clip in Studio at source timestamps, adjust boundaries, re-extract. ClipTimeline handles new clips; this covers editing existing DB entries in-place.\n\n**Depends on:** ClipTimeline (done)",
    },
    {
        "title": "Job history + batch import queue",
        "state": "Todo",
        "priority": 4,
        "labels": ["frontend", "backend"],
        "description": "**Assignee: James Yang.** Jobs list UI, batch URL input, filter database by job.",
    },
]


def load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def build_notion_blocks() -> list[dict]:
    spec_path = ROOT / "docs" / "notion-page-content.md"
    text = spec_path.read_text()
    chunks = [chunk.strip() for chunk in text.split("\n\n") if chunk.strip()]
    blocks: list[dict] = []
    for chunk in chunks[:80]:
        if chunk.startswith("#"):
            level = min(chunk.count("#", 0, 3), 3)
            content = chunk.lstrip("#").strip()
            blocks.append(
                {
                    "object": "block",
                    "type": f"heading_{level}",
                    f"heading_{level}": {
                        "rich_text": [{"type": "text", "text": {"content": content[:2000]}}]
                    },
                }
            )
        else:
            blocks.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": chunk[:2000]}}]
                    },
                }
            )
    return blocks


def append_notion_update(page_id: str, project_url: str) -> None:
    children = [
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "Sync update — July 5, 2026"}}]
            },
        },
        {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": "Wispr Flow UI overhaul (DESIGN.md)"}}]
            },
        },
        {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": "ClipTimeline dual-bar scrubber in Studio"}}]
            },
        },
        {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": "GPT-5.5 analysis + JSON retry/truncation fixes"}}]
            },
        },
        {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": "Job logs API + UI panels"}}]
            },
        },
        {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": "Optional AI on import; re-run AI on any saved video"}}]
            },
        },
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"type": "text", "text": {"content": "Linear project: "}},
                    {"type": "text", "text": {"content": project_url, "link": {"url": project_url}}},
                    {"type": "text", "text": {"content": f" · GitHub: {GITHUB_REPO}"}},
                ]
            },
        },
    ]
    notion_request("PATCH", f"blocks/{page_id}/children", {"children": children})


def create_notion_page(parent_id: str, project_url: str) -> str:
    blocks = build_notion_blocks()
    body = {
        "parent": {"page_id": parent_id},
        "icon": {"type": "emoji", "emoji": "🎬"},
        "properties": {
            "title": [{"type": "text", "text": {"content": "Motivation Video Assembler — Project Spec"}}]
        },
        "children": blocks[:100],
    }
    page = notion_request("POST", "pages", body)
    return page.get("url", page.get("id", ""))


def main() -> None:
    load_env()
    team_id, viewer_id = get_team_and_viewer()
    status_map = get_status_map(team_id)

    print(f"Syncing Linear project in {TEAM_NAME}…")
    project = find_project(PROJECT_NAME)
    if project:
        print(f"Found existing project: {project['url']}")
        update_project(project["id"])
        print("Updated project description.")
    else:
        project = create_project(team_id, viewer_id)
        print(f"Created project: {project['url']}")

    existing = list_project_issues(project["id"])
    label_cache: dict[str, str] = {}
    synced_issues = []

    for ticket in TICKETS:
        action = "Updated" if ticket["title"] in existing else "Created"
        issue = upsert_issue(
            team_id, project["id"], viewer_id, status_map, label_cache, existing, ticket
        )
        synced_issues.append(issue)
        print(f"  {action} [{issue['identifier']}] P{issue['priority']} {issue['title']} — {issue['state']['name']}")

    notion_page_id = os.environ.get("NOTION_PAGE_ID", "").strip()
    parent = os.environ.get("NOTION_PARENT_PAGE_ID", "").strip()

    if notion_page_id:
        print("Appending update to existing Notion page…")
        try:
            append_notion_update(notion_page_id, project["url"])
            print(f"Notion page updated: {notion_page_id}")
        except urllib.error.HTTPError as exc:
            print(f"Notion update failed: {exc.read().decode()}", file=sys.stderr)
    elif parent:
        print("Creating Notion page…")
        try:
            notion_url = create_notion_page(parent, project["url"])
            print(f"Notion: {notion_url}")
        except urllib.error.HTTPError as exc:
            print(f"Notion failed: {exc.read().decode()}", file=sys.stderr)
    else:
        print("Skipping Notion (set NOTION_PAGE_ID to append, or NOTION_TOKEN + NOTION_PARENT_PAGE_ID to create).")
        print(f"Notion content source: {ROOT / 'docs' / 'notion-page-content.md'}")

    summary = {
        "project_url": project["url"],
        "github": GITHUB_REPO,
        "synced_at": "2026-07-05",
        "issues": [{"id": i["identifier"], "url": i["url"], "title": i["title"], "state": i["state"]["name"]} for i in synced_issues],
    }
    out = ROOT / "docs" / "tracking-links.json"
    out.write_text(json.dumps(summary, indent=2))
    print(f"Saved links: {out}")


if __name__ == "__main__":
    main()
