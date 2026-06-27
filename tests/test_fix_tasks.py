"""Fix task selection tests."""

from __future__ import annotations

from actguard.agent.progress import load_completed, mark_completed
from actguard.agent.tasks import is_actionable, select_next_task, task_key
from parsing.implementation_parser import ImplementationTask
from tests.fixtures.sample_implementation import SAMPLE_IMPLEMENTATION_GUIDE
from parsing.implementation_parser import parse_implementation_guide


def test_is_actionable_skips_process_and_policy():
    process = ImplementationTask(
        id="t1", priority="P0", title="DPIA", type="process", why=""
    )
    code = ImplementationTask(
        id="t2", priority="P1", title="Badge", type="code", why=""
    )
    assert not is_actionable(process)
    assert is_actionable(code)


def test_select_next_skips_process_task():
    guide = parse_implementation_guide(SAMPLE_IMPLEMENTATION_GUIDE)
    task = select_next_task(guide.tasks, set())
    assert task is not None
    assert task.priority == "P1"
    assert task.type == "code"


def test_select_next_respects_completed():
    guide = parse_implementation_guide(SAMPLE_IMPLEMENTATION_GUIDE)
    p1 = select_next_task(guide.tasks, set())
    assert p1 is not None
    completed = {task_key(p1)}
    nxt = select_next_task(guide.tasks, completed)
    assert nxt is None


def test_select_next_by_task_prefix():
    guide = parse_implementation_guide(SAMPLE_IMPLEMENTATION_GUIDE)
    task = select_next_task(guide.tasks, set(), task_prefix="P1")
    assert task is not None
    assert task.priority == "P1"


def test_fix_progress_round_trip(tmp_path):
    mark_completed(tmp_path, "P1 — Add badge")
    assert "P1 — Add badge" in load_completed(tmp_path)
