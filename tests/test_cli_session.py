"""CLI session persistence tests."""

from __future__ import annotations

from actguard.pipeline import submit_answers
from actguard.session import load_session, save_session


def test_session_round_trip(tmp_path):
    session = {
        "project_name": "demo",
        "repo_path": str(tmp_path),
        "state": {"uses_ai": {"value": False}},
        "scan_summary": {"profile_flags": []},
        "readiness": {"final_overall": 90},
        "qa_submitted": False,
        "answers": {},
    }
    path = save_session(tmp_path, session)
    assert path.is_file()
    loaded = load_session(tmp_path)
    assert loaded is not None
    assert loaded["project_name"] == "demo"
    assert loaded["readiness"]["final_overall"] == 90


def test_submit_answers_marks_qa_complete():
    session = {
        "state": {"sector": None},
        "answers": {},
        "qa_submitted": False,
    }
    updated = submit_answers(session, {"sector": "Software / tech"})
    assert updated["qa_submitted"] is True
    assert updated["state"]["sector"] == "Software / tech"
    assert updated["answers"]["sector"] == "Software / tech"
