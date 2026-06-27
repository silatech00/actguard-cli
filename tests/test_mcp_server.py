"""MCP server smoke tests."""

from __future__ import annotations

import mcp_server.server as mcp_mod


def test_mcp_tools_registered():
    assert mcp_mod.mcp is not None
    assert callable(mcp_mod.actguard_scan)
    assert callable(mcp_mod.actguard_get_questions)
    assert callable(mcp_mod.actguard_submit_answers)
    assert callable(mcp_mod.actguard_generate_report)
    assert callable(mcp_mod.actguard_generate_artifact)
    assert callable(mcp_mod.actguard_status)
