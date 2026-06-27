"""Deterministic founder extras: sub-processors, data flows, timelines, etc."""

from __future__ import annotations

import json

from deploy.gates import build_launch_gates

VENDOR_REGISTRY: dict[str, dict[str, str]] = {
    "openai": {"name": "OpenAI", "purpose": "AI inference / embeddings", "dpa_needed": "yes", "region_note": "US — SCCs typically required"},
    "anthropic": {"name": "Anthropic", "purpose": "AI inference", "dpa_needed": "yes", "region_note": "US — SCCs typically required"},
    "mistralai": {"name": "Mistral AI", "purpose": "AI inference", "dpa_needed": "yes", "region_note": "EU company — check processing region"},
    "stripe": {"name": "Stripe", "purpose": "Payment processing", "dpa_needed": "yes", "region_note": "US/EU — DPA available"},
    "sendgrid": {"name": "SendGrid", "purpose": "Transactional email", "dpa_needed": "yes", "region_note": "US — SCCs typically required"},
    "resend": {"name": "Resend", "purpose": "Transactional email", "dpa_needed": "yes", "region_note": "US — check DPA"},
    "boto3": {"name": "Amazon Web Services", "purpose": "Cloud infrastructure", "dpa_needed": "yes", "region_note": "Pin to EU region"},
    "google_cloud": {"name": "Google Cloud", "purpose": "Cloud infrastructure", "dpa_needed": "yes", "region_note": "Pin to EU region"},
    "azure": {"name": "Microsoft Azure", "purpose": "Cloud infrastructure", "dpa_needed": "yes", "region_note": "Pin to EU region"},
    "supabase": {"name": "Supabase", "purpose": "Database / auth", "dpa_needed": "yes", "region_note": "Select EU project region"},
    "posthog": {"name": "PostHog", "purpose": "Product analytics", "dpa_needed": "yes", "region_note": "EU cloud option available — consent required"},
    "mixpanel": {"name": "Mixpanel", "purpose": "Product analytics", "dpa_needed": "yes", "region_note": "US — consent banner required"},
    "segment": {"name": "Segment", "purpose": "Analytics pipeline", "dpa_needed": "yes", "region_note": "US — consent banner required"},
}

AI_ACT_MILESTONES = [
    {"date": "2025-02-02", "label": "Prohibited AI practices apply", "applies_when": "always_if_ai"},
    {"date": "2025-08-02", "label": "GPAI model obligations apply", "applies_when": "gpai_provider"},
    {"date": "2026-08-02", "label": "High-risk AI system requirements (Annex III)", "applies_when": "high_risk"},
    {"date": "2027-08-02", "label": "High-risk AI embedded in regulated products", "applies_when": "high_risk_embedded"},
]


def _build_subprocessors(deploy_profile: dict) -> list[dict]:
    vendors = deploy_profile.get("detected_vendors") or []
    rows = []
    for v in vendors:
        meta = VENDOR_REGISTRY.get(v, {
            "name": v,
            "purpose": "Third-party service detected in dependencies",
            "dpa_needed": "review",
            "region_note": "Verify processing location and DPA",
        })
        rows.append({"id": v, **meta})
    return rows


def _build_data_flows(deploy_profile: dict, hosting_shortlist: dict) -> list[dict]:
    primary = (hosting_shortlist or {}).get("primary") or {}
    host_name = primary.get("name", "EU application host")
    host_region = primary.get("region", "EU")
    flows = [
        {"from": "EU user", "to": host_name, "data": "HTTP requests / personal data", "jurisdiction": "EU"},
        {"from": host_name, "to": f"{host_name} ({host_region})", "data": "Application processing", "jurisdiction": "EU"},
    ]
    if deploy_profile.get("persistence"):
        flows.append({
            "from": host_name,
            "to": "Database (co-located EU)",
            "data": "Stored user data",
            "jurisdiction": "EU",
        })
    for vendor in deploy_profile.get("detected_vendors") or []:
        meta = VENDOR_REGISTRY.get(vendor, {})
        flows.append({
            "from": host_name,
            "to": meta.get("name", vendor),
            "data": meta.get("purpose", "API calls"),
            "jurisdiction": meta.get("region_note", "Review"),
        })
    return flows


def _build_ai_act_timeline(state: dict) -> list[dict]:
    uses_ai = state.get("uses_ai", {}).get("value", False)
    high_risk = state.get("high_risk_ai", {}).get("value", False)
    annex = state.get("annex_iii_candidates") or []
    if not uses_ai:
        return [{"date": "", "label": "No AI detected — AI Act timeline not applicable", "status": "not_applicable"}]

    timeline = []
    for m in AI_ACT_MILESTONES:
        applies = False
        when = m["applies_when"]
        if when == "always_if_ai":
            applies = True
        elif when == "high_risk":
            applies = high_risk or bool(annex)
        elif when == "gpai_provider":
            applies = False  # rare for startups
        elif when == "high_risk_embedded":
            applies = high_risk
        timeline.append({
            "date": m["date"],
            "label": m["label"],
            "status": "applies" if applies else "monitor",
        })
    return timeline


