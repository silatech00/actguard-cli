"""EU readiness scoring rules — deterministic deductions from scan state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

REGULATIONS = ("ai_act", "nis2", "dsa", "gdpr", "data_act")

BIOMETRIC_TERMS = ("biometric", "face", "fingerprint", "face_id")
HEALTH_TERMS = ("health", "diagnosis", "medical")
ART9_TERMS = (
    "ethnicity",
    "race",
    "religion",
    "political",
    "sexual_orientation",
    "criminal",
    "biometric",
    "genetic",
)
MIGRATION_TERMS = ("immigration", "asylum", "migration", "visa", "border control")


def _evidence_text(state: dict) -> str:
    return " ".join(state.get("sensitive_data", {}).get("evidence", [])).lower()


def _evidence_mentions(state: dict, terms: tuple[str, ...]) -> bool:
    text = _evidence_text(state)
    return any(term in text for term in terms)


def _slot_value(state: dict, key: str) -> bool:
    slot = state.get(key, {})
    if isinstance(slot, dict):
        return bool(slot.get("value"))
    return False


def _sensitive_evidence(state: dict) -> list[str]:
    return list(state.get("sensitive_data", {}).get("evidence", []))


def _signal_evidence(state: dict, key: str) -> list[str]:
    slot = state.get(key, {})
    if isinstance(slot, dict):
        return list(slot.get("evidence", []))
    return []


def _has_biometric(state: dict) -> bool:
    return _evidence_mentions(state, BIOMETRIC_TERMS)


def _has_credit_scoring(state: dict) -> bool:
    text = _evidence_text(state)
    return "credit_score" in text or "creditworthiness" in text


def _has_health_signals(state: dict) -> bool:
    return _evidence_mentions(state, HEALTH_TERMS)


def _has_art9_special_category(state: dict) -> bool:
    return _evidence_mentions(state, ART9_TERMS)


def _has_annex_iii_candidates(state: dict) -> bool:
    return bool(state.get("annex_iii_candidates"))


def _domain_text(state: dict) -> str:
    parts = list(state.get("domain_signals") or [])
    readme = (state.get("project_context") or {}).get("readme") or ""
    if readme:
        parts.append(readme)
    return " ".join(parts).lower()


def _migration_domain(state: dict) -> bool:
    text = _domain_text(state)
    return any(term in text for term in MIGRATION_TERMS)


@dataclass(frozen=True)
class ReadinessRule:
    id: str
    regulation: str
    severity_tier: str
    points: int
    cap_max_score: int | None
    llm_adjustable: bool
    llm_max_tier_reduction: int
    condition: Callable[[dict], bool]
    evidence_fn: Callable[[dict], list[str]]


RULES: list[ReadinessRule] = [
    ReadinessRule(
        id="biometric_data",
        regulation="ai_act",
        severity_tier="critical",
        points=40,
        cap_max_score=35,
        llm_adjustable=False,
        llm_max_tier_reduction=0,
        condition=lambda s: _slot_value(s, "sensitive_data")
        and _evidence_mentions(s, BIOMETRIC_TERMS),
        evidence_fn=_sensitive_evidence,
    ),
    ReadinessRule(
        id="credit_scoring",
        regulation="ai_act",
        severity_tier="critical",
        points=40,
        cap_max_score=35,
        llm_adjustable=False,
        llm_max_tier_reduction=0,
        condition=lambda s: _slot_value(s, "sensitive_data")
        and ("credit_score" in _evidence_text(s) or "creditworthiness" in _evidence_text(s)),
        evidence_fn=_sensitive_evidence,
    ),
    ReadinessRule(
        id="health_data_ai",
        regulation="ai_act",
        severity_tier="high",
        points=25,
        cap_max_score=55,
        llm_adjustable=True,
        llm_max_tier_reduction=1,
        condition=lambda s: _slot_value(s, "sensitive_data")
        and _evidence_mentions(s, HEALTH_TERMS)
        and _slot_value(s, "uses_ai"),
        evidence_fn=lambda s: _sensitive_evidence(s) + _signal_evidence(s, "uses_ai"),
    ),
    ReadinessRule(
        id="art9_special_category",
        regulation="gdpr",
        severity_tier="critical",
        points=35,
        cap_max_score=45,
        llm_adjustable=False,
        llm_max_tier_reduction=0,
        condition=lambda s: _slot_value(s, "sensitive_data") and _has_art9_special_category(s),
        evidence_fn=_sensitive_evidence,
    ),
    ReadinessRule(
        id="annex_iii_ai_system",
        regulation="ai_act",
        severity_tier="critical",
        points=35,
        cap_max_score=40,
        llm_adjustable=False,
        llm_max_tier_reduction=0,
        condition=lambda s: _slot_value(s, "uses_ai") and _has_annex_iii_candidates(s),
        evidence_fn=lambda s: [
            f"{c.get('category', '')} — {c.get('note', '')}"
            for c in (s.get("annex_iii_candidates") or [])
        ],
    ),
    ReadinessRule(
        id="migration_ai_system",
        regulation="ai_act",
        severity_tier="critical",
        points=40,
        cap_max_score=35,
        llm_adjustable=False,
        llm_max_tier_reduction=0,
        condition=lambda s: _slot_value(s, "uses_ai")
        and _migration_domain(s)
        and (_slot_value(s, "scores_people") or _slot_value(s, "sensitive_data")),
        evidence_fn=lambda s: (s.get("domain_signals") or [])[:6]
        + _signal_evidence(s, "scores_people"),
    ),
    ReadinessRule(
        id="ai_scores_people",
        regulation="ai_act",
        severity_tier="high",
        points=20,
        cap_max_score=55,
        llm_adjustable=True,
        llm_max_tier_reduction=1,
        condition=lambda s: _slot_value(s, "uses_ai")
        and _slot_value(s, "scores_people")
        and not _migration_domain(s),
        evidence_fn=lambda s: _signal_evidence(s, "scores_people"),
    ),
    ReadinessRule(
        id="sensitive_data_general",
        regulation="gdpr",
        severity_tier="high",
        points=20,
        cap_max_score=None,
        llm_adjustable=True,
        llm_max_tier_reduction=1,
        condition=lambda s: _slot_value(s, "sensitive_data")
        and not _has_art9_special_category(s)
        and not (
            _has_biometric(s)
            or _has_credit_scoring(s)
            or (_has_health_signals(s) and _slot_value(s, "uses_ai"))
        ),
        evidence_fn=_sensitive_evidence,
    ),
    ReadinessRule(
        id="high_risk_ai_no_governance",
        regulation="ai_act",
        severity_tier="high",
        points=15,
        cap_max_score=None,
        llm_adjustable=True,
        llm_max_tier_reduction=1,
        condition=lambda s: _slot_value(s, "high_risk_ai") and not _slot_value(s, "has_security"),
        evidence_fn=lambda s: _signal_evidence(s, "high_risk_ai"),
    ),
    ReadinessRule(
        id="ai_no_governance_signal",
        regulation="ai_act",
        severity_tier="medium",
        points=12,
        cap_max_score=None,
        llm_adjustable=True,
        llm_max_tier_reduction=1,
        condition=lambda s: _slot_value(s, "uses_ai")
        and not _slot_value(s, "high_risk_ai")
        and not _slot_value(s, "has_security"),
        evidence_fn=lambda s: _signal_evidence(s, "uses_ai"),
    ),
    ReadinessRule(
        id="platform_no_security",
        regulation="nis2",
        severity_tier="medium",
        points=10,
        cap_max_score=None,
        llm_adjustable=True,
        llm_max_tier_reduction=1,
        condition=lambda s: _slot_value(s, "is_platform")
        and not _slot_value(s, "has_security"),
        evidence_fn=lambda s: _signal_evidence(s, "is_platform"),
    ),
    ReadinessRule(
        id="platform_no_security_dsa",
        regulation="dsa",
        severity_tier="low",
        points=8,
        cap_max_score=None,
        llm_adjustable=True,
        llm_max_tier_reduction=1,
        condition=lambda s: _slot_value(s, "is_platform")
        and not _slot_value(s, "has_security"),
        evidence_fn=lambda s: _signal_evidence(s, "is_platform"),
    ),
    ReadinessRule(
        id="cloud_no_security",
        regulation="nis2",
        severity_tier="low",
        points=6,
        cap_max_score=None,
        llm_adjustable=True,
        llm_max_tier_reduction=1,
        condition=lambda s: _slot_value(s, "cloud_infra")
        and not _slot_value(s, "has_security"),
        evidence_fn=lambda s: _signal_evidence(s, "cloud_infra"),
    ),
]
