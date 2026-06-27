"""Tests for founder extras."""

from __future__ import annotations

import tempfile
from pathlib import Path

from deploy.extras import build_founder_extras
from deploy.fingerprint import build_deploy_profile
from deploy.matcher import match_hosting_providers
from tests.fixtures.deploy_repos import write_actguard_like_repo


def test_founder_extras_structure():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_actguard_like_repo(root)
        profile = build_deploy_profile(str(root))
        hosting = match_hosting_providers(profile)
        state = {"uses_ai": {"value": True}, "has_security": {"value": True}, "deploy_profile": profile}
        extras = build_founder_extras(state, profile, hosting, readiness={"final_overall": 75, "sub_scores": {"gdpr": 80}})
        assert "subprocessors" in extras
        assert "launch_gates" in extras
        assert len(extras["launch_gates"]) >= 3
        assert "mistralai" in [s["id"] for s in extras["subprocessors"]]
        assert extras["investor_summary"]["readiness_score"] == 75
