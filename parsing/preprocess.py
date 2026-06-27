"""Markdown preprocessing and parsing helpers."""

from __future__ import annotations

import re

TECHNICAL_REPORT_MARKER = "<!-- TECHNICAL_REPORT -->"

_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\u2600-\u27BF"
    "\uFE0F"
    "]+",
    flags=re.UNICODE,
)


def strip_emojis(text: str) -> str:
    return _EMOJI_RE.sub("", text).strip()


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_CODE_RE = re.compile(r"`(.+?)`")


def clean_inline_markdown(text: str) -> str:
    """Strip all inline markdown markers for plain-text consumers."""
    if not text:
        return text
    prev = None
    while prev != text:
        prev = text
        text = _BOLD_RE.sub(r"\1", text)
        text = _ITALIC_RE.sub(r"\1", text)
        text = _CODE_RE.sub(r"\1", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"\*+", "", text)
    return text.strip()


_SEPARATOR_RE = re.compile(r"^\|?[\s\-:|]+\|?$")


def _is_separator_row(line: str) -> bool:
    """A markdown table separator line, e.g. |---|:--:|---|."""
    s = line.strip()
    return bool(s) and bool(_SEPARATOR_RE.match(s)) and "-" in s


def _is_table_row(line: str) -> bool:
    """A line that looks like a pipe table row (content on both sides of a pipe)."""
    s = line.strip()
    if "|" not in s or _is_separator_row(s):
        return False
    cells = s.strip("|").split("|")
    return len(cells) >= 2


def parse_markdown_tables(md: str) -> tuple[str, list[dict]]:
    """Extract markdown pipe tables; return remaining text and table objects.

    Tolerant of loose LLM output: tables are detected either by a proper
    separator row or by two or more consecutive pipe rows even when the
    separator is missing or malformed.
    """
    lines = md.splitlines()
    out_lines: list[str] = []
    tables: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _is_table_row(line):
            block: list[str] = []
            j = i
            while j < len(lines) and (_is_table_row(lines[j]) or _is_separator_row(lines[j])):
                block.append(lines[j])
                j += 1
            has_sep = any(_is_separator_row(b) for b in block)
            data_rows = [b for b in block if not _is_separator_row(b)]
            if (has_sep and len(data_rows) >= 1) or len(data_rows) >= 2:
                parsed = _parse_table_block(block)
                if parsed:
                    tables.append(parsed)
                    i = j
                    continue
        out_lines.append(line)
        i += 1
    return "\n".join(out_lines), tables


def _parse_table_block(lines: list[str]) -> dict | None:
    data_lines = [ln for ln in lines if not _is_separator_row(ln)]
    if not data_lines:
        return None

    def split_row(row: str) -> list[str]:
        return [clean_inline_markdown(c.strip()) for c in row.strip().strip("|").split("|")]

    headers = split_row(data_lines[0])
    headers = [h for h in headers if h] or headers
    if not headers:
        return None
    n = len(headers)
    rows: list[list[str]] = []
    for line in data_lines[1:]:
        cells = split_row(line)
        if not any(c for c in cells):
            continue
        while len(cells) < n:
            cells.append("")
        rows.append(cells[:n])
    if not rows:
        return None
    return {"headers": headers, "rows": rows}


def split_plain_and_technical(body: str) -> tuple[str, str]:
    """Split report body on explicit marker or legacy --- delimiter."""
    if TECHNICAL_REPORT_MARKER in body:
        plain, _, technical = body.partition(TECHNICAL_REPORT_MARKER)
        return plain.strip(), technical.strip()
    if "\n---\n" in body:
        parts = body.split("\n---\n", 1)
        if len(parts) == 2 and len(parts[0]) < 8000:
            return parts[0].strip(), parts[1].strip()
    return "", body.strip()


def normalize_field_lines(md: str) -> str:
    """Convert **Label**: value bullets to HTML-friendly divs for WeasyPrint."""
    lines = md.splitlines()
    out: list[str] = []
    for line in lines:
        m = re.match(r"^-\s+\*\*(.+?)\*\*:\s*(.*)$", line.strip())
        if not m:
            m = re.match(r"^-\s+(.+?):\s*(.*)$", line.strip())
        if m:
            label, value = m.group(1), m.group(2)
            out.append(f'<div class="field-row"><span class="field-label">{label}</span>'
                       f'<span class="field-value">{value}</span></div>')
        else:
            out.append(line)
    return "\n".join(out)


def preprocess_markdown(md: str) -> str:
    cleaned = strip_emojis(md)
    cleaned = normalize_field_lines(cleaned)
    return clean_inline_markdown(cleaned)


def wrap_regulation_sections(html: str) -> str:
    """Add CSS classes to regulation h2 headings."""
    patterns = [
        (r"<h2>EU AI Act", '<h2 class="reg-section reg-ai-act">EU AI Act'),
        (r"<h2>NIS2", '<h2 class="reg-section reg-nis2">NIS2'),
        (r"<h2>DSA", '<h2 class="reg-section reg-dsa">DSA'),
        (r"<h2>GDPR", '<h2 class="reg-section reg-gdpr">GDPR'),
        (r"<h2>Data Act", '<h2 class="reg-section reg-data-act">Data Act'),
        (r"<h2>Overall priority", '<h2 class="reg-section reg-priority">Overall priority'),
        (r"<h2>What This Means", '<h2 class="reg-section reg-summary">What This Means'),
    ]
    for pattern, replacement in patterns:
        html = re.sub(pattern, replacement, html, count=1)
    return html
