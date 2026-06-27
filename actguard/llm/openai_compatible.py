"""OpenAI-compatible chat API (Ollama, LM Studio, etc.)."""

from __future__ import annotations

import httpx

from actguard.llm.config import LLMSettings


def openai_compatible_complete(
    settings: LLMSettings,
    messages: list[dict],
    *,
    response_format: dict | None = None,
    timeout_ms: int | None = None,
) -> str:
    effective_timeout_ms = timeout_ms or settings.timeout_ms
    read_seconds = max(effective_timeout_ms / 1000.0, 120.0)
    base = settings.base_url.rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    url = f"{base}/chat/completions"

    payload: dict = {
        "model": settings.model,
        "messages": messages,
        "stream": False,
    }
    if response_format:
        payload["response_format"] = response_format

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if settings.api_key:
        headers["Authorization"] = f"Bearer {settings.api_key}"

    with httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(read_seconds, connect=30.0),
    ) as client:
        response = client.post(url, json=payload, headers=headers)
        if response.status_code == 401:
            raise ValueError(
                f"API rejected the key (401). Check ACTGUARD_API_KEY for {settings.base_url}"
            )
        response.raise_for_status()
        data = response.json()

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"Empty response from {url}")
    message = choices[0].get("message") or {}
    content = message.get("content", "")
    return str(content) if content is not None else ""
