"""Tests for report parsing and preprocessing."""

from parsing.preprocess import (
    TECHNICAL_REPORT_MARKER,
    split_plain_and_technical,
    strip_emojis,
)
from parsing.report_parser import parse_report_markdown
from tests.fixtures.sample_report import SAMPLE_FULL, SAMPLE_PLAIN, SAMPLE_TECHNICAL


def test_strip_emojis():
    assert "📋" not in strip_emojis("## 📋 Summary")
    assert "Summary" in strip_emojis("## 📋 Summary")


def test_split_plain_and_technical_marker():
    body = f"{SAMPLE_PLAIN}\n\n{TECHNICAL_REPORT_MARKER}\n\n{SAMPLE_TECHNICAL}"
    plain, technical = split_plain_and_technical(body)
    assert "Plain Language" in plain
    assert "EU AI Act" in technical


def test_parse_report_sections():
    structured = parse_report_markdown(SAMPLE_FULL, project_name="TestApp", language="English")
    assert structured.project_name == "TestApp"
    assert len(structured.sections) >= 4
    ai_act = next(s for s in structured.sections if s.id == "ai_act")
    assert "Applies" in ai_act.applicability
    assert len(ai_act.gaps) >= 1
    assert len(ai_act.actions) >= 1
    assert len(structured.priority_matrix) >= 3


def test_parse_plain_summary():
    structured = parse_report_markdown(SAMPLE_FULL, project_name="TestApp")
    assert structured.plain_summary.get("product") or structured.plain_summary.get("next_steps")
