"""Track completed fix tasks per project."""

from __future__ import annotations

import json
from pathlib import Path

from actguard.config import SESSION_DIRNAME


def fix_progress_path(repo_path: Path | str) -> Path:
    return Path(repo_path).resolve() / SESSION_DIRNAME / "fix_progress.json"


def load_completed(repo_path: Path | str) -> set[str]:
    path = fix_progress_path(repo_path)
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data.get("completed") or [])
    except (json.JSONDecodeError, OSError):
        return set()


def mark_completed(repo_path: Path | str, task_key: str) -> None:
    path = fix_progress_path(repo_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    completed = load_completed(repo_path)
    completed.add(task_key)
    path.write_text(
        json.dumps({"completed": sorted(completed)}, indent=2),
        encoding="utf-8",
    )
