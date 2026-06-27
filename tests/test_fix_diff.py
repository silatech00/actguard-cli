"""Git diff apply tests."""

from __future__ import annotations

import subprocess

from actguard.agent.git import apply_diff, apply_diff_check, is_git_repo


def _git(cwd, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def test_git_apply_check_and_apply(tmp_path):
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@test.com")
    _git(tmp_path, "config", "user.name", "Test")

    hello = tmp_path / "hello.txt"
    hello.write_text("hello\n", encoding="utf-8")
    _git(tmp_path, "add", "hello.txt")
    _git(tmp_path, "commit", "-m", "init")

    diff = """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+hello world
"""
    assert is_git_repo(tmp_path)
    ok, err = apply_diff_check(tmp_path, diff)
    assert ok, err

    ok, err = apply_diff(tmp_path, diff)
    assert ok, err
    assert hello.read_text(encoding="utf-8") == "hello world\n"
