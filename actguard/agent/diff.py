"""Generate unified diffs for compliance tasks."""

from __future__ import annotations

import re
from pathlib import Path

from actguard.llm import complete
from parsing.implementation_parser import ImplementationTask

FIX_DISCLAIMER = (
    "Automated compliance fix — review before merging. Not legal advice."
)


def _extract_diff(text: str) -> str:
    text = text.strip()
    fence = re.search(r"```(?:diff)?\s*\n(.*?)```", text, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    if text.startswith("---") or text.startswith("diff --git"):
        return text
    return text


def _read_file_snippet(path: Path, max_chars: int = 12000) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(content) > max_chars:
        return content[:max_chars] + "\n... [truncated]"
    return content


def build_fix_prompt(
    repo_path: Path,
    task: ImplementationTask,
    file_paths: list[Path],
) -> list[dict]:
    files_block = []
    for path in file_paths:
        rel = path.relative_to(repo_path)
        snippet = _read_file_snippet(path)
        files_block.append(f"### {rel}\n```\n{snippet}\n```")

    steps = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(task.steps))
    acceptance = "\n".join(f"- {c}" for c in task.acceptance_criteria)

    user_content = f"""{FIX_DISCLAIMER}

Implement ONE compliance task as a unified diff (standard unified diff format).

PROJECT ROOT: {repo_path}

TASK: {task.priority} — {task.title}
Regulation: {task.regulation}
Type: {task.type}
Why: {task.why}

Implementation steps:
{steps or "(see task title)"}

Acceptance criteria:
{acceptance or "(see steps)"}

FILES:
{chr(10).join(files_block) if files_block else "(no files — create new files if needed under project root)"}

RULES:
- Output ONLY a valid unified diff (no prose before or after).
- Use standard headers: --- a/path and +++ b/path (paths relative to project root).
- For new files use --- /dev/null and +++ b/path.
- Minimal change; match existing code style.
- Do not modify unrelated files.
"""

    return [
        {
            "role": "system",
            "content": (
                "You are a senior engineer applying EU compliance fixes. "
                "Respond with a single unified diff only."
            ),
        },
        {"role": "user", "content": user_content},
    ]


def generate_task_diff(
    repo_path: Path,
    task: ImplementationTask,
    file_paths: list[Path],
) -> str:
    messages = build_fix_prompt(repo_path, task, file_paths)
    raw = complete(messages, label="Fix agent", timeout_ms=300000)
    return _extract_diff(raw)
