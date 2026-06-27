"""Tests for markdown preprocessing."""

from parsing.preprocess import (
    TECHNICAL_REPORT_MARKER,
    preprocess_markdown,
    split_plain_and_technical,
    strip_emojis,
)


def test_clean_inline_markdown():
    from parsing.preprocess import clean_inline_markdown, parse_markdown_tables
    assert clean_inline_markdown("**Applicability**: Applies") == "Applicability: Applies"
    assert "**" not in clean_inline_markdown("No **raw** markers left")
    assert "*" not in clean_inline_markdown("Mixed *italic* and **bold** text")
    md = "## Summary\n\n- **Applicability**: Applies to all"
    out = preprocess_markdown(md)
    assert "field-row" in out
    assert "**" not in out

    table_md = "| Reg | Status |\n| --- | --- |\n| AI Act | Applies |"
    remaining, tables = parse_markdown_tables(table_md)
    assert len(tables) == 1
    assert tables[0]["headers"] == ["Reg", "Status"]
    assert tables[0]["rows"][0][0] == "AI Act"


def test_split_marker():
    body = f"plain part\n\n{TECHNICAL_REPORT_MARKER}\n\ntechnical part"
    plain, tech = split_plain_and_technical(body)
    assert plain == "plain part"
    assert tech == "technical part"
