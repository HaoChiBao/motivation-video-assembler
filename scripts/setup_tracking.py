#!/usr/bin/env python3
"""Create Linear project + issues and optionally a Notion spec page.

Requires:
  LINEAR_API_KEY  — https://linear.app/settings/api
  NOTION_TOKEN    — optional, for Notion page creation
  NOTION_PARENT_PAGE_ID — optional parent page for Notion wiki
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
NOTION_API = "https://api.notion.com/v1/pages"

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

    url = f"https://api.notion.com/v1/{path.lstrip('/')}"
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
                "summary": "YouTube motivational speech → AI moment analysis → ffmpeg clips → preview library.",
                "description": (
                    "## Motivation Video Assembler\n\n"
                    "Paste a motivational YouTube URL. The pipeline transcribes the speech, "
                    "runs a two-pass OpenAI analysis to find clip-worthy moments by category, "
                    "cuts preview clips with ffmpeg, and surfaces them in a product UI.\n\n"
                    f"**Repo:** {GITHUB_REPO}\n\n"
                    "**Stack:** Python · FastAPI · OpenAI · yt-dlp · ffmpeg · HTML/CSS/JS"
                ),
            }
        },
    )
    return data["projectCreate"]["project"]


def create_issue(
    team_id: str,
    project_id: str,
    assignee_id: str,
    status_map: dict[str, str],
    ticket: dict,
) -> dict:
    state_name = ticket.get("state", "Todo").lower()
    state_id = status_map.get(state_name) or status_map.get("todo") or status_map.get("backlog")

    label_ids: list[str] = []
    for label in ticket.get("labels", []):
        label_data = linear_request(
            """
            mutation($teamId: String!, $name: String!) {
              issueLabelCreate(input: { teamId: $teamId, name: $name }) {
                issueLabel { id name }
              }
            }
            """,
            {"teamId": team_id, "name": label},
        )
        label_ids.append(label_data["issueLabelCreate"]["issueLabel"]["id"])

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
        "description": "**Shipped.** Captions via youtube-transcript-api + Whisper fallback when captions missing.\n\n**Files:** `backend/services/transcript.py`",
    },
    {
        "title": "Two-pass OpenAI moment analysis (find + verify)",
        "state": "Done",
        "priority": 2,
        "labels": ["ai", "backend"],
        "description": "**Shipped.** Optional auto-clip pass; 6 moment categories with verify pass.\n\n**Files:** `backend/services/analyzer.py`",
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
        "description": "**Shipped.** Jobs, transcript storage, manual + AI clip endpoints.\n\n**Files:** `backend/app.py`, `backend/services/pipeline.py`",
    },
    {
        "title": "Motivation clip database — index, tags, local save",
        "state": "Done",
        "priority": 2,
        "labels": ["backend", "database"],
        "description": "**Shipped.** Searchable index at `data/database/index.json`, saved MP4s in `data/database/clips/`, PATCH metadata, download endpoint.\n\n**Files:** `backend/services/database.py`",
    },
    {
        "title": "Studio — manual transcript-synced clipper",
        "state": "Done",
        "priority": 2,
        "labels": ["frontend", "backend", "ux"],
        "description": "**Shipped.** Source video + transcript timeline, set in/out from playhead or shift+click range, save with title/category/tags.\n\n**Files:** `frontend/*`, `POST /api/jobs/{id}/clips`",
    },
    {
        "title": "Database UI — search, filter, download, edit labels",
        "state": "Done",
        "priority": 2,
        "labels": ["frontend", "ux"],
        "description": "**Shipped.** Master-detail database view, search, tag filters, download MP4, edit title/tags.\n\n**Files:** `frontend/app.js`",
    },
    {
        "title": "Goated design system + product UI overhaul",
        "state": "Done",
        "priority": 3,
        "labels": ["frontend", "design"],
        "description": "**Shipped.** Analyze / Studio / Database tabs, Goated tokens per DESIGN.md + UIUX_PROMPT.md.",
    },
    {
        "title": "Configure OpenAI + run end-to-end QA on real speeches",
        "state": "Todo",
        "priority": 1,
        "labels": ["qa", "infra"],
        "description": "**Assignee: James Yang.** Add OPENAI_API_KEY, test 3 real motivational videos (short/medium/long). Document failure modes.\n\n**Acceptance:** Full flow works including Whisper fallback on no-caption video.",
    },
    {
        "title": "Montage assembly — stitch selected clips into one export",
        "state": "Todo",
        "priority": 2,
        "labels": ["video", "backend"],
        "description": "**Assignee: James Yang.** Select clips from database, order them, ffmpeg concat export.\n\n**Acceptance:** Single MP4 download from UI.",
    },
    {
        "title": "Re-trim existing clips without re-clipping from scratch",
        "state": "Todo",
        "priority": 3,
        "labels": ["frontend", "backend", "video"],
        "description": "**Assignee: James Yang.** Edit boundaries on saved database clips and re-extract.\n\n**Note:** Studio handles new manual clips; this covers editing existing entries.",
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


def create_notion_page(parent_id: str, linear_url: str) -> str:
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
    return page.get("url", "")


def main() -> None:
    load_env()
    team_id, viewer_id = get_team_and_viewer()
    status_map = get_status_map(team_id)

    print(f"Syncing Linear project in {TEAM_NAME}…")
    project = find_project(PROJECT_NAME)
    if project:
        print(f"Found existing project: {project['url']}")
    else:
        project = create_project(team_id, viewer_id)
        print(f"Created project: {project['url']}")

    created_issues = []
    for ticket in TICKETS:
        issue = create_issue(team_id, project["id"], viewer_id, status_map, ticket)
        created_issues.append(issue)
        print(f"  [{issue['identifier']}] P{issue['priority']} {issue['title']} — {issue['state']['name']}")

    parent = os.environ.get("NOTION_PARENT_PAGE_ID", "").strip()
    if parent:
        print("Creating Notion page…")
        try:
            notion_url = create_notion_page(parent, project["url"])
            print(f"Notion: {notion_url}")
        except urllib.error.HTTPError as exc:
            print(f"Notion failed: {exc.read().decode()}", file=sys.stderr)
    else:
        print("Skipping Notion (set NOTION_TOKEN + NOTION_PARENT_PAGE_ID to create page).")
        print(f"Notion content ready at: {ROOT / 'docs' / 'notion-page-content.md'}")

    summary = {
        "project_url": project["url"],
        "issues": [{"id": i["identifier"], "url": i["url"], "title": i["title"]} for i in created_issues],
    }
    out = ROOT / "docs" / "tracking-links.json"
    out.write_text(json.dumps(summary, indent=2))
    print(f"Saved links: {out}")


if __name__ == "__main__":
    main()
