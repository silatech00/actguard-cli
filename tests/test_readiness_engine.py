"""Tests for deterministic readiness scoring."""

from __future__ import annotations

from readiness.engine import apply_review, compute_raw_score, compute_readiness_score


def _base_state() -> dict:
    return {
        "uses_ai": {"value": False, "evidence": []},
        "high_risk_ai": {"value": False, "evidence": []},
        "is_platform": {"value": False, "evidence": []},
        "has_security": {"value": False, "evidence": []},
        "cloud_infra": {"value": False, "evidence": []},
        "sensitive_data": {"value": False, "evidence": []},
    }


def test_clean_project_scores_100():
    result = compute_raw_score(_base_state())
    assert result["overall"] == 100
    assert all(score == 100 for score in result["sub_scores"].values())
    assert result["triggered_rules"] == []


def test_biometric_scores_low_on_ai_act():
    state = {
        **_base_state(),
        "sensitive_data": {
            "value": True,
            "evidence": ["Biometric data — user.py: `biometric_hash`"],
        },
    }
    result = compute_raw_score(state)
    assert result["sub_scores"]["ai_act"] <= 35
    assert result["overall"] < 100
    assert any(r["id"] == "biometric_data" for r in result["triggered_rules"])


def test_biometric_hard_cap_survives_review():
    state = {
        **_base_state(),
        "sensitive_data": {
            "value": True,
            "evidence": ["Biometric data — user.py: `face_id_token`"],
        },
    }
    raw = compute_raw_score(state)
    review = [
        {
            "rule_id": "biometric_data",
            "verdict": "reduce_severity",
            "reasoning": "Sympathetic but should be ignored.",
            "suggested_tier_reduction": 2,
        }
    ]
    final = apply_review(raw, review)
    assert final["final_sub_scores"]["ai_act"] <= 35
    assert final["final_overall"] == raw["overall"]


def test_health_false_positive_can_waive_adjustable_rule():
    state = {
        **_base_state(),
        "uses_ai": {"value": True, "evidence": ["openai — requirements.txt"]},
        "sensitive_data": {
            "value": True,
            "evidence": [
                "Health data — routes.py: `health_check_endpoint = '/health'`"
            ],
        },
    }
    raw = compute_raw_score(state)
    assert any(r["id"] == "health_data_ai" for r in raw["triggered_rules"])
    review = [
        {
            "rule_id": "health_data_ai",
            "verdict": "likely_false_positive",
            "reasoning": "health_check_endpoint is monitoring, not patient data.",
            "suggested_tier_reduction": 0,
        }
    ]
    final = apply_review(raw, review)
    health_adj = next(
        a for a in final["adjustments"] if a["rule_id"] == "health_data_ai"
    )
    assert health_adj["verdict"] == "likely_false_positive"
    assert health_adj["effective_points"] == 0

    # Because this rule has a cap_max_score, the LLM cannot silently restore the
    # full AI Act sub-score past the cap.
    assert final["final_sub_scores"]["ai_act"] == raw["sub_scores"]["ai_act"]
    assert final["final_overall"] == raw["overall"]


def test_compute_readiness_score_skip_review():
    result = compute_readiness_score(_base_state(), None, skip_review=True)
    assert result["raw_overall"] == 100
    assert result["final_overall"] == 100
    assert result["review"] == []
