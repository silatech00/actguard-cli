"""Tests for hosting provider matcher."""

from __future__ import annotations

import tempfile
from pathlib import Path

from deploy.fingerprint import build_deploy_profile
from deploy.matcher import match_hosting_providers
from tests.fixtures.deploy_repos import write_actguard_like_repo, write_streamlit_repo


def test_docker_fastapi_recommends_eu_native():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_actguard_like_repo(root)
        profile = build_deploy_profile(str(root))
        result = match_hosting_providers(profile)
        primary = result["primary"]
        assert primary is not None
        assert primary["residency_tier"] == 1
        assert primary["provider"] in ("sliplane", "hetzner", "scaleway", "ovhcloud")


def test_railway_without_eu_pin_warns():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_actguard_like_repo(root)
        profile = build_deploy_profile(str(root))
        result = match_hosting_providers(profile)
        warnings_text = " ".join(result["warnings"]).lower()
        assert "railway" in warnings_text or "region" in warnings_text


def test_streamlit_excludes_vercel():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_streamlit_repo(root)
        profile = build_deploy_profile(str(root))
        result = match_hosting_providers(profile)
        primary = result["primary"]
        assert primary is not None
        assert primary["provider"] != "vercel"
        alts = [a["provider"] for a in result["alternatives"]]
        assert "vercel" not in alts or primary["provider"] in ("sliplane", "hetzner", "fly_io")
