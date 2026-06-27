"""ActGuard CLI configuration."""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(REPO_ROOT / ".env")
load_dotenv(Path.home() / ".actguard" / ".env")

SESSION_DIRNAME = ".actguard"
SESSION_FILENAME = "session.json"


def chroma_dir() -> Path:
    """ChromaDB index path (legal_rag/chroma_db/ under install or checkout)."""
    source = REPO_ROOT / "legal_rag" / "chroma_db"
    if source.is_dir() and any(source.iterdir()):
        return source
    return source


def dir_size_mb(path: Path) -> float:
    if not path.is_dir():
        return 0.0
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return round(total / 1024 / 1024, 1)


def session_path(repo_path: Path | str) -> Path:
    return Path(repo_path).resolve() / SESSION_DIRNAME / SESSION_FILENAME


def llm_settings():
    from actguard.llm.config import llm_settings as _llm_settings

    return _llm_settings()


def llm_status_line() -> str:
    from actguard.llm.config import llm_status_line as _llm_status_line

    return _llm_status_line()
