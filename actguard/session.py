"""Local scan session persistence (.actguard/session.json)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from actguard.config import session_path


def load_session(repo_path: Path | str) -> dict[str, Any] | None:
    path = session_path(repo_path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_session(repo_path: Path | str, data: dict[str, Any]) -> Path:
    path = session_path(repo_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return path


def require_session(repo_path: Path | str) -> dict[str, Any]:
    session = load_session(repo_path)
    if session is None:
        raise SystemExit(
            f"No scan session found at {session_path(repo_path)}. Run: actguard scan"
        )
    return session
