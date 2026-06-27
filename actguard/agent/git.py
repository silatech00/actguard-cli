"""Git helpers for applying compliance fixes."""

from __future__ import annotations

import subprocess
from pathlib import Path

DEFAULT_BRANCH = "actguard/fixes"


def _run(cmd: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


def is_git_repo(repo_path: Path) -> bool:
    result = _run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        repo_path,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def ensure_git_repo(repo_path: Path) -> None:
    if not is_git_repo(repo_path):
        raise RuntimeError(
            f"{repo_path} is not a git repository. "
            "Initialize git before applying fixes (git init)."
        )


def ensure_branch(repo_path: Path, branch: str = DEFAULT_BRANCH) -> None:
    ensure_git_repo(repo_path)
    current = _run(["git", "branch", "--show-current"], repo_path).stdout.strip()
    if current == branch:
        return
    exists = _run(
        ["git", "show-ref", "--verify", f"refs/heads/{branch}"],
        repo_path,
        check=False,
    )
    if exists.returncode == 0:
        _run(["git", "checkout", branch], repo_path)
    else:
        _run(["git", "checkout", "-b", branch], repo_path)


def apply_diff_check(repo_path: Path, diff_text: str) -> tuple[bool, str]:
    if not diff_text.strip():
        return False, "Empty diff"
    proc = subprocess.run(
        ["git", "apply", "--check", "--whitespace=nowarn"],
        cwd=repo_path,
        input=diff_text,
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return True, ""
    return False, proc.stderr.strip() or proc.stdout.strip()


def apply_diff(repo_path: Path, diff_text: str) -> tuple[bool, str]:
    if not diff_text.strip():
        return False, "Empty diff"
    proc = subprocess.run(
        ["git", "apply", "--whitespace=nowarn"],
        cwd=repo_path,
        input=diff_text,
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return True, ""
    return False, proc.stderr.strip() or proc.stdout.strip()
