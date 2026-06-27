"""Hybrid LLM review layer for readiness rules."""

from __future__ import annotations

import json
from typing import Callable

from eu_compliance import _mistral_complete, _parse_json_response


def _synthesis_context(synthesis: dict | None) -> str:
    if not synthesis:
        return ""
    parts: list[str] = []
    for key in ("product_description", "ai_features", "summary"):
        value = synthesis.get(key)
        if value:
            parts.append(f"{key}: {value}")
    return "\n".join(parts)


def _review_single_rule(
    rule: dict,
    state: dict,
    synthesis: dict | None,
) -> dict:
    evidence = rule.get("evidence") or []
    evidence_block = "\n".join(f"- {e}" for e in evidence[:8]) or "(none)"
    context_block = _synthesis_context(synthesis) or "(no synthesis available)"
    adjustable = rule.get("llm_adjustable", False)
    adjustability = (
        "ADJUSTABLE — you may return reduce_severity with suggested_tier_reduction "
        f"up to {rule.get('llm_max_tier_reduction', 0)}."
        if adjustable
        else (
            "NOT ADJUSTABLE — you may only return verdict 'confirmed' or "
            "'likely_false_positive' (for human review). You may NOT request a "
            "severity reduction regardless of how the evidence reads. If you "
            "believe a reduction would be warranted, state that limitation "
            "explicitly in your reasoning but do not request one."
        )
    )

    prompt = f"""You are reviewing an automated EU readiness rule trigger for false positives.

Rule id: {rule['id']}
Regulation: {rule['regulation']}
Severity tier: {rule['severity_tier']}
Point deduction if confirmed: {rule['points']}
Cap max score: {rule.get('cap_max_score')}
Adjustability: {adjustability}

Evidence that triggered this rule:
{evidence_block}

Project context from deep analysis:
{context_block}

Return ONLY valid JSON with these keys:
- "verdict": "confirmed" | "likely_false_positive" | "reduce_severity"
- "reasoning": one or two sentences explaining why, referencing the specific evidence
- "suggested_tier_reduction": 0, 1, or 2 (only meaningful if ADJUSTABLE and verdict is reduce_severity)
"""

    messages = [
        {
            "role": "system",
            "content": (
                "You are a precise compliance analyst. Ground every claim in the "
                "provided evidence strings. Do not invent file paths or data types."
            ),
        },
        {"role": "user", "content": prompt},
    ]
    try:
        raw = _mistral_complete(
            messages,
            response_format={"type": "json_object"},
            label=f"readiness review {rule['id']}",
        )
        parsed = _parse_json_response(raw)
    except Exception as exc:
        parsed = {
            "verdict": "confirmed",
            "reasoning": f"Review unavailable ({exc}); defaulting to confirmed.",
            "suggested_tier_reduction": 0,
        }

    verdict = parsed.get("verdict", "confirmed")
    if verdict not in ("confirmed", "likely_false_positive", "reduce_severity"):
        verdict = "confirmed"

    return {
        "rule_id": rule["id"],
        "verdict": verdict,
        "reasoning": str(parsed.get("reasoning", "")).strip(),
        "suggested_tier_reduction": int(parsed.get("suggested_tier_reduction", 0) or 0),
    }


def review_triggered_rules(
    triggered_rules: list[dict],
    state: dict,
    synthesis: dict | None,
    *,
    progress_callback: Callable[[str], None] | None = None,
) -> list[dict]:
    results: list[dict] = []
    total = len(triggered_rules)
    for i, rule in enumerate(triggered_rules, start=1):
        if progress_callback:
            progress_callback(f"Reviewing readiness rule {i}/{total}: {rule['id']}…")
        results.append(_review_single_rule(rule, state, synthesis))
    return results
