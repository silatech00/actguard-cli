"""Task selection from implementation guide."""

from __future__ import annotations

from pathlib import Path

from parsing.implementation_parser import ImplementationTask, parse_implementation_guide

ACTIONABLE_TYPES = frozenset({"code", "config", "docs", "infra"})
SKIP_TYPES = frozenset({"process", "policy"})
PRIORITY_ORDER = ("P0", "P1", "P2", "P3")


def task_key(task: ImplementationTask) -> str:
    return f"{task.priority} — {task.title}"


def _priority_rank(priority: str) -> int:
    p = priority.upper()
    try:
        return PRIORITY_ORDER.index(p)
    except ValueError:
        return len(PRIORITY_ORDER)


def is_actionable(task: ImplementationTask) -> bool:
    task_type = (task.type or "").strip().lower()
    if task_type in SKIP_TYPES:
        return False
    if task_type in ACTIONABLE_TYPES:
        return True
    if not task_type:
        return bool(task.files)
    return task_type not in SKIP_TYPES


def load_implementation_guide(repo_path: Path | str) -> str:
    root = Path(repo_path).resolve()
    path = root / "implementation_guide.md"
    if not path.is_file():
        raise FileNotFoundError(
            f"No implementation_guide.md at {path}. Run: actguard generate implement"
        )
    return path.read_text(encoding="utf-8")


def load_tasks(repo_path: Path | str) -> list[ImplementationTask]:
    md = load_implementation_guide(repo_path)
    guide = parse_implementation_guide(md)
    return guide.tasks


def select_next_task(
    tasks: list[ImplementationTask],
    completed: set[str],
    *,
    task_prefix: str | None = None,
) -> ImplementationTask | None:
    """Return next actionable task by priority, skipping completed."""
    candidates = [t for t in tasks if is_actionable(t) and task_key(t) not in completed]
    if task_prefix:
        prefix = task_prefix.upper()
        candidates = [t for t in candidates if t.priority.upper() == prefix]
        if not candidates:
            return None
        return candidates[0]

    candidates.sort(key=lambda t: (_priority_rank(t.priority), t.title))
    return candidates[0] if candidates else None


def resolve_task_files(repo_path: Path, task: ImplementationTask) -> list[Path]:
    root = repo_path.resolve()
    resolved: list[Path] = []
    for rel in task.files:
        rel = rel.strip().strip("`")
        if not rel or rel.lower().startswith("n/a"):
            continue
        path = (root / rel).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            continue
        if path.is_file():
            resolved.append(path)
    return resolved
