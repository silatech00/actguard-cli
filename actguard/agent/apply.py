"""Apply diffs via git or native patch fallback."""

from __future__ import annotations

import re
from pathlib import Path

from actguard.agent.git import (
    DEFAULT_BRANCH,
    apply_diff,
    apply_diff_check,
    ensure_branch,
    is_git_repo,
)
from actguard.agent.patch import (
    affected_paths,
    apply_unified_diff,
    apply_unified_diff_check,
    backup_files,
)


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", text).strip("-")[:80] or "task"


def apply_patch_check(repo_path: Path, diff_text: str) -> tuple[bool, str]:
    if is_git_repo(repo_path):
        return apply_diff_check(repo_path, diff_text)
    return apply_unified_diff_check(repo_path, diff_text)


def apply_patch(
    repo_path: Path,
    diff_text: str,
    *,
    task_label: str = "fix",
) -> tuple[bool, str, str]:
    """
    Apply diff to project. Returns (ok, error, method) where method is 'git' or 'native'.
  """
    if is_git_repo(repo_path):
        ensure_branch(repo_path)
        ok, err = apply_diff_check(repo_path, diff_text)
        if not ok:
            return False, err, "git"
        ok, err = apply_diff(repo_path, diff_text)
        return ok, err, "git"

    paths = affected_paths(diff_text)
    backup_dir = repo_path / ".actguard" / "backups" / _slug(task_label)
    if paths:
        backup_files(repo_path, paths, backup_dir)

    ok, err = apply_unified_diff_check(repo_path, diff_text)
    if not ok:
        return False, err, "native"
    ok, err = apply_unified_diff(repo_path, diff_text)
    if ok:
        backup_note = f" Backups: {backup_dir}" if paths else ""
        return True, backup_note, "native"
    return False, err, "native"
