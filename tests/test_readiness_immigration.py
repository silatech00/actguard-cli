"""Readiness scoring for high-risk immigration / eligibility AI fixtures."""

from __future__ import annotations

from readiness.engine import compute_raw_score


def _immigration_state() -> dict:
    return {
        "uses_ai": {"value": True, "evidence": ["openai (OpenAI API) — requirements.txt"]},
        "high_risk_ai": {"value": True, "evidence": ["Annex III(6) - Law enforcement (trigger: criminal)"]},
        "is_platform": {"value": True, "evidence": ["streamlit (Streamlit web app) — app.py"]},
        "has_security": {"value": False, "evidence": []},
        "cloud_infra": {"value": False, "evidence": []},
        "scores_people": {
            "value": True,
            "evidence": ["numeric scoring of individuals — scan:167: `visa_eligibility_score`"],
        },
        "sensitive_data": {
            "value": True,
            "evidence": [
                "Racial/ethnic origin (GDPR Art. 9) — schema.sql:8: `ethnicity TEXT,`",
                "Criminal record data (GDPR Art. 10) — schema.sql:9: `criminal_record TEXT,`",
                "Government ID document — schema.sql:6: `passport_number TEXT,`",
            ],
        },
        "domain_signals": [
            "Migration / immigration domain — README.md:3: `immigration law`",
            "Automated eligibility scoring — app.py:167: `check_eligibility`",
        ],
        "project_context": {
            "readme": "Immigration Law AI — automated visa eligibility scoring",
        },
        "annex_iii_candidates": [
            {
                "category": "Possible Annex III(1) - if used for categorisation",
                "article": "Annex III(1)",
                "note": "ethnicity categorisation",
                "trigger": "ethnicity",
            },
            {
                "category": "Annex III(6) - Law enforcement",
                "article": "Annex III(6)",
                "note": "criminal data",
                "trigger": "criminal",
            },
        ],
    }


def test_immigration_fixture_scores_below_70():
    result = compute_raw_score(_immigration_state())
    assert result["overall"] < 70
    assert result["sub_scores"]["gdpr"] <= 45
    assert result["sub_scores"]["ai_act"] <= 40
    assert "art9_special_category" in [r["id"] for r in result["triggered_rules"]]
    assert "migration_ai_system" in [r["id"] for r in result["triggered_rules"]]
    assert "data_act" not in result["active_regulations"]


def test_derived_signals_from_build_state(tmp_path):
    from eu_compliance import build_state, scan_project_context, scan_repo, scan_sensitive_fields

    repo = tmp_path / "visa-app"
    repo.mkdir()
    (repo / "README.md").write_text(
        "# Immigration visa bot\nAutomated visa eligibility scoring with AI.\n",
        encoding="utf-8",
    )
    (repo / "app.py").write_text(
        "import streamlit as st\n"
        "def check_eligibility(profile):\n"
        "    return profile.visa_eligibility_score\n",
        encoding="utf-8",
    )
    (repo / "requirements.txt").write_text("openai\nstreamlit\n", encoding="utf-8")
    (repo / "schema.sql").write_text(
        "CREATE TABLE users (ethnicity TEXT, criminal_record TEXT, passport_number TEXT);\n",
        encoding="utf-8",
    )

    context = scan_project_context(str(repo))
    evidence, snippets = scan_repo(str(repo))
    sensitive = scan_sensitive_fields(str(repo))
    state = build_state(evidence, snippets, sensitive, context)

    assert state["scores_people"]["value"] is True
    assert state["high_risk_ai"]["value"] is True
    assert state["annex_iii_candidates"]
    assert any("immigration" in s.lower() or "eligibility" in s.lower() for s in state["domain_signals"])

    score = compute_raw_score(state)
    assert score["overall"] < 75
