"""Native unified diff apply tests (no git)."""

from __future__ import annotations

from actguard.agent.patch import apply_unified_diff, apply_unified_diff_check


def test_native_patch_apply(tmp_path):
    hello = tmp_path / "hello.txt"
    hello.write_text("hello\n", encoding="utf-8")

    diff = """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+hello world
"""
    ok, err = apply_unified_diff_check(tmp_path, diff)
    assert ok, err

    ok, err = apply_unified_diff(tmp_path, diff)
    assert ok, err
    assert hello.read_text(encoding="utf-8") == "hello world\n"


def test_native_patch_create_file(tmp_path):
    diff = """--- /dev/null
+++ b/notes/privacy.md
@@ -0,0 +1,2 @@
+# Privacy
+Draft policy.
"""
    ok, err = apply_unified_diff(tmp_path, diff)
    assert ok, err
    created = tmp_path / "notes" / "privacy.md"
    assert created.is_file()
    assert "Draft policy" in created.read_text(encoding="utf-8")
