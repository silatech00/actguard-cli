"""Parse implementation guide markdown into structured data."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from parsing.preprocess import clean_inline_markdown, strip_emojis

TASK_HEADER_RE = re.compile(r"^###\s+(P\d+)\s*[—–-]\s*(.+)$", re.I)
FIELD_RE = re.compile(r"^-\s+\*\*(.+?)\*\*\s*:?\s*(.*)$")
AGENT_PROMPT_HEADER_RE = re.compile(r"^##\s+Agent prompt", re.I)
LEGAL_NOTES_HEADER_RE = re.compile(r"^##\s+Notes for legal review", re.I)
PROJECT_CONTEXT_HEADER_RE = re.compile(r"^##\s+Project context", re.I)
BACKLOG_HEADER_RE = re.compile(r"^##\s+Prioritized backlog", re.I)


@dataclass
class ImplementationTask:
    id: str
    priority: str
    title: str
    regulation: str = ""
    type: str = ""
    why: str = ""
    files: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    effort: str = ""


@dataclass
class StructuredImplementationGuide:
    project_name: str
    generated_at: str
    language: str
    project_context: str = ""
    tasks: list[ImplementationTask] = field(default_factory=list)
    agent_prompt: str = ""
    legal_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["schemaVersion"] = "eucompliance.implementation.v1"
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


def _extract_fenced_block(text: str) -> str:
    """Return content of first markdown fenced code block, or stripped text."""
    m = re.search(r"```(?:\w+)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text.strip()


def _parse_list_under_field(lines: list[str], start_idx: int) -> tuple[list[str], int]:
    """Parse numbered or bulleted list items following a field line."""
    items: list[str] = []
    i = start_idx
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("### ") or (stripped.startswith("## ") and not stripped.startswith("###")):
            break
        if FIELD_RE.match(stripped) and items:
            break
        m_num = re.match(r"^\d+\.\s+(.*)", stripped)
        m_bullet = re.match(r"^-\s+(.*)", stripped)
        if m_num:
            items.append(clean_inline_markdown(m_num.group(1).strip()))
        elif m_bullet and not FIELD_RE.match(stripped):
            items.append(clean_inline_markdown(m_bullet.group(1).strip()))
        elif not stripped and items:
            pass
        elif stripped and not items and not FIELD_RE.match(stripped):
            items.append(clean_inline_markdown(stripped))
        elif FIELD_RE.match(stripped) and not items:
            break
        i += 1
    return items, i


def _parse_files_value(value: str) -> list[str]:
    if not value or value.lower() in ("n/a", "n/a — organizational", "none"):
        return []
    parts = re.split(r"[,;]\s*|\s+and\s+", value)
    return [p.strip().strip("`") for p in parts if p.strip()]


def _parse_task_body(priority: str, title: str, body_lines: list[str], task_index: int) -> ImplementationTask:
    regulation = ""
    task_type = ""
    why = ""
    files: list[str] = []
    steps: list[str] = []
    acceptance: list[str] = []
    effort = ""
    current_list: str | None = None

    i = 0
    while i < len(body_lines):
        line = body_lines[i]
        stripped = line.strip()
        m = FIELD_RE.match(stripped)
        if m:
            field_name = m.group(1).lower().rstrip(":")
            val = m.group(2).strip()
            current_list = None
            if field_name == "regulation":
                regulation = clean_inline_markdown(val)
            elif field_name == "type":
                task_type = clean_inline_markdown(val)
            elif field_name == "why":
                why = clean_inline_markdown(val)
            elif field_name in ("files / areas", "files", "areas"):
                files = _parse_files_value(val)
            elif field_name == "effort":
                effort = clean_inline_markdown(val)
            elif field_name == "implementation steps":
                current_list = "steps"
                if val:
                    steps.append(clean_inline_markdown(val))
            elif field_name == "acceptance criteria":
                current_list = "acceptance"
                if val:
                    acceptance.append(clean_inline_markdown(val))
            i += 1
            continue

        if current_list == "steps":
            m_num = re.match(r"^\d+\.\s+(.*)", stripped)
            if m_num:
                steps.append(clean_inline_markdown(m_num.group(1).strip()))
            elif stripped.startswith("- ") and not FIELD_RE.match(stripped):
                steps.append(clean_inline_markdown(stripped[2:].strip()))
            elif not stripped:
                pass
            else:
                current_list = None
                continue
        elif current_list == "acceptance":
            if stripped.startswith("- ") and not FIELD_RE.match(stripped):
                acceptance.append(clean_inline_markdown(stripped[2:].strip()))
            elif not stripped:
                pass
            else:
                current_list = None
                continue
        i += 1

    return ImplementationTask(
        id=f"task-{task_index:03d}",
        priority=priority.upper(),
        title=clean_inline_markdown(title),
        regulation=regulation,
        type=task_type,
        why=why,
        files=files,
        steps=steps,
        acceptance_criteria=acceptance,
        effort=effort,
    )


def parse_implementation_guide(
    markdown: str,
    *,
    project_name: str = "",
    language: str = "English",
) -> StructuredImplementationGuide:
    lines = [strip_emojis(ln) for ln in markdown.splitlines()]
    project_context = ""
    tasks: list[ImplementationTask] = []
    agent_prompt = ""
    legal_notes: list[str] = []

    section = "header"
    context_lines: list[str] = []
    task_priority = ""
    task_title = ""
    task_body: list[str] = []
    agent_lines: list[str] = []
    legal_lines: list[str] = []
    task_index = 0
    in_agent_fence = False
    fence_lines: list[str] = []

    def flush_task():
        nonlocal task_index, task_body, task_priority, task_title
        if task_priority and task_title:
            task_index += 1
            tasks.append(_parse_task_body(task_priority, task_title, task_body, task_index))
        task_priority = ""
        task_title = ""
        task_body = []

    for line in lines:
        stripped = line.strip()

        if PROJECT_CONTEXT_HEADER_RE.match(stripped):
            flush_task()
            section = "context"
            continue
        if BACKLOG_HEADER_RE.match(stripped):
            flush_task()
            section = "backlog"
            project_context = clean_inline_markdown("\n".join(context_lines).strip())
            continue
        if AGENT_PROMPT_HEADER_RE.match(stripped):
            flush_task()
            section = "agent"
            continue
        if LEGAL_NOTES_HEADER_RE.match(stripped):
            section = "legal"
            if not agent_prompt:
                agent_prompt = _extract_fenced_block("\n".join(agent_lines))
            continue
        if stripped.startswith("---") and "DISCLAIMER" in "\n".join(lines[lines.index(line):lines.index(line)+3]).upper():
            if section == "legal":
                legal_notes = [
                    clean_inline_markdown(ln.lstrip("- ").strip())
                    for ln in legal_lines
                    if ln.strip().startswith("-")
                ]
            break

        m_task = TASK_HEADER_RE.match(stripped)
        if m_task and section in ("backlog", "context", "header"):
            flush_task()
            section = "backlog"
            task_priority = m_task.group(1)
            task_title = m_task.group(2)
            continue

        if section == "context":
            if stripped and not stripped.startswith("#"):
                context_lines.append(stripped)
        elif section == "backlog":
            if task_priority:
                task_body.append(line)
        elif section == "agent":
            if stripped.startswith("```"):
                if in_agent_fence:
                    agent_prompt = "\n".join(fence_lines).strip()
                    in_agent_fence = False
                    fence_lines = []
                else:
                    in_agent_fence = True
                continue
            if in_agent_fence:
                fence_lines.append(line)
            else:
                agent_lines.append(line)
        elif section == "legal":
            if stripped.startswith("- "):
                legal_lines.append(stripped)

    flush_task()
    if not agent_prompt and agent_lines:
        agent_prompt = _extract_fenced_block("\n".join(agent_lines))
    if not legal_notes and legal_lines:
        legal_notes = [
            clean_inline_markdown(ln.lstrip("- ").strip())
            for ln in legal_lines
            if ln.strip().startswith("-")
        ]
    if not project_context and context_lines:
        project_context = clean_inline_markdown("\n".join(context_lines).strip())

    return StructuredImplementationGuide(
        project_name=project_name,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        language=language,
        project_context=project_context,
        tasks=tasks,
        agent_prompt=agent_prompt,
        legal_notes=legal_notes,
    )
