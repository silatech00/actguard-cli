"""Deterministic EU readiness score engine."""

from __future__ import annotations

from typing import Any, Callable

from readiness.review import review_triggered_rules
from readiness.rules import REGULATIONS, RULES, ReadinessRule


def _rule_summary(rule: ReadinessRule, evidence: list[str]) -> dict[str, Any]:
    return {
        "id": rule.id,
        "regulation": rule.regulation,
        "severity_tier": rule.severity_tier,
        "points": rule.points,
        "cap_max_score": rule.cap_max_score,
        "llm_adjustable": rule.llm_adjustable,
        "llm_max_tier_reduction": rule.llm_max_tier_reduction,
        "evidence": evidence,
    }


def _collect_triggered(state: dict) -> list[dict[str, Any]]:
    triggered: list[dict[str, Any]] = []
    for rule in RULES:
        if not rule.condition(state):
            continue
        evidence = rule.evidence_fn(state)
        summary = _rule_summary(rule, evidence)
        summary["effective_points"] = rule.points
        triggered.append(summary)
    return triggered


def _applicable_regulations(state: dict | None) -> tuple[str, ...]:
    """Average only regulations that plausibly apply — avoids inflating score via irrelevant regs."""
    if not state:
        return REGULATIONS
    applicable: list[str] = []
    if _slot_value(state, "uses_ai") or state.get("annex_iii_candidates"):
        applicable.append("ai_act")
    if _slot_value(state, "is_platform") or _slot_value(state, "sensitive_data"):
        applicable.append("gdpr")
    if _slot_value(state, "is_platform") or _slot_value(state, "cloud_infra"):
        applicable.append("nis2")
    if _slot_value(state, "is_platform"):
        applicable.append("dsa")
    if _slot_value(state, "cloud_infra"):
        applicable.append("data_act")
    return tuple(applicable) if applicable else REGULATIONS


def _slot_value(state: dict, key: str) -> bool:
    slot = state.get(key, {})
    if isinstance(slot, dict):
        return bool(slot.get("value"))
    return False


def _aggregate_scores(
    triggered: list[dict[str, Any]],
    *,
    active_regulations: tuple[str, ...] | None = None,
) -> tuple[dict[str, int], int]:
    regs = active_regulations or REGULATIONS
    sub_scores = {reg: 100 for reg in REGULATIONS}
    for item in triggered:
        points = item.get("effective_points", item["points"])
        regulation = item["regulation"]
        if regulation == "general":
            for reg in REGULATIONS:
                sub_scores[reg] -= points
        else:
            sub_scores[regulation] -= points

    for reg in REGULATIONS:
        sub_scores[reg] = max(0, min(100, sub_scores[reg]))

    for item in triggered:
        cap = item.get("cap_max_score")
        if cap is not None:
            reg = item["regulation"]
            if reg == "general":
                for r in REGULATIONS:
                    sub_scores[r] = min(sub_scores[r], cap)
            else:
                sub_scores[reg] = min(sub_scores[reg], cap)

    active_scores = [sub_scores[reg] for reg in regs]
    overall = round(sum(active_scores) / len(active_scores))
    return sub_scores, overall


def compute_raw_score(state: dict) -> dict[str, Any]:
    triggered = _collect_triggered(state)
    active = _applicable_regulations(state)
    sub_scores, overall = _aggregate_scores(triggered, active_regulations=active)
    return {
        "overall": overall,
        "sub_scores": sub_scores,
        "triggered_rules": triggered,
        "active_regulations": list(active),
    }


