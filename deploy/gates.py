"""Launch gate definitions from readiness and deploy profile."""

from __future__ import annotations


def _check_status(passed: bool, warn: bool = False) -> str:
    if passed:
        return "pass"
    if warn:
        return "warn"
    return "fail"


def build_launch_gates(
    deploy_profile: dict | None,
    hosting_shortlist: dict | None,
    readiness: dict | None = None,
) -> list[dict]:
    """Build phased launch gates from deploy + readiness signals."""
    profile = deploy_profile or {}
    hosting = hosting_shortlist or {}
    readiness = readiness or {}
    sub_scores = readiness.get("sub_scores") or {}
    final_score = readiness.get("final_overall", readiness.get("final_score", 100))
    warnings = hosting.get("warnings") or []
    primary = hosting.get("primary") or {}
    tier = primary.get("residency_tier", 3)

    has_security = True
    triggered = readiness.get("triggered_rules") or []
    security_rules = [r for r in triggered if r.get("regulation") in ("nis2", "gdpr")]
    gdpr_score = sub_scores.get("gdpr", 100)

    gates = []

    # Gate: friends & family
    dev_checks = [
        {
            "id": "stack_detected",
            "label": "Stack fingerprint detected",
            "status": _check_status(profile.get("confidence") != "low", warn=True),
        },
        {
            "id": "hosting_plan",
            "label": "EU hosting recommendation available",
            "status": _check_status(bool(primary)),
        },
    ]
    gates.append({
        "id": "dev_preview",
        "label": "Safe to show friends",
        "passed": all(c["status"] == "pass" for c in dev_checks),
        "checks": dev_checks,
    })

    # Gate: public beta
    beta_checks = [
        {
            "id": "db_eu",
            "label": "Database planned in EU region",
            "status": _check_status(
                tier == 1 or not profile.get("persistence"),
                warn=tier == 3 and bool(profile.get("persistence")),
            ),
        },
        {
            "id": "residency_tier",
            "label": "Primary host is EU-native or EU-region pinned",
            "status": _check_status(tier <= 2, warn=tier == 3),
        },
        {
            "id": "gdpr_baseline",
            "label": "GDPR readiness sub-score ≥ 70",
            "status": _check_status(gdpr_score >= 70, warn=gdpr_score >= 50),
        },
        {
            "id": "no_deploy_warnings",
            "label": "No critical deploy region warnings",
            "status": _check_status(len(warnings) == 0, warn=len(warnings) <= 2),
        },
    ]
    gates.append({
        "id": "public_beta",
        "label": "Safe for public beta",
        "passed": all(c["status"] == "pass" for c in beta_checks),
        "checks": beta_checks,
    })

    # Gate: paid customers
    paid_checks = [
        {
            "id": "overall_readiness",
            "label": "Overall readiness score ≥ 65",
            "status": _check_status(final_score >= 65, warn=final_score >= 50),
        },
        {
            "id": "security_posture",
            "label": "No open critical security/compliance rules",
            "status": _check_status(
                not any(r.get("severity_tier") == "critical" for r in triggered),
                warn=bool(security_rules),
            ),
        },
        {
            "id": "subprocessors",
            "label": "Sub-processor list drafted",
            "status": _check_status(bool(profile.get("detected_vendors"))),
        },
    ]
    gates.append({
        "id": "paid_launch",
        "label": "Safe to charge money",
        "passed": all(c["status"] == "pass" for c in paid_checks),
        "checks": paid_checks,
    })

    # Gate: enterprise
    ent_checks = [
        {
            "id": "readiness_80",
            "label": "Overall readiness score ≥ 80",
            "status": _check_status(final_score >= 80, warn=final_score >= 65),
        },
        {
            "id": "eu_residency",
            "label": "EU-native hosting (tier 1) or documented transfer safeguards",
            "status": _check_status(tier == 1, warn=tier == 2),
        },
    ]
    gates.append({
        "id": "enterprise_pilot",
        "label": "Safe for enterprise pilot",
        "passed": all(c["status"] == "pass" for c in ent_checks),
        "checks": ent_checks,
    })

    return gates
