"""Write compliance artifacts to the project directory (markdown only)."""

from __future__ import annotations

import json
from pathlib import Path


def lang_slug(language: str) -> str:
    return language.lower().replace(" ", "_")


def save_markdown(path: Path, markdown: str) -> Path:
    path.write_text(markdown, encoding="utf-8")
    return path


def save_report_outputs(
    repo_path: Path | str,
    *,
    markdown: str,
    stem: str = "compliance_report",
) -> Path:
    """Write a markdown artifact to the project directory."""
    root = Path(repo_path).resolve()
    md_path = root / f"{stem}.md"
    return save_markdown(md_path, markdown)


def _artifact_stem(stem: str, primary_lang: str, *, multi_lang: bool) -> str:
    if multi_lang:
        return f"{stem}_{lang_slug(primary_lang)}"
    return stem


def save_artifact_section(
    repo_path: Path,
    section: dict,
    stem: str,
    primary_lang: str,
    *,
    multi_lang: bool = False,
) -> list[Path]:
    saved: list[Path] = []
    slug = lang_slug(primary_lang)
    md_stem = _artifact_stem(stem, primary_lang, multi_lang=multi_lang)

    md_content = (section.get("reports") or {}).get(slug, "")
    if not md_content and section.get("reports"):
        first_key = next(iter(section["reports"]))
        md_content = section["reports"][first_key]

    if md_content:
        saved.append(save_report_outputs(repo_path, markdown=md_content, stem=md_stem))

    return saved


def save_plan_artifacts(
    repo_path: Path | str,
    artifacts: dict,
    primary_lang: str,
    *,
    multi_lang: bool = False,
) -> list[Path]:
    """Write plan bundle markdown files to the project directory."""
    root = Path(repo_path).resolve()
    saved: list[Path] = []

    for stem, key in (
        ("compliance_report", "compliance_report"),
        ("implementation_guide", "implementation_guide"),
        ("rollout_guide", "rollout_guide"),
    ):
        section = artifacts.get(key) or {}
        saved.extend(
            save_artifact_section(
                root,
                section,
                stem,
                primary_lang,
                multi_lang=multi_lang,
            )
        )

    slug = lang_slug(primary_lang)
    impl = artifacts.get("implementation_guide") or {}
    agent_prompts = impl.get("agent_prompts") or {}
    prompt = agent_prompts.get(slug, "")
    if not prompt and agent_prompts:
        prompt = next(iter(agent_prompts.values()))
    if prompt:
        saved.append(save_markdown(root / "agent_prompt.md", prompt))

    extras = artifacts.get("founder_extras")
    if extras:
        extras_path = root / "founder_extras.json"
        extras_path.write_text(
            json.dumps(extras, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        saved.append(extras_path)

    return saved
