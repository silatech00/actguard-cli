"""Pluggable LLM providers for ActGuard."""

from __future__ import annotations

import time

from actguard.llm.config import LLMSettings, llm_settings, llm_status_line
from actguard.llm.mistral import mistral_complete
from actguard.llm.openai_compatible import openai_compatible_complete

__all__ = ["complete", "llm_settings", "llm_status_line", "LLMSettings"]


def _is_auth_error(exc: Exception, provider: str) -> bool:
    err = str(exc).lower()
    if "401" in err or "unauthorized" in err:
        return True
    if provider == "mistral" and "mistral" in err:
        return True
    return False


def _auth_error_message(settings: LLMSettings) -> str:
    if settings.provider == "mistral":
        return (
            "Mistral API rejected the API key (401 Unauthorized). "
            "Set a valid MISTRAL_API_KEY in ACTGUARD/.env"
        )
    return (
        f"API rejected the key (401). Check ACTGUARD_API_KEY and {settings.base_url}"
    )


def complete(
    messages: list[dict],
    *,
    response_format: dict | None = None,
    timeout_ms: int | None = None,
    label: str = "LLM",
    max_retries: int = 3,
    settings: LLMSettings | None = None,
) -> str:
    """Call configured LLM provider with retry on timeouts and rate limits."""
    cfg = settings or llm_settings()
    effective_timeout = timeout_ms or cfg.timeout_ms
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            if cfg.provider == "openai-compatible":
                return openai_compatible_complete(
                    cfg,
                    messages,
                    response_format=response_format,
                    timeout_ms=effective_timeout,
                )
            return mistral_complete(
                cfg,
                messages,
                response_format=response_format,
                timeout_ms=effective_timeout,
            )
        except Exception as exc:
            last_exc = exc
            err = str(exc).lower()
            is_timeout = "timeout" in err or "timed out" in err
            is_rate_limit = (
                "429" in err
                or "rate limit" in err
                or "rate_limited" in err
                or "rate_limit" in err
            )
            if (is_timeout or is_rate_limit) and attempt < max_retries:
                wait = (5 * (2 ** attempt)) if is_rate_limit else (2 ** attempt)
                reason = "rate limit" if is_rate_limit else "timeout"
                print(f"      {label} {reason}, retrying in {wait}s…")
                time.sleep(wait)
                continue
            if _is_auth_error(exc, cfg.provider):
                raise ValueError(_auth_error_message(cfg)) from exc
            raise

    if last_exc:
        raise last_exc
    return ""
