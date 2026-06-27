"""À la carte compliance artifact generation (markdown only)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from actguard.services.report_service import (
    _strip_actguard_header,
    build_founder_extras_artifact,
    generate_implementation_for_lang,
    generate_legal_doc,
    generate_report_for_lang,
    generate_rollout_for_lang,
    serialize_artifacts,
)
from deploy.matcher import match_hosting_providers
from eu_compliance import generate_privacy_policy, generate_tos
from legal_rag.retrieve import rag_job_context
from parsing.preprocess import split_plain_and_technical
from parsing.report_parser import parse_report_markdown

from actguard.output import lang_slug, save_artifact_section, save_markdown, save_plan_artifacts
from actguard.plan import _readiness_dict
from actguard.session import save_session

ARTIFACT_CHOICES = (
    "report",
    "implement",
    "rollout",
    "privacy",
    "tos",
    "extras",
    "all",
)

_REPORT_HEADER = "ActGuard — EU Compliance Self-Assessment Report"


def _report_md_path(repo: Path, lang: str, *, multi_lang: bool) -> Path:
    stem = "compliance_report"
    if multi_lang:
        stem = f"{stem}_{lang_slug(lang)}"
    return repo / f"{stem}.md"


def _cache_report_context(
    session: dict[str, Any],
    lang: str,
    *,
    technical_report: str,
    structured: object,
    report_md: str,
) -> None:
    generated = session.setdefault("generated", {})
    generated[lang_slug(lang)] = {
        "technical_report": technical_report,
        "structured": getattr(structured, "to_dict", lambda: structured)(),
        "report_md": report_md,
    }


def _load_report_context(
    repo: Path,
    lang: str,
    project: str,
    session: dict[str, Any] | None = None,
    *,
    multi_lang: bool = False,
) -> tuple[str, object, str]:
    """Return (technical_report, structured, full_report_md) from session cache or disk."""
    if session:
        cached = (session.get("generated") or {}).get(lang_slug(lang))
        if cached and cached.get("technical_report"):
            structured = parse_report_markdown(
                cached.get("report_md") or cached["technical_report"],
                project_name=project,
                language=lang,
            )
            return cached["technical_report"], structured, cached.get("report_md", "")

    md_path = _report_md_path(repo, lang, multi_lang=multi_lang)
    if not md_path.is_file() and not multi_lang:
        md_path = repo / "compliance_report.md"
    if not md_path.is_file():
        raise FileNotFoundError(
            "Compliance report not found. Run: actguard generate report"
        )

    full_md = md_path.read_text(encoding="utf-8")
    body = _strip_actguard_header(full_md, _REPORT_HEADER)
    _, technical = split_plain_and_technical(body)
    if not technical:
        technical = body
    structured = parse_report_markdown(body, project_name=project, language=lang)
    return technical, structured, full_md


def _founder_extras_payload(
    state: dict,
    readiness: dict | None,
) -> dict:
    deploy_profile = state.get("deploy_profile") or {}
    hosting_shortlist = match_hosting_providers(deploy_profile)
    return build_founder_extras_artifact(
        state,
        hosting_shortlist,
        _readiness_dict(readiness),
    )


def generate_report_artifact(
    repo: Path,
    session: dict[str, Any],
    lang: str,
    *,
    multi_lang: bool = False,
    progress: Callable[[str], None] | None = None,
) -> list[Path]:
    project = session.get("project_name") or repo.name
    scan_summary = session.get("scan_summary") or {}

    if progress:
        progress("Compliance report (plain + legal language)…")

    with rag_job_context():
        md, meta, structured, technical_report = generate_report_for_lang(
            session["state"],
            lang,
            project,
            scan_summary=scan_summary,
        )

    _cache_report_context(
        session,
        lang,
        technical_report=technical_report,
        structured=structured,
        report_md=md,
    )
    save_session(repo, session)

    section = serialize_artifacts(
        {lang: md},
        structured_by_lang={lang: meta["structured"]},
    )
    return save_artifact_section(
        repo,
        section,
        "compliance_report",
        lang,
        multi_lang=multi_lang,
    )


def generate_implement_artifact(
    repo: Path,
    session: dict[str, Any],
    lang: str,
    *,
    multi_lang: bool = False,
    progress: Callable[[str], None] | None = None,
) -> list[Path]:
    project = session.get("project_name") or repo.name
    scan_summary = session.get("scan_summary") or {}
    technical, structured, compliance_md = _load_report_context(
        repo, lang, project, session, multi_lang=multi_lang
    )

    if progress:
        progress("Implementation guide + engineer agent prompt…")

    with rag_job_context():
        impl_md, impl_meta = generate_implementation_for_lang(
            session["state"],
            lang,
            project,
            technical,
            structured,
            scan_summary=scan_summary,
            compliance_md=compliance_md,
        )

    section = serialize_artifacts(
        {lang: impl_md},
        structured_by_lang={lang: impl_meta["structured"]},
        agent_prompts_by_lang={lang: impl_meta["agent_prompt"]},
    )
    saved = save_artifact_section(
        repo,
        section,
        "implementation_guide",
        lang,
        multi_lang=multi_lang,
    )
    prompt = impl_meta.get("agent_prompt", "")
    if prompt:
        prompt_path = repo / "agent_prompt.md"
        save_markdown(prompt_path, prompt)
        saved.append(prompt_path)
    return saved


def generate_rollout_artifact(
    repo: Path,
    session: dict[str, Any],
    lang: str,
    *,
    multi_lang: bool = False,
    progress: Callable[[str], None] | None = None,
) -> list[Path]:
    project = session.get("project_name") or repo.name
    state = session["state"]
    technical, _, _ = _load_report_context(
        repo, lang, project, session, multi_lang=multi_lang
    )
    founder_extras = _founder_extras_payload(state, session.get("readiness"))
    hosting_shortlist = match_hosting_providers(state.get("deploy_profile") or {})

    if progress:
        progress("EU rollout guide…")

    with rag_job_context():
        rollout_md, rollout_meta = generate_rollout_for_lang(
            state,
            lang,
            project,
            hosting_shortlist,
            technical,
            founder_extras.get("structured", {}).get("default", {}),
        )

    section = serialize_artifacts(
        {lang: rollout_md},
        structured_by_lang={lang: rollout_meta["structured"]},
    )
    return save_artifact_section(
        repo,
        section,
        "rollout_guide",
        lang,
        multi_lang=multi_lang,
    )


def _legal_header(title: str, project: str, lang: str) -> str:
    return (
        f"# {title}\n\n"
        f"> Project: {project}  \n"
        f"> Language: {lang}  \n"
        "> AI-generated draft for legal review. Not legal advice.\n\n"
    )


def generate_privacy_artifact(
    repo: Path,
    session: dict[str, Any],
    lang: str,
    *,
    multi_lang: bool = False,
    progress: Callable[[str], None] | None = None,
) -> list[Path]:
    project = session.get("project_name") or repo.name

    if progress:
        progress("Draft privacy policy…")

    with rag_job_context():
        body = generate_legal_doc(generate_privacy_policy, session["state"], lang)

    full_md = _legal_header("Privacy Policy (Draft)", project, lang) + body
    stem = "privacy_policy"
    if multi_lang:
        stem = f"{stem}_{lang_slug(lang)}"
    return [save_markdown(repo / f"{stem}.md", full_md)]


def generate_tos_artifact(
    repo: Path,
    session: dict[str, Any],
    lang: str,
    *,
    multi_lang: bool = False,
    progress: Callable[[str], None] | None = None,
) -> list[Path]:
    project = session.get("project_name") or repo.name

    if progress:
        progress("Draft terms of service…")

    with rag_job_context():
        body = generate_legal_doc(generate_tos, session["state"], lang)

    full_md = _legal_header("Terms of Service (Draft)", project, lang) + body
    stem = "terms_of_service"
    if multi_lang:
        stem = f"{stem}_{lang_slug(lang)}"
    return [save_markdown(repo / f"{stem}.md", full_md)]


def generate_extras_artifact(
    repo: Path,
    session: dict[str, Any],
    *,
    progress: Callable[[str], None] | None = None,
) -> list[Path]:
    if progress:
        progress("Founder extras (hosting, timelines, subprocessors)…")

    founder_extras = _founder_extras_payload(session["state"], session.get("readiness"))
    return save_plan_artifacts(
        repo,
        {"founder_extras": founder_extras},
        "English",
        multi_lang=False,
    )


def generate_all_artifacts(
    repo: Path,
    session: dict[str, Any],
    langs: list[str],
    *,
    progress: Callable[[str], None] | None = None,
) -> list[Path]:
    from actguard.plan import generate_plan_bundle

    project = session.get("project_name") or repo.name
    if progress:
        progress("Full plan bundle…")

    with rag_job_context():
        artifacts = generate_plan_bundle(
            session["state"],
            session.get("scan_summary") or {},
            project,
            langs,
            session.get("readiness"),
        )

    multi_lang = len(langs) > 1
    saved = save_plan_artifacts(repo, artifacts, langs[0], multi_lang=multi_lang)

    for lang in langs:
        comp = artifacts.get("compliance_report") or {}
        slug = lang_slug(lang)
        md = (comp.get("reports") or {}).get(slug, "")
        structured = (comp.get("structured") or {}).get(slug)
        if md and structured:
            body = _strip_actguard_header(md, _REPORT_HEADER)
            _, technical = split_plain_and_technical(body)
            if not technical:
                technical = body
            _cache_report_context(
                session,
                lang,
                technical_report=technical,
                structured=structured,
                report_md=md,
            )
    save_session(repo, session)
    return saved


def generate_artifact(
    name: str,
    repo: Path,
    session: dict[str, Any],
    lang: str,
    *,
    multi_lang: bool = False,
    progress: Callable[[str], None] | None = None,
) -> list[Path]:
    generators: dict[str, Callable[..., list[Path]]] = {
        "report": generate_report_artifact,
        "implement": generate_implement_artifact,
        "rollout": generate_rollout_artifact,
        "privacy": generate_privacy_artifact,
        "tos": generate_tos_artifact,
        "extras": lambda r, s, *_a, **_k: generate_extras_artifact(r, s, progress=progress),
    }
    if name == "all":
        return generate_all_artifacts(repo, session, [lang], progress=progress)
    if name not in generators:
        raise ValueError(f"Unknown artifact: {name}")
    if name == "extras":
        return generators[name](repo, session)
    return generators[name](repo, session, lang, multi_lang=multi_lang, progress=progress)
