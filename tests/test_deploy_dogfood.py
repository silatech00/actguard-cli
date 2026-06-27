"""Dogfood: ActGuard repo should get sensible EU-native hosting recommendation."""

from __future__ import annotations

from pathlib import Path

import pytest

from deploy.fingerprint import build_deploy_profile
from deploy.matcher import match_hosting_providers

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not (REPO_ROOT / "api" / "main.py").exists(), reason="not in repo root")
def test_actguard_repo_self_recommendation():
    profile = build_deploy_profile(str(REPO_ROOT))
    # CLI/MCP pivot: Next.js web app archived; API-only deploy profile
    assert profile["app_model"] == "python_api"
    assert profile["container_ready"] is True
    result = match_hosting_providers(profile)
    primary = result["primary"]
    assert primary is not None
    assert primary["residency_tier"] == 1
    assert primary["provider"] in ("sliplane", "hetzner", "scaleway", "ovhcloud")
