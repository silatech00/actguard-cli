"""Apply unified diffs without git."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str] = field(default_factory=list)


@dataclass
class FilePatch:
    old_path: str | None
    new_path: str
    hunks: list[Hunk] = field(default_factory=list)


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_PATH_RE = re.compile(r"^(?:---|\+\+\+) (?:a/|b/)?(.+)$")


def _normalize_path(raw: str) -> str | None:
    path = raw.strip()
    if path in ("/dev/null", "dev/null"):
        return None
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    return path


def parse_unified_diff(diff_text: str) -> list[FilePatch]:
    """Parse a unified diff into structured file patches."""
    lines = diff_text.replace("\r\n", "\n").split("\n")
    patches: list[FilePatch] = []
    current: FilePatch | None = None
    hunk: Hunk | None = None
    i = 0

    while i < len(lines):
        line = lines[i]

        if line.startswith("--- "):
            old_raw = line[4:].strip()
            if i + 1 >= len(lines) or not lines[i + 1].startswith("+++ "):
                i += 1
                continue
            new_raw = lines[i + 1][4:].strip()
            current = FilePatch(old_path=_normalize_path(old_raw), new_path=_normalize_path(new_raw) or "")
            patches.append(current)
            hunk = None
            i += 2
            continue

        m = _HUNK_RE.match(line)
        if m and current is not None:
            hunk = Hunk(
                old_start=int(m.group(1)),
                old_count=int(m.group(2) or "1"),
                new_start=int(m.group(3)),
                new_count=int(m.group(4) or "1"),
            )
            current.hunks.append(hunk)
            i += 1
            continue

        if hunk is not None and line and line[0] in (" ", "+", "-", "\\"):
            hunk.lines.append(line)
        i += 1

    return [p for p in patches if p.new_path]


def _apply_hunk(lines: list[str], hunk: Hunk) -> list[str]:
    """Apply one hunk to a list of lines (without trailing newlines)."""
    start_idx = max(0, hunk.old_start - 1)
    cursor = start_idx
    result = lines[:start_idx]
    hunk_lines = hunk.lines

    hi = 0
    while hi < len(hunk_lines):
        tag = hunk_lines[hi]
        if tag.startswith("\\"):
            hi += 1
            continue
        prefix = tag[0]
        content = tag[1:]

        if prefix == " ":
            if cursor >= len(lines) or lines[cursor] != content:
                raise ValueError(
                    f"Context mismatch at line {cursor + 1}: "
                    f"expected {content!r}, got {lines[cursor] if cursor < len(lines) else 'EOF'!r}"
                )
            result.append(content)
            cursor += 1
        elif prefix == "-":
            if cursor >= len(lines) or lines[cursor] != content:
                raise ValueError(
                    f"Remove mismatch at line {cursor + 1}: "
                    f"expected {content!r}, got {lines[cursor] if cursor < len(lines) else 'EOF'!r}"
                )
            cursor += 1
        elif prefix == "+":
            result.append(content)
        hi += 1

    result.extend(lines[cursor:])
    return result


def _read_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text:
        return []
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(lines)
    if content:
        content += "\n"
    path.write_text(content, encoding="utf-8")


def apply_unified_diff_check(repo_path: Path, diff_text: str) -> tuple[bool, str]:
    """Validate diff can be applied without writing files."""
    try:
        patches = parse_unified_diff(diff_text)
        if not patches:
            return False, "No file patches found in diff"
        for patch in patches:
            target = repo_path / patch.new_path
            lines = _read_lines(target) if patch.old_path else []
            if patch.old_path and not target.is_file():
                return False, f"File not found: {patch.new_path}"
            for hunk in patch.hunks:
                lines = _apply_hunk(lines, hunk)
        return True, ""
    except ValueError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, str(exc)


def apply_unified_diff(repo_path: Path, diff_text: str) -> tuple[bool, str]:
    """Apply unified diff by writing files directly."""
    try:
        patches = parse_unified_diff(diff_text)
        if not patches:
            return False, "No file patches found in diff"
        for patch in patches:
            target = repo_path / patch.new_path
            lines = _read_lines(target) if patch.old_path else []
            if patch.old_path and not target.is_file():
                return False, f"File not found: {patch.new_path}"
            for hunk in patch.hunks:
                lines = _apply_hunk(lines, hunk)
            _write_lines(target, lines)
        return True, ""
    except ValueError as exc:
        return False, str(exc)
    except OSError as exc:
        return False, str(exc)


def backup_files(repo_path: Path, rel_paths: list[str], backup_dir: Path) -> None:
    """Copy files to backup_dir before patching (non-git safety net)."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    for rel in rel_paths:
        src = repo_path / rel
        if src.is_file():
            dst = backup_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def affected_paths(diff_text: str) -> list[str]:
    patches = parse_unified_diff(diff_text)
    paths: list[str] = []
    for p in patches:
        if p.old_path:
            paths.append(p.old_path)
        if p.new_path and p.new_path not in paths:
            paths.append(p.new_path)
    return paths
