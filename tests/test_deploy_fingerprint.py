"""Tests for deploy fingerprinting."""

from __future__ import annotations

from pathlib import Path

import pytest

from deploy.fingerprint import build_deploy_profile
from tests.fixtures.deploy_repos import (
    write_actguard_like_repo,
    write_next_spa_repo,
    write_streamlit_repo,
)


@pytest.fixture()
def actguard_repo(tmp_path: Path) -> Path:
    write_actguard_like_repo(tmp_path)
    return tmp_path


@pytest.fixture()
def streamlit_repo(tmp_path: Path) -> Path:
    write_streamlit_repo(tmp_path)
    return tmp_path


def test_actguard_like_profile(actguard_repo: Path):
    profile = build_deploy_profile(str(actguard_repo))
    assert profile["app_model"] == "split_monorepo"
    assert profile["container_ready"] is True
    assert "postgres" in profile["persistence"]
    assert "fastapi" in profile["runtimes"] or "python" in profile["runtimes"]
    assert "railway.toml" in profile["existing_deploy_hints"]
    assert profile["confidence"] in ("high", "medium")


def test_streamlit_profile(streamlit_repo: Path):
    profile = build_deploy_profile(str(streamlit_repo))
    assert profile["app_model"] == "streamlit"
    assert "openai" in profile["detected_vendors"]


def test_next_spa_profile(tmp_path: Path):
    write_next_spa_repo(tmp_path)
    profile = build_deploy_profile(str(tmp_path))
    assert profile["app_model"] in ("next_fullstack", "static_spa")
    assert "node" in profile["runtimes"]
