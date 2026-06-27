"""Generate full compliance plan bundle (markdown only)."""

from __future__ import annotations

from actguard.services.report_service import (
    build_founder_extras_artifact,
    generate_implementation_for_lang,
    generate_report_for_lang,
    generate_rollout_for_lang,
    serialize_artifacts,
)
from deploy.matcher import match_hosting_providers
from legal_rag.retrieve import rag_job_context


def _readiness_dict(readiness: dict | None) -> dict | None:
    if not readiness:
        return None
    return {
        "final_overall": readiness.get("final_overall"),
        "sub_scores": readiness.get("final_sub_scores") or readiness.get("sub_scores"),
        "triggered_rules": readiness.get("adjusted_triggered_rules")
        or readiness.get("triggered_rules")
        or [],
    }


def generate_plan_bundle(
    state: dict,
    scan_summary: dict,
    project: str,
    langs: list[str],
    readiness: dict | None = None,
) -> dict:
    """Build all plan artifacts for one or more languages."""
    deploy_profile = state.get("deploy_profile") or {}
    hosting_shortlist = match_hosting_providers(deploy_profile)
    readiness_dict = _readiness_dict(readiness)

    reports: dict[str, str] = {}
    structured_by_lang: dict[str, dict] = {}
    bundles_by_lang: dict[str, dict] = {}
    impl_reports: dict[str, str] = {}
    impl_structured_by_lang: dict[str, dict] = {}
    agent_prompts_by_lang: dict[str, str] = {}
    rollout_reports: dict[str, str] = {}
    rollout_structured_by_lang: dict[str, dict] = {}

    founder_extras = build_founder_extras_artifact(state, hosting_shortlist, readiness_dict)

    with rag_job_context():
        for lang in langs:
            md, meta, structured, technical_report = generate_report_for_lang(
                state,
                lang,
                project,
                scan_summary=scan_summary,
            )
            reports[lang] = md
            if meta.get("structured"):
                structured_by_lang[lang] = meta["structured"]

            impl_md, impl_meta = generate_implementation_for_lang(
                state,
                lang,
                project,
                technical_report,
                structured,
                scan_summary=scan_summary,
                compliance_md=md,
            )
            impl_reports[lang] = impl_md
            if impl_meta.get("structured"):
                impl_structured_by_lang[lang] = impl_meta["structured"]
            if impl_meta.get("agent_prompt"):
                agent_prompts_by_lang[lang] = impl_meta["agent_prompt"]
            if impl_meta.get("bundle"):
                bundles_by_lang[lang] = impl_meta["bundle"]

            rollout_md, rollout_meta = generate_rollout_for_lang(
                state,
                lang,
                project,
                hosting_shortlist,
                technical_report,
                founder_extras.get("structured", {}).get("default", {}),
            )
            rollout_reports[lang] = rollout_md
            if rollout_meta.get("structured"):
                rollout_structured_by_lang[lang] = rollout_meta["structured"]

    return {
        "compliance_report": serialize_artifacts(
            reports,
            structured_by_lang=structured_by_lang or None,
            bundles_by_lang=bundles_by_lang or None,
        ),
        "implementation_guide": serialize_artifacts(
            impl_reports,
            structured_by_lang=impl_structured_by_lang or None,
            agent_prompts_by_lang=agent_prompts_by_lang or None,
        ),
        "rollout_guide": serialize_artifacts(
            rollout_reports,
            structured_by_lang=rollout_structured_by_lang or None,
        ),
        "founder_extras": founder_extras,
    }