def _build_cookie_spec(deploy_profile: dict) -> dict | None:
    analytics = deploy_profile.get("analytics_libs") or []
    if not analytics:
        return None
    return {
        "consent_required": True,
        "detected_tools": analytics,
        "recommendations": [
            "Block analytics scripts until explicit consent",
            "Offer Accept / Reject / Customize categories",
            "Document tools in privacy policy sub-processor list",
            "Prefer EU-hosted analytics (e.g. PostHog EU) when possible",
        ],
    }


def _build_microcopy(state: dict) -> dict:
    synthesis = state.get("deep_synthesis") or {}
    product = synthesis.get("product_summary") or synthesis.get("product_description") or "this service"
    uses_ai = state.get("uses_ai", {}).get("value", False)
    copy = {
        "privacy_footer": "Privacy Policy | Contact",
        "data_one_liner": f"We process personal data to provide {product[:80]}. See our Privacy Policy for details.",
    }
    if uses_ai:
        copy["ai_disclosure"] = "This content was generated with AI assistance. It may contain errors — verify important information."
        copy["ai_badge"] = "AI-generated"
    return copy


def _build_investor_summary(state: dict, readiness: dict | None, hosting_shortlist: dict | None) -> dict:
    synthesis = state.get("deep_synthesis") or {}
    readiness = readiness or {}
    primary = (hosting_shortlist or {}).get("primary") or {}
    triggered = readiness.get("triggered_rules") or []
    top_gaps = [
        f"{r.get('id', 'rule')}: {r.get('severity_tier', '')} ({r.get('regulation', '')})"
        for r in triggered[:5]
    ]
    return {
        "product_summary": synthesis.get("product_summary", ""),
        "readiness_score": readiness.get("final_overall", readiness.get("final_score")),
        "sub_scores": readiness.get("sub_scores", {}),
        "recommended_hosting": primary.get("name", ""),
        "hosting_region": primary.get("region", ""),
        "top_gaps": top_gaps or ["No critical rules triggered"],
        "disclaimer": "Automated self-assessment — not legal advice or certification.",
    }


def _build_security_qa(state: dict, deploy_profile: dict) -> list[dict]:
    ctx = state.get("project_context", {})
    return [
        {
            "question": "Where is application data stored?",
            "answer": f"Planned EU region ({deploy_profile.get('existing_deploy_hints', ['TBD'])[0] if deploy_profile.get('existing_deploy_hints') else 'select EU host'})",
            "confidence": "medium",
        },
        {
            "question": "Do you use subprocessors?",
            "answer": f"Yes — detected: {', '.join(deploy_profile.get('detected_vendors') or []) or 'none in scan'}",
            "confidence": "high" if deploy_profile.get("detected_vendors") else "low",
        },
        {
            "question": "Is AI used in the product?",
            "answer": "Yes" if state.get("uses_ai", {}).get("value") else "No",
            "confidence": "high",
        },
        {
            "question": "Encryption in transit?",
            "answer": "HTTPS/TLS assumed for production deployment",
            "confidence": "medium",
        },
        {
            "question": "Security libraries detected?",
            "answer": "Yes" if state.get("has_security", {}).get("value") else "No — review authentication and secrets handling",
            "confidence": "high",
        },
        {
            "question": "Incident notification process?",
            "answer": "Not detected in codebase — document before enterprise sales",
            "confidence": "low",
        },
    ]


def build_founder_extras(
    state: dict,
    deploy_profile: dict | None,
    hosting_shortlist: dict | None,
    readiness: dict | None = None,
) -> dict:
    """Build structured founder extras (deterministic, no LLM)."""
    profile = deploy_profile or state.get("deploy_profile") or {}
    hosting = hosting_shortlist or {}

    data_flows = _build_data_flows(profile, hosting)
    mermaid_lines = ["flowchart LR"]
    for i, flow in enumerate(data_flows[:6]):
        src = flow["from"].replace(" ", "_")
        dst = flow["to"].replace(" ", "_").replace("(", "").replace(")", "")
        mermaid_lines.append(f'  {src} -->|{flow["data"][:30]}| {dst}')

    return {
        "subprocessors": _build_subprocessors(profile),
        "data_flows": data_flows,
        "data_flow_mermaid": "\n".join(mermaid_lines),
        "launch_gates": build_launch_gates(profile, hosting, readiness),
        "ai_act_timeline": _build_ai_act_timeline(state),
        "cookie_spec": _build_cookie_spec(profile),
        "microcopy": _build_microcopy(state),
        "investor_summary": _build_investor_summary(state, readiness, hosting),
        "security_qa": _build_security_qa(state, profile),
        "hosting": hosting,
        "deploy_profile": profile,
    }


def founder_extras_to_json(extras: dict) -> dict:
    """Ensure extras are JSON-serializable for artifacts_json."""
    return json.loads(json.dumps(extras, default=str))
