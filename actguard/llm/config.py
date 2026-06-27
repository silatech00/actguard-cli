"""LLM provider configuration from environment."""

from __future__ import annotations

import os
from dataclasses import dataclass

from actguard.config import REPO_ROOT
from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env")

DEFAULT_MISTRAL_MODEL = "mistral-large-latest"
DEFAULT_OPENAI_MODEL = "llama3.2"


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    model: str
    api_key: str
    base_url: str
    timeout_ms: int
    report_timeout_ms: int


def llm_settings() -> LLMSettings:
    provider = (
        os.environ.get("ACTGUARD_PROVIDER", "").strip().lower() or "mistral"
    )
    timeout_ms = int(os.environ.get("MISTRAL_TIMEOUT_MS", "300000"))
    report_timeout_ms = int(os.environ.get("MISTRAL_REPORT_TIMEOUT_MS", "600000"))

    api_key = (
        os.environ.get("ACTGUARD_API_KEY", "").strip()
        or os.environ.get("MISTRAL_API_KEY", "").strip()
    )

    if provider in ("openai-compatible", "openai", "ollama", "lmstudio"):
        provider = "openai-compatible"
        model = (
            os.environ.get("ACTGUARD_MODEL", "").strip() or DEFAULT_OPENAI_MODEL
        )
        base_url = (
            os.environ.get("ACTGUARD_BASE_URL", "").strip().rstrip("/")
            or "http://localhost:11434/v1"
        )
    else:
        provider = "mistral"
        model = (
            os.environ.get("ACTGUARD_MODEL", "").strip() or DEFAULT_MISTRAL_MODEL
        )
        base_url = ""

    return LLMSettings(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout_ms=timeout_ms,
        report_timeout_ms=report_timeout_ms,
    )


def llm_status_line() -> str:
    settings = llm_settings()
    if settings.provider == "mistral":
        key_ok = bool(settings.api_key and settings.api_key != "your_key_here")
        return (
            f"LLM: Mistral ({settings.model})"
            + (" — API key set" if key_ok else " — set MISTRAL_API_KEY in .env")
        )
    return (
        f"LLM: OpenAI-compatible ({settings.model}) @ {settings.base_url}"
    )
