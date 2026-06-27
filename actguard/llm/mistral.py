"""Mistral API provider."""

from __future__ import annotations

from actguard.llm.config import LLMSettings


def mistral_complete(
    settings: LLMSettings,
    messages: list[dict],
    *,
    response_format: dict | None = None,
    timeout_ms: int | None = None,
) -> str:
    try:
        import httpx
        from mistralai.client import Mistral
    except ImportError as exc:
        raise ImportError(
            "mistralai not installed. Run: pip install -r requirements.txt"
        ) from exc

    if not settings.api_key:
        raise ValueError(
            "MISTRAL_API_KEY not found. Set MISTRAL_API_KEY or ACTGUARD_API_KEY in .env"
        )

    effective_timeout_ms = timeout_ms or settings.timeout_ms
    read_seconds = max(effective_timeout_ms / 1000.0, 60.0)
    http_client = httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(read_seconds, connect=30.0),
    )
    with Mistral(
        api_key=settings.api_key,
        client=http_client,
        timeout_ms=effective_timeout_ms,
    ) as client:
        kwargs: dict = {
            "model": settings.model,
            "messages": messages,
            "timeout_ms": effective_timeout_ms,
        }
        if response_format:
            kwargs["response_format"] = response_format
        response = client.chat.complete(**kwargs)
    content = response.choices[0].message.content
    return str(content) if content is not None else ""
