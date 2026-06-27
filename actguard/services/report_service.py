"""Report and legal document generation (markdown only)."""

from __future__ import annotations

from deploy.extras import build_founder_extras, founder_extras_to_json
from deploy.rollout import generate_rollout_guide
from eu_compliance import (
    generate_implementation_guide,
    generate_plain_summary,
    generate_report,
)
from export.build_artifacts import (
    build_bundle,
    build_implementation_artifact,
    build_report_artifact,
    build_scan_artifact,
)
from parsing.preprocess import TECHNICAL_REPORT_MARKER
from parsing.implementation_parser import parse_implementation_guide
from parsing.report_parser import parse_report_markdown


def _strip_actguard_header(full_md: str, header_title: str) -> str:
    """Return markdown body without the ActGuard title/blockquote header."""
    prefix = f"# {header_title}"
    if prefix not in full_md:
        return full_md
    _, rest = full_md.split(prefix, 1)
    marker = "> Automated self-assessment only. This is not legal advice."
    if marker in rest:
        return rest.split(marker, 1)[1].lstrip()
    marker = "> Engineer-ready tasks derived from automated self-assessment. Not legal advice."
    if marker in rest:
        return rest.split(marker, 1)[1].lstrip()
    marker = "> Hosting and phased launch guidance from automated stack analysis. Not legal advice."
    if marker in rest:
        return rest.split(marker, 1)[1].lstrip()
    parts = rest.split("\n\n", 2)
    return parts[2] if len(parts) >= 3 else rest.strip()


def generate_report_for_lang(
    state: dict,
    language: str,
    project: str,
    scan_summary: dict | None = None,
) -> tuple[str, dict, object, str]:
    technical_report = generate_report(state, language=language)
    synthesis = state.get("deep_synthesis") or {}
    plain_summary = generate_plain_summary(technical_report, synthesis, language=language)
    report_body = f"{plain_summary}\n\n{TECHNICAL_REPORT_MARKER}\n\n{technical_report}"
    header = (
        "# ActGuard — EU Compliance Self-Assessment Report\n\n"
        f"> Project: {project}  \n"
        f"> Language: {language}  \n"
        "> Automated self-assessment only. This is not legal advice.\n\n"
    )
    full_md = header + report_body

    structured = parse_report_markdown(
        report_body, project_name=project, language=language
    )
    artifacts_meta: dict = {"structured": structured.to_dict()}

    return full_md, artifacts_meta, structured, technical_report


def generate_implementation_for_lang(
    state: dict,
    language: str,
    project: str,
    technical_report: str,
    structured,
    scan_summary: dict | None = None,
    *,
    compliance_md: str | None = None,
) -> tuple[str, dict]:
    impl_md = generate_implementation_guide(
        state, technical_report, structured, language=language
    )
    header = (
        "# ActGuard — Compliance Implementation Guide\n\n"
        f"> Project: {project}  \n"
        f"> Language: {language}  \n"
        "> Engineer-ready tasks derived from automated self-assessment. Not legal advice.\n\n"
    )
    full_md = header + impl_md

    impl_structured = parse_implementation_guide(
        impl_md, project_name=project, language=language
    )

    meta: dict = {
        "structured": impl_structured.to_dict(),
        "agent_prompt": impl_structured.agent_prompt,
    }
    if scan_summary:
        scan_art = build_scan_artifact(scan_summary, state, project)
        report_art = build_report_artifact(structured)
        impl_art = build_implementation_artifact(impl_structured)
        meta["bundle"] = build_bundle(
            scan_art,
            report_art,
            markdown=compliance_md,
            implementation_artifact=impl_art,
            implementation_md=full_md,
        )

    return full_md, meta


def generate_rollout_for_lang(
    state: dict,
    language: str,
    project: str,
    hosting_shortlist: dict,
    technical_report: str,
    founder_extras: dict,
) -> tuple[str, dict]:
    rollout_body = generate_rollout_guide(
        state,
        hosting_shortlist,
        technical_report=technical_report,
        language=language,
        founder_extras=founder_extras,
    )
    header = (
        "# ActGuard — EU Startup Rollout Guide\n\n"
        f"> Project: {project}  \n"
        f"> Language: {language}  \n"
        "> Hosting and phased launch guidance from automated stack analysis. Not legal advice.\n\n"
    )
    full_md = header + rollout_body
    structured = {
        "schemaVersion": "eucompliance.rollout.v1",
        "projectName": project,
        "language": language,
        "hosting": hosting_shortlist,
        "deploy_profile": state.get("deploy_profile") or {},
        "phases": ["building", "public_beta", "paid", "scale"],
    }
    return full_md, {"structured": structured}


def build_founder_extras_artifact(
    state: dict,
    hosting_shortlist: dict,
    readiness: dict | None = None,
) -> dict:
    extras = build_founder_extras(
        state,
        state.get("deploy_profile"),
        hosting_shortlist,
        readiness,
    )
    return {"structured": {"default": founder_extras_to_json(extras)}}


def generate_legal_doc(generator, state: dict, language: str) -> str:
    return generator(state, language=language)


def serialize_artifacts(
    reports: dict[str, str],
    structured_by_lang: dict[str, dict] | None = None,
    bundles_by_lang: dict[str, dict] | None = None,
    agent_prompts_by_lang: dict[str, str] | None = None,
) -> dict:
    """Store markdown + structured JSON for session persistence."""
    out: dict = {"reports": {}, "structured": {}, "bundles": {}}
    for lang, md in reports.items():
        slug = lang.lower().replace(" ", "_")
        out["reports"][slug] = md
    if structured_by_lang:
        for lang, data in structured_by_lang.items():
            slug = lang.lower().replace(" ", "_")
            out["structured"][slug] = data
    if bundles_by_lang:
        for lang, data in bundles_by_lang.items():
            slug = lang.lower().replace(" ", "_")
            out["bundles"][slug] = data
    if agent_prompts_by_lang:
        out["agent_prompts"] = {}
        for lang, prompt in agent_prompts_by_lang.items():
            slug = lang.lower().replace(" ", "_")
            out["agent_prompts"][slug] = prompt
    return out
