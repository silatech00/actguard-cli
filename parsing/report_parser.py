"""Parse Mistral compliance report markdown into structured data."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from parsing.preprocess import (
    strip_emojis,
    split_plain_and_technical,
    clean_inline_markdown,
    parse_markdown_tables,
)

# Regulation section detection by keyword. Matching is done against a normalized
# heading (bold/numbering/translation stripped), so the parser tolerates the many
# ways the model formats headers: "## **1. EU AI Act ...**", "## GDPR (...)", etc.
# Regulation names/acronyms stay stable across languages, so keyword matching is
# language independent for the section split.
REGULATION_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("ai_act", ("ai act",)),
    ("nis2", ("nis2", "nis 2")),
    ("dsa", ("dsa", "digital services act")),
    ("gdpr", ("gdpr", "rgpd", "general data protection")),
    ("data_act", ("data act",)),
    ("priority", ("overall priority", "priority matrix", "matrice des priorites", "priority ranking")),
]

# Inline bold-bullet field, e.g. "- **Applicability**: Applies — ...".
FIELD_RE = re.compile(r"^[-*+]\s+\*\*(.+?)\*\*\s*:?\s*(.*)$")

# Canonical field detection: accent/case-insensitive substring match against
# common EU-language labels, so fields written as "### Applicability" or
# "### **Lacunes clés**" map to the same structured slot as bullet fields.
_FIELD_MATCHERS: list[tuple[str, tuple[str, ...]]] = [
    ("applicability", ("applic",)),
    ("risk", ("risk", "risq", "risiko", "riesgo", "rischio")),
    ("special", ("special category", "categorie speciale", "categoria especial", "special-category")),
    ("gaps", ("gap", "lacune", "lacuna", "ecart", "brecha", "lucke")),
    ("actions", ("action", "azioni", "acciones", "massnahm", "mesure")),
]


def _deaccent(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


def _heading_text(line: str) -> str | None:
    """Return cleaned text for a markdown heading line, else None.

    Strips leading hashes, bold/italic markers, and a leading numeric prefix
    such as "1." or "2)" so headers like "## **1. EU AI Act**" normalize to
    "EU AI Act".
    """
    s = line.strip()
    if not s.startswith("#"):
        return None
    s = clean_inline_markdown(s.lstrip("#").strip())
    s = re.sub(r"^\d+\s*[.)\-:]\s*", "", s).strip()
    return s


def _match_regulation(line: str) -> tuple[str, str] | None:
    """Match a heading line to a regulation id, tolerant of formatting drift."""
    heading = _heading_text(line)
    if not heading:
        return None
    low = _deaccent(heading).lower()
    for sec_id, keywords in REGULATION_KEYWORDS:
        if any(k in low for k in keywords):
            return sec_id, heading
    return None


def _canonical_field(label: str) -> str | None:
    low = _deaccent(label).lower().strip().rstrip(":")
    for key, needles in _FIELD_MATCHERS:
        if any(n in low for n in needles):
            return key
    return None


@dataclass
class MarkdownTable:
    headers: list[str]
    rows: list[list[str]]
    caption: str = ""


@dataclass
class RegulationSection:
    id: str
    title: str
    applicability: str = ""
    risk_classification: str | None = None
    gaps: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)
    raw_body: str = ""
    body_blocks: list[dict] = field(default_factory=list)


@dataclass
class StructuredReport:
    project_name: str
    generated_at: str
    plain_summary: dict
    sections: list[RegulationSection]
    priority_matrix: list[str]
    disclaimer: str
    tables: list[dict] = field(default_factory=list)
    language: str = "English"

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


def _is_rule(s: str) -> bool:
    """A horizontal-rule / separator line like '---' or '***'."""
    return bool(re.fullmatch(r"[-*_\s]{3,}", s.strip()))


def _strip_rule_tokens(s: str) -> str:
    """Remove stray '---' separators that the model leaves inside text."""
    s = re.sub(r"(?:^|\s)[-*_]{3,}(?=\s|$)", " ", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def _group_paragraphs(lines: list[str]) -> list[str]:
    """Group blank-line-separated blocks into single cleaned items."""
    blocks: list[str] = []
    buf: list[str] = []

    def flush():
        if buf:
            text = _strip_rule_tokens(clean_inline_markdown(" ".join(buf)))
            if text:
                blocks.append(text)
            buf.clear()

    for line in lines:
        s = line.strip()
        if not s or _is_rule(s):
            flush()
            continue
        buf.append(s.lstrip("-*+ ").strip())
    flush()
    return [b for b in blocks if b]


def _group_items(lines: list[str]) -> list[str]:
    """Group a list where each bullet/numbered marker starts a new item."""
    items: list[str] = []
    buf = ""

    def flush():
        nonlocal buf
        if buf:
            text = _strip_rule_tokens(clean_inline_markdown(buf.strip()))
            if text:
                items.append(text)
        buf = ""

    for line in lines:
        s = line.strip()
        if not s or _is_rule(s):
            flush()
            continue
        indented = bool(re.match(r"^(\s{2,}|\t)", line))
        m = re.match(r"^(\d+[.)]|[-*+])\s+(.*)$", s)
        if m and not indented:
            flush()
            buf = m.group(2)
        elif m and indented and buf:
            # Indented sub-bullet: fold into the parent item as detail.
            buf += " " + m.group(2)
        elif buf:
            buf += " " + s
        else:
            buf = s
            flush()
    flush()
    return items


def _parse_plain_summary(text: str) -> dict:
    lines = [strip_emojis(ln) for ln in text.splitlines()]
    product = ""
    reg_lines: list[str] = []
    step_lines: list[str] = []
    section = "intro"
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            low = _deaccent(stripped).lower()
            if "plain terms" in low or "rules apply" in low or "which eu rules" in low:
                section = "regulations"
            elif "do first" in low or "what to do" in low or "next step" in low:
                section = "steps"
            # Unrecognized headings (incl. the main summary header) keep the
            # current section so the intro paragraph is still captured.
            continue
        if section == "intro":
            if stripped and not product:
                product = stripped
        elif section == "regulations":
            reg_lines.append(line)
        elif section == "steps":
            step_lines.append(line)
    return {
        "product": clean_inline_markdown(product),
        "regulations_plain": _group_paragraphs(reg_lines)[:8],
        "next_steps": _group_items(step_lines)[:6],
        "raw": clean_inline_markdown(text.strip()),
    }


def _field_marker(line: str) -> tuple[str | None, str, str] | None:
    """Detect a field marker. Returns (canonical_key, label, inline_value) or None.

    Recognizes both bold-bullet fields ("- **Applicability**: ...") and
    sub-heading fields ("### Applicability", "### **Lacunes clés**").
    """
    s = line.strip()
    h = re.match(r"^#{2,6}\s+(.*)$", s)
    if h:
        label = clean_inline_markdown(h.group(1)).strip().rstrip(":")
        return (_canonical_field(label), label, "")
    m = FIELD_RE.match(s)
    if m:
        label = m.group(1).strip().rstrip(":")
        return (_canonical_field(label), label, m.group(2).strip())
    return None


def _segment_fields(lines: list[str]) -> list[dict]:
    """Split a section body into ordered field segments.

    The first segment (key/marker None) holds any preamble before the first
    field. Each subsequent segment is one field with its following content.
    """
    segments: list[dict] = []
    current: dict = {"key": None, "label": "", "marker": None, "inline": "", "lines": []}

    def flush():
        nonlocal current
        if current["marker"] is not None or current["inline"] or any(l.strip() for l in current["lines"]):
            segments.append(current)
        current = {"key": None, "label": "", "marker": None, "inline": "", "lines": []}

    for line in lines:
        marker = _field_marker(line)
        if marker is not None:
            flush()
            current = {
                "key": marker[0],
                "label": marker[1],
                "marker": line,
                "inline": marker[2],
                "lines": [],
            }
        else:
            current["lines"].append(line)
    flush()
    return segments


def _segment_text(seg: dict) -> str:
    if seg["inline"]:
        return _strip_rule_tokens(clean_inline_markdown(seg["inline"]))
    for line in seg["lines"]:
        s = line.strip()
        if s and not _is_rule(s):
            return _strip_rule_tokens(clean_inline_markdown(s.lstrip("-*+ ").strip()))
    return ""


def _segment_items(seg: dict) -> list[str]:
    body = ([seg["inline"]] if seg["inline"] else []) + seg["lines"]
    return _group_items(body)


def _segment_raw(seg: dict) -> list[str]:
    raw: list[str] = []
    if seg["marker"] is not None:
        raw.append(seg["marker"])
    raw.extend(seg["lines"])
    return raw


def _parse_regulation_section(section_id: str, title: str, body: str) -> RegulationSection:
    body_no_tables, tables = parse_markdown_tables(body)
    segments = _segment_fields(body_no_tables.splitlines())

    applicability = ""
    risk: str | None = None
    gaps: list[str] = []
    actions: list[str] = []
    leftover_lines: list[str] = []

    for seg in segments:
        key = seg["key"]
        if key == "applicability" and not applicability:
            applicability = _segment_text(seg)
        elif key == "risk" and risk is None:
            risk = _segment_text(seg) or None
        elif key == "gaps":
            gaps.extend(_segment_items(seg))
        elif key == "actions":
            actions.extend(_segment_items(seg))
        else:
            # Preamble, special-category, or unrecognized field: keep as prose
            # so it renders under the section instead of being dropped.
            leftover_lines.extend(_segment_raw(seg))

    leftover = "\n".join(leftover_lines).strip()
    body_blocks: list[dict] = []  # reserved; markdown-only CLI does not render blocks

    return RegulationSection(
        id=section_id,
        title=clean_inline_markdown(title),
        applicability=applicability,
        risk_classification=risk,
        gaps=gaps,
        actions=actions,
        tables=tables,
        raw_body=clean_inline_markdown(body_no_tables.strip()),
        body_blocks=body_blocks,
    )


def _split_sections(technical_md: str) -> list[tuple[str, str, str]]:
    lines = technical_md.splitlines()
    sections: list[tuple[str, str, str]] = []
    current_id = ""
    current_title = ""
    current_lines: list[str] = []

    def flush():
        nonlocal current_id, current_title, current_lines
        if current_id and current_lines:
            sections.append((current_id, current_title, "\n".join(current_lines)))
        current_lines = []

    for line in lines:
        match = _match_regulation(line)
        if match:
            flush()
            current_id, current_title = match
            continue
        if current_id:
            current_lines.append(line)
    flush()
    return sections


def parse_report_markdown(
    markdown_body: str,
    *,
    project_name: str = "",
    language: str = "English",
) -> StructuredReport:
    plain_text, technical = split_plain_and_technical(markdown_body)
    plain_summary = _parse_plain_summary(plain_text) if plain_text else {"product": "", "regulations_plain": [], "next_steps": [], "raw": ""}

    sections: list[RegulationSection] = []
    priority_matrix: list[str] = []
    global_tables: list[dict] = []
    disclaimer = ""

    technical_no_tables, technical_tables = parse_markdown_tables(technical)
    global_tables.extend(technical_tables)

    for sec_id, title, body in _split_sections(technical_no_tables):
        if sec_id == "priority":
            priority_body, priority_tables = parse_markdown_tables(body)
            global_tables.extend(priority_tables)
            for line in priority_body.splitlines():
                stripped = line.strip()
                if re.match(r"^\d+\.", stripped) or stripped.startswith("- "):
                    priority_matrix.append(
                        clean_inline_markdown(
                            re.sub(r"^\d+\.\s*", "", stripped.lstrip("- ")).strip()
                        )
                    )
            continue
        sections.append(_parse_regulation_section(sec_id, title, body))

    if "DISCLAIMER" in technical.upper():
        disclaimer = "Automated self-assessment only. This is not legal advice."

    return StructuredReport(
        project_name=project_name,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        plain_summary=plain_summary,
        sections=sections,
        priority_matrix=priority_matrix,
        tables=global_tables,
        disclaimer=disclaimer,
        language=language,
    )
