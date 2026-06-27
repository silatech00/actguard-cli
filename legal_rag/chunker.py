"""Parse EUR-Lex HTML exports into article/annex chunks for RAG indexing."""

from __future__ import annotations

import random
import re
from pathlib import Path

from bs4 import BeautifulSoup

PACKAGE_DIR = Path(__file__).resolve().parent
AGENT_DIR = PACKAGE_DIR.parent


REGULATION_FILES = {
    "ai_act.html": "AI Act",
    "nis2.html": "NIS2",
    "dsa.html": "DSA",
    "gdpr.html": "GDPR",
    "data_act.html": "Data Act",
}

ARTICLE_FALLBACK_RE = re.compile(r"Article\s+\d+", re.IGNORECASE)
ANNEX_SECTION_RE = re.compile(r"^\d+\.\s", re.MULTILINE)


def resolve_legal_texts_dir() -> Path:
    """Return the directory containing the five regulation HTML files.

    Checks in order:
    1. Bundled legal_texts/ (inside Nuitka _MEIPASS)
    2. Local legal_texts/ next to this package
    3. Parent legal_texts/ (source mode)
    """
    # Installed package: legal_texts/*.html at site-packages/legal_texts/
    try:
        import legal_texts as lt_pkg

        pkg_dir = Path(lt_pkg.__file__).resolve().parent
        if (pkg_dir / "ai_act.html").exists():
            return pkg_dir
    except ImportError:
        pass

    # Check local legal_texts/ next to repo root (source checkout)
    local = AGENT_DIR / "legal_texts"
    if local.is_dir() and (local / "ai_act.html").exists():
        return local

    # Check parent legal_texts/ (source mode)
    parent = AGENT_DIR.parent / "legal_texts"
    if parent.is_dir() and (parent / "ai_act.html").exists():
        return parent

    raise FileNotFoundError(
        "legal_texts/ not found. Expected ai_act.html under "
        f"{local} or {parent}"
    )


def _clean_text(text: str) -> str:
    text = re.sub(r"\u00a0", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_title(div) -> str:
    title_el = div.select_one("div.eli-title p.oj-sti-art")
    if title_el:
        return _clean_text(title_el.get_text())
    doc_ti = div.select_one("p.oj-doc-ti")
    if doc_ti:
        return _clean_text(doc_ti.get_text())
    return ""


def _chunk_articles(soup: BeautifulSoup, regulation: str) -> list[dict]:
    chunks: list[dict] = []
    for div in soup.select('div.eli-subdivision[id^="art_"]'):
        art_id = div.get("id", "")
        art_num = art_id.replace("art_", "")
        header = div.select_one("p.oj-ti-art")
        article = _clean_text(header.get_text()) if header else f"Article {art_num}"
        title = _extract_title(div)
        text = _clean_text(div.get_text(separator="\n"))
        if not text:
            continue
        chunks.append(
            {
                "regulation": regulation,
                "article": article,
                "title": title,
                "text": text,
            }
        )
    return chunks


def _split_annex_sections(full_text: str) -> list[tuple[str, str]]:
    """Split annex plain text on numbered top-level sections (1., 2., ...)."""
    matches = list(ANNEX_SECTION_RE.finditer(full_text))
    if len(matches) < 2:
        return [("", full_text)]

    sections: list[tuple[str, str]] = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(full_text)
        section_text = full_text[start:end].strip()
        label = match.group(0).strip().rstrip(".")
        sections.append((label, section_text))
    return sections


def _chunk_annexes(soup: BeautifulSoup, regulation: str) -> list[dict]:
    chunks: list[dict] = []
    for div in soup.select('div.eli-container[id^="anx_"]'):
        annex_id = div.get("id", "").replace("anx_", "")
        header_parts = [
            _clean_text(el.get_text())
            for el in div.select("p.oj-doc-ti")
            if _clean_text(el.get_text())
        ]
        annex_label = header_parts[0] if header_parts else f"Annex {annex_id}"
        annex_title = header_parts[1] if len(header_parts) > 1 else ""
        full_text = _clean_text(div.get_text(separator="\n"))
        if not full_text:
            continue

        sections = _split_annex_sections(full_text)
        if len(sections) == 1 and sections[0][0] == "":
            chunks.append(
                {
                    "regulation": regulation,
                    "article": annex_label,
                    "title": annex_title,
                    "text": full_text,
                }
            )
            continue

        for section_label, section_text in sections:
            article = f"{annex_label} — Section {section_label}"
            chunks.append(
                {
                    "regulation": regulation,
                    "article": article,
                    "title": annex_title,
                    "text": section_text,
                }
            )
    return chunks


def _chunk_regex_fallback(html: str, regulation: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    body = soup.find("body") or soup
    plain = _clean_text(body.get_text(separator="\n"))
    matches = list(ARTICLE_FALLBACK_RE.finditer(plain))
    if not matches:
        return []

    chunks: list[dict] = []
    for idx, match in enumerate(matches):
        article = match.group(0)
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(plain)
        text = plain[start:end].strip()
        if text:
            chunks.append(
                {
                    "regulation": regulation,
                    "article": article,
                    "title": "",
                    "text": text,
                }
            )
    return chunks


def chunk_html(html_path: str | Path, regulation: str) -> list[dict]:
    """Parse one EUR-Lex HTML file into article/annex chunks."""
    html = Path(html_path).read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")

    chunks = _chunk_articles(soup, regulation)
    chunks.extend(_chunk_annexes(soup, regulation))

    if not chunks:
        chunks = _chunk_regex_fallback(html, regulation)

    return chunks


def chunk_all_regulations(legal_dir: Path | None = None) -> list[dict]:
    legal_dir = legal_dir or resolve_legal_texts_dir()
    all_chunks: list[dict] = []
    for filename, label in REGULATION_FILES.items():
        path = legal_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing regulation file: {path}")
        all_chunks.extend(chunk_html(path, label))
    return all_chunks


if __name__ == "__main__":
    legal_texts = resolve_legal_texts_dir()
    print(f"Parsing legal texts from: {legal_texts}\n")

    for filename, label in REGULATION_FILES.items():
        file_chunks = chunk_html(legal_texts / filename, label)
        print(f"{label}: {len(file_chunks)} chunks")

        sample = random.sample(file_chunks, min(3, len(file_chunks)))
        for chunk in sample:
            preview = chunk["text"][:100].replace("\n", " ")
            title = f" — {chunk['title']}" if chunk["title"] else ""
            print(f"  · {chunk['article']}{title}")
            print(f"    {preview}...")
        print()
