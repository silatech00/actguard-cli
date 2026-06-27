"""Orchestrate compliance fix application."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from actguard.agent.apply import apply_patch, apply_patch_check
from actguard.agent.diff import FIX_DISCLAIMER, generate_task_diff
from actguard.agent.git import is_git_repo
from actguard.agent.progress import load_completed, mark_completed
from actguard.agent.tasks import (
    load_tasks,
    resolve_task_files,
    select_next_task,
    task_key,
)
from parsing.implementation_parser import ImplementationTask


@dataclass
class FixResult:
    task: ImplementationTask
    diff: str
    applied: bool
    message: str


def run_fix(
    repo_path: Path | str,
    *,
    dry_run: bool = False,
    yes: bool = False,
    interactive: bool = True,
    task_prefix: str | None = None,
    use_next: bool = True,
) -> FixResult:
    root = Path(repo_path).resolve()
    tasks = load_tasks(root)
    completed = load_completed(root)

    if not use_next and not task_prefix:
        raise ValueError("Specify --next or --task P0|P1|...")

    task = select_next_task(tasks, completed, task_prefix=task_prefix)
    if task is None:
        raise RuntimeError("No remaining actionable tasks to fix.")

    files = resolve_task_files(root, task)
    if not files and not (task.type or "").lower() in ("docs", "infra", "config", "code"):
        raise RuntimeError(
            f"Task {task_key(task)} has no resolvable files. Skip or implement manually."
        )

    print(f"\n{FIX_DISCLAIMER}\n")
    print(f"Task: {task_key(task)}")
    if files:
        print("Files: " + ", ".join(str(p.relative_to(root)) for p in files))
    if is_git_repo(root):
        print("Apply mode: git (branch actguard/fixes)")
    else:
        print("Apply mode: direct patch (backups under .actguard/backups/)")

    diff = generate_task_diff(root, task, files)
    print("\n--- proposed diff ---\n")
    print(diff)
    print("\n--- end diff ---\n")

    if dry_run:
        ok, err = apply_patch_check(root, diff)
        if ok:
            mode = "git apply --check" if is_git_repo(root) else "native patch check"
            return FixResult(task, diff, False, f"Dry run: diff passes {mode}")
        return FixResult(task, diff, False, f"Dry run: diff failed check — {err}")

    should_apply = yes
    if interactive and not yes:
        answer = input("Apply this diff? [y/N] ").strip().lower()
        should_apply = answer in ("y", "yes")

    if not should_apply:
        return FixResult(task, diff, False, "Skipped — no changes applied")

    ok, err, method = apply_patch(root, diff, task_label=task_key(task))
    if not ok:
        raise RuntimeError(f"Patch failed ({method}): {err}")

    mark_completed(root, task_key(task))
    if method == "git":
        msg = f"Applied on branch actguard/fixes — {task_key(task)}"
    else:
        msg = f"Applied directly — {task_key(task)}.{err}"
    return FixResult(task, diff, True, msg)