# Each severity tier step halves the point deduction (documented mapping).
def _points_after_tier_reduction(base_points: int, tier_reduction: int) -> int:
    adjusted = base_points
    for _ in range(tier_reduction):
        adjusted = max(0, adjusted // 2)
    return adjusted


def apply_review(raw_result: dict, review: list[dict]) -> dict[str, Any]:
    review_by_id = {item["rule_id"]: item for item in review}
    adjusted_rules: list[dict[str, Any]] = []
    adjustments: list[dict[str, Any]] = []

    for rule_data in raw_result["triggered_rules"]:
        rule_id = rule_data["id"]
        review_item = review_by_id.get(rule_id, {})
        verdict = review_item.get("verdict", "confirmed")
        reasoning = review_item.get("reasoning", "")
        suggested_reduction = int(review_item.get("suggested_tier_reduction", 0) or 0)
        base_points = rule_data["points"]
        effective_points = base_points
        change_note = "No adjustment applied."

        if not rule_data["llm_adjustable"]:
            if verdict == "reduce_severity":
                # Non-adjustable rules may not request tier reductions.
                verdict = "confirmed"
            if verdict == "likely_false_positive":
                change_note = (
                    "AI flagged this as worth double-checking; "
                    "score deduction and cap unchanged (non-adjustable rule)."
                )
            adjustments.append(
                {
                    "rule_id": rule_id,
                    "verdict": verdict,
                    "reasoning": reasoning,
                    "original_points": base_points,
                    "effective_points": base_points,
                    "note": change_note,
                }
            )
            adjusted = dict(rule_data)
            adjusted["effective_points"] = base_points
            adjusted_rules.append(adjusted)
            continue

        if verdict == "likely_false_positive":
            effective_points = 0
            change_note = "False positive — points waived for adjustable rule."
        elif verdict == "reduce_severity":
            clamped = min(suggested_reduction, rule_data["llm_max_tier_reduction"])
            effective_points = _points_after_tier_reduction(base_points, clamped)
            change_note = (
                f"Severity reduced by {clamped} tier(s); "
                f"points {base_points} → {effective_points}."
            )
        else:
            change_note = "Rule confirmed at full severity."

        adjustments.append(
            {
                "rule_id": rule_id,
                "verdict": verdict,
                "reasoning": reasoning,
                "original_points": base_points,
                "effective_points": effective_points,
                "note": change_note,
            }
        )
        adjusted = dict(rule_data)
        adjusted["effective_points"] = effective_points
        adjusted_rules.append(adjusted)

    final_sub_scores, final_overall = _aggregate_scores(
        adjusted_rules,
        active_regulations=tuple(raw_result.get("active_regulations") or REGULATIONS),
    )
    return {
        "final_overall": final_overall,
        "final_sub_scores": final_sub_scores,
        "adjustments": adjustments,
        "adjusted_triggered_rules": adjusted_rules,
    }


def compute_readiness_score(
    state: dict,
    synthesis: dict | None,
    *,
    progress_callback: Callable[[str], None] | None = None,
    skip_review: bool = False,
) -> dict[str, Any]:
    raw = compute_raw_score(state)
    if skip_review or not raw["triggered_rules"]:
        review: list[dict] = []
        final_sub, final_overall = _aggregate_scores(
            raw["triggered_rules"],
            active_regulations=tuple(raw.get("active_regulations") or REGULATIONS),
        )
        final = {
            "final_overall": final_overall,
            "final_sub_scores": final_sub,
            "adjustments": [],
            "adjusted_triggered_rules": raw["triggered_rules"],
        }
    else:
        review = review_triggered_rules(
            raw["triggered_rules"], state, synthesis, progress_callback=progress_callback
        )
        final = apply_review(raw, review)

    return {
        "raw_overall": raw["overall"],
        "raw_sub_scores": raw["sub_scores"],
        "final_overall": final["final_overall"],
        "final_sub_scores": final["final_sub_scores"],
        "active_regulations": raw.get("active_regulations", list(REGULATIONS)),
        "triggered_rules": raw["triggered_rules"],
        "adjusted_triggered_rules": final["adjusted_triggered_rules"],
        "review": review,
        "adjustments": final["adjustments"],
    }


if __name__ == "__main__":
    clean_state = {
        "uses_ai": {"value": False, "evidence": []},
        "high_risk_ai": {"value": False, "evidence": []},
        "is_platform": {"value": False, "evidence": []},
        "has_security": {"value": False, "evidence": []},
        "cloud_infra": {"value": False, "evidence": []},
        "sensitive_data": {"value": False, "evidence": []},
    }
    biometric_state = {
        **clean_state,
        "sensitive_data": {
            "value": True,
            "evidence": [
                "Biometric data — models/user.py: `biometric_hash = ...`"
            ],
        },
    }
    health_ai_state = {
        **clean_state,
        "uses_ai": {"value": True, "evidence": ["openai (LLM API) — requirements.txt"]},
        "sensitive_data": {
            "value": True,
            "evidence": [
                "Health data — api/routes.py: `health_check_endpoint = '/health'`"
            ],
        },
    }

    for label, fixture in [
        ("clean", clean_state),
        ("biometric", biometric_state),
        ("health_ai", health_ai_state),
    ]:
        result = compute_readiness_score(fixture, None, skip_review=True)
        print(f"\n=== {label} ===")
        print(f"raw overall: {result['raw_overall']}")
        print(f"sub_scores: {result['raw_sub_scores']}")
        print(f"triggered: {[r['id'] for r in result['triggered_rules']]}")
