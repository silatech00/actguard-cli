"""Scanner exclude-dir tests."""

from __future__ import annotations

from pathlib import Path

from eu_compliance import (
    SCRIPT_DIR,
    TOOL_INTERNAL_DIRS,
    TOOL_REPO_DIR_NAMES,
    _should_skip,
    scan_context,
)


def test_tool_repo_dir_names():
    assert "ACTGUARD" in TOOL_REPO_DIR_NAMES
    assert "eu-compliance-agent" in TOOL_REPO_DIR_NAMES


def test_should_skip_actguard_tool_internals():
    path = SCRIPT_DIR / "api" / "main.py"
    with scan_context(SCRIPT_DIR):
        assert _should_skip(path)


def test_nested_project_inside_actguard_is_not_skipped():
    project = SCRIPT_DIR / "immigration law ai (test)" / "app.py"
    if not project.is_file():
        return  # fixture project optional in CI
    with scan_context(project.parent):
        assert not _should_skip(project)


def test_parent_audit_skips_actguard_subtree():
    parent = SCRIPT_DIR.parent
    tool_file = SCRIPT_DIR / "eu_compliance.py"
    with scan_context(parent):
        assert _should_skip(tool_file)


def test_tool_internal_dir_names():
    assert "api" in TOOL_INTERNAL_DIRS
    assert "legal_rag" in TOOL_INTERNAL_DIRS
