"""Tests for implementation guide parser."""

from parsing.implementation_parser import parse_implementation_guide
from tests.fixtures.sample_implementation import SAMPLE_IMPLEMENTATION_GUIDE


def test_parse_implementation_guide_tasks():
    guide = parse_implementation_guide(
        SAMPLE_IMPLEMENTATION_GUIDE,
        project_name="HealthBot",
        language="English",
    )
    assert guide.project_name == "HealthBot"
    assert len(guide.tasks) == 2
    assert guide.tasks[0].priority == "P0"
    assert "DPIA" in guide.tasks[0].title
    assert guide.tasks[0].regulation == "GDPR"
    assert guide.tasks[0].type == "process"
    assert "models.py" in guide.tasks[0].files
    assert len(guide.tasks[0].steps) >= 2
    assert len(guide.tasks[0].acceptance_criteria) >= 1

    assert guide.tasks[1].priority == "P1"
    assert guide.tasks[1].type == "code"
    assert "RecommendationCard" in guide.tasks[1].files[0]


def test_parse_implementation_guide_agent_prompt():
    guide = parse_implementation_guide(SAMPLE_IMPLEMENTATION_GUIDE)
    assert "HealthBot" in guide.agent_prompt
    assert "P0" in guide.agent_prompt
    assert "P1" in guide.agent_prompt


def test_parse_implementation_guide_legal_notes():
    guide = parse_implementation_guide(SAMPLE_IMPLEMENTATION_GUIDE)
    assert len(guide.legal_notes) >= 1
    assert any("DPIA" in note for note in guide.legal_notes)


def test_parse_implementation_guide_to_dict():
    guide = parse_implementation_guide(SAMPLE_IMPLEMENTATION_GUIDE)
    data = guide.to_dict()
    assert data["schemaVersion"] == "eucompliance.implementation.v1"
    assert "tasks" in data
    assert "agent_prompt" in data
