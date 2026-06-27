"""Scan and Q&A orchestration shared by CLI, MCP, and legacy eu_compliance.py."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from actguard.services.scan_service import run_full_scan
from eu_compliance import apply_answers, get_questions
from readiness.engine import compute_readiness_score


def run_local_scan(
    repo_path: str | Path,
    *,
    progress_callback: Callable[[str], None] | None = None,
    skip_readiness_review: bool = False,
) -> dict[str, Any]:
    """Run full local scan and readiness scoring; return session payload."""
    repo = str(Path(repo_path).resolve())
    result = run_full_scan(repo, progress_callback=progress_callback)

    synthesis = (result["state"].get("deep_synthesis") or {}) or None
    if progress_callback:
        progress_callback("Computing EU readiness score…")
    readiness = compute_readiness_score(
        result["state"],
        synthesis,
        progress_callback=progress_callback,
        skip_review=skip_readiness_review,
    )

    return {
        "project_name": result["project_name"],
        "repo_path": repo,
        "state": result["state"],
        "scan_summary": result["scan_summary"],
        "readiness": readiness,
        "deep_analysis_done": result["deep_analysis_done"],
        "deep_error": result["deep_error"],
        "has_synthesis": result["has_synthesis"],
        "qa_submitted": False,
        "answers": {},
    }


def list_questions(session: dict[str, Any]) -> list[dict]:
    return get_questions(session["state"])


def submit_answers(session: dict[str, Any], answers: dict[str, str]) -> dict[str, Any]:
    updated_state = apply_answers(session["state"], answers)
    merged_answers = dict(session.get("answers") or {})
    merged_answers.update(answers)
    return {
        **session,
        "state": updated_state,
        "answers": merged_answers,
        "qa_submitted": True,
    }
