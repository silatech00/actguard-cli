"""LLM provider configuration tests."""

from __future__ import annotations

import os

import pytest

from actguard.llm.config import llm_settings, llm_status_line


def test_default_provider_is_mistral(monkeypatch):
    monkeypatch.delenv("ACTGUARD_PROVIDER", raising=False)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    settings = llm_settings()
    assert settings.provider == "mistral"
    assert settings.api_key == "test-key"
    assert settings.model == "mistral-large-latest"


def test_openai_compatible_provider(monkeypatch):
    monkeypatch.setenv("ACTGUARD_PROVIDER", "openai-compatible")
    monkeypatch.setenv("ACTGUARD_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("ACTGUARD_MODEL", "llama3.2")
    settings = llm_settings()
    assert settings.provider == "openai-compatible"
    assert settings.base_url == "http://localhost:11434/v1"
    assert settings.model == "llama3.2"


def test_api_key_fallback(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.setenv("ACTGUARD_API_KEY", "shared-key")
    settings = llm_settings()
    assert settings.api_key == "shared-key"


def test_llm_status_line_mistral(monkeypatch):
    monkeypatch.setenv("ACTGUARD_PROVIDER", "mistral")
    monkeypatch.setenv("MISTRAL_API_KEY", "secret")
    line = llm_status_line()
    assert "Mistral" in line
    assert "API key set" in line
