"""ActGuard MCP server for Cursor."""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from actguard.config import llm_status_line
from actguard.generate import generate_artifact
from actguard.pipeline import list_questions, run_local_scan, submit_answers
from actguard.session import load_session, save_session

mcp = FastMCP(
    "ActGuard",
    instructions=(
        "EU compliance scanner: scan workspace locally, ask Q&A, generate "
        "compliance markdown artifacts with the user's own LLM API key."
    ),
)

_workspace_root: Path | None = None


def _root(path: str | None = None) -> Path:
    if path:
        return Path(path).resolve()
    if _workspace_root is not None:
        return _workspace_root
    return Path.cwd().resolve()


def set_workspace_root(path: str | Path) -> None:
    global _workspace_root
    _workspace_root = Path(path).resolve()


@mcp.tool()
def actguard_scan(workspace_path: str = ".", fast: bool = False) -> str:
    """Scan a project directory for EU compliance signals (local, no upload)."""
    root = _root(workspace_path)
    if not root.is_dir():
        return f"Error: not a directory: {root}"
    session = run_local_scan(root, skip_readiness_review=fast)
    save_session(root, session)
    summary = session.get("scan_summary") or {}
    flags = summary.get("profile_flags", [])
    score = (session.get("readiness") or {}).get("final_overall")
    lines = [
        f"Scan complete for {root}",
        f"Session: {root / '.actguard' / 'session.json'}",
        f"Flags: {', '.join(flags) if flags else 'none'}",
    ]
    if score is not None:
        lines.append(f"Readiness score: {score}/100")
    lines.append(
        "Next: actguard_get_questions → actguard_submit_answers → "
        "actguard_generate_report (or actguard_generate_artifact)"
    )
    return "\n".join(lines)


@mcp.tool()
def actguard_get_questions(workspace_path: str = ".") -> str:
    """Return Q&A questions still needed after a scan."""
    root = _root(workspace_path)
    session = load_session(root)
    if session is None:
        return f"No session. Run actguard_scan first."
    questions = list_questions(session)
    return json.dumps(questions, indent=2)


@mcp.tool()
def actguard_submit_answers(
    answers_json: str,
    workspace_path: str = ".",
) -> str:
    """Submit Q&A answers as JSON object {question_key: answer_string}."""
    root = _root(workspace_path)
    session = load_session(root)
    if session is None:
        return "No session. Run actguard_scan first."
    try:
        answers = json.loads(answers_json)
    except json.JSONDecodeError as exc:
        return f"Invalid JSON: {exc}"
    if not isinstance(answers, dict):
        return "answers_json must be a JSON object."
    session = submit_answers(session, {str(k): str(v) for k, v in answers.items()})
    save_session(root, session)
    return "Answers saved. Run actguard_generate_report or actguard_generate_artifact."


@mcp.tool()
def actguard_generate_report(
    workspace_path: str = ".",
    primary_lang: str = "English",
) -> str:
    """Generate compliance report markdown locally (requires MISTRAL_API_KEY or Ollama)."""
    return actguard_generate_artifact("report", workspace_path, primary_lang)


@mcp.tool()
def actguard_generate_artifact(
    artifact: str,
    workspace_path: str = ".",
    primary_lang: str = "English",
) -> str:
    """Generate one markdown artifact: report, implement, rollout, privacy, tos, extras, all."""
    root = _root(workspace_path)
    session = load_session(root)
    if session is None:
        return "No session. Run actguard_scan first."
    if artifact not in ("extras",) and not session.get("qa_submitted"):
        return "Q&A not complete. Run actguard_submit_answers first."
    try:
        saved = generate_artifact(artifact, root, session, primary_lang)
    except FileNotFoundError as exc:
        return f"Error: {exc}"
    except Exception as exc:
        return f"Generation failed: {exc}"
    lines = [f"Saved {len(saved)} file(s):"]
    lines.extend(f"  {p}" for p in saved)
    return "\n".join(lines)


@mcp.tool()
def actguard_status(workspace_path: str = ".") -> str:
    """Show session and LLM status."""
    root = _root(workspace_path)
    session = load_session(root)
    lines = [f"Workspace: {root}", f"LLM: {llm_status_line()}", "Mode: local BYOK"]
    if session:
        lines.append(f"Q&A complete: {session.get('qa_submitted', False)}")
        score = (session.get("readiness") or {}).get("final_overall")
        if score is not None:
            lines.append(f"Readiness: {score}/100")
    else:
        lines.append("Session: none — run actguard_scan")
    return "\n".join(lines)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
