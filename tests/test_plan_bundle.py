"""Plan artifact writer tests."""

from __future__ import annotations

import json

from actguard.output import save_plan_artifacts


def test_save_plan_artifacts_writes_expected_files(tmp_path):
    artifacts = {
        "compliance_report": {
            "reports": {"english": "# Report\n"},
        },
        "implementation_guide": {
            "reports": {"english": "# Implementation\n"},
            "agent_prompts": {"english": "Fix the app"},
        },
        "rollout_guide": {
            "reports": {"english": "# Rollout\n"},
        },
        "founder_extras": {"structured": {"default": {"hosting": {}}}},
    }

    saved = save_plan_artifacts(tmp_path, artifacts, "English")
    names = {p.name for p in saved}

    assert "compliance_report.md" in names
    assert "implementation_guide.md" in names
    assert "rollout_guide.md" in names
    assert "agent_prompt.md" in names
    assert "founder_extras.json" in names
    assert not any(n.endswith(".pdf") for n in names)

    assert (tmp_path / "agent_prompt.md").read_text() == "Fix the app"
    extras = json.loads((tmp_path / "founder_extras.json").read_text())
    assert "structured" in extras
