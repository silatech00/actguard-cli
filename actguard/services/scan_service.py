"""Scan orchestration extracted from Streamlit app."""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Callable

from deep_analysis import build_file_tree, has_synthesis_content, run_deep_analysis
from eu_compliance import (
    SIGNALS,
    SENSITIVE_FIELD_KEYWORDS,
    build_state,
    scan_context,
    scan_project_context,
    scan_repo,
    scan_sensitive_fields,
)
from deploy.fingerprint import build_deploy_profile
from github_fetch import download_repo_to_tempdir


def extract_zip(upload_bytes: bytes, dest: Path) -> Path:
    zip_path = dest / "upload.zip"
    zip_path.write_bytes(upload_bytes)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(dest)
    except zipfile.BadZipFile as exc:
        raise ValueError("The uploaded file is not a valid zip archive.") from exc
    finally:
        zip_path.unlink(missing_ok=True)

    entries = [p for p in dest.iterdir() if p.name != ".DS_Store"]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return dest


def fetch_github_repo(url: str, token: str | None) -> str:
    return download_repo_to_tempdir(url.strip(), token)


def run_deep_analysis_step(
    repo_path: str,
    state: dict,
    evidence: dict,
    sensitive: dict,
    progress_callback: Callable[[str], None] | None = None,
    max_files: int = 18,
) -> dict:
    file_tree = build_file_tree(repo_path)
    synthesis = run_deep_analysis(
        repo_path,
        file_tree,
        evidence,
        sensitive,
        state,
        max_files=max_files,
        progress_callback=progress_callback,
    )
    return {**state, "deep_synthesis": synthesis}


def run_full_scan(
    repo_path: str,
    progress_callback: Callable[[str], None] | None = None,
) -> dict:
    """Run rule-based scan + deep analysis; return session payload."""
    with scan_context(repo_path):
        context = scan_project_context(repo_path)
        evidence, snippets = scan_repo(repo_path)
        sensitive = scan_sensitive_fields(repo_path)
        state = build_state(evidence, snippets, sensitive, context)
        state["deploy_profile"] = build_deploy_profile(repo_path, evidence, context)

        scan_summary = build_scan_summary(context, evidence, sensitive, state)

        try:
            state = run_deep_analysis_step(
                repo_path, state, evidence, sensitive, progress_callback=progress_callback
            )
            deep_done = True
            deep_error = None
        except Exception as exc:
            deep_done = False
            deep_error = str(exc)

    synthesis = state.get("deep_synthesis") or {}
    return {
        "project_name": context.get("name", ""),
        "repo_path": repo_path,
        "state": state,
        "scan_summary": scan_summary,
        "deep_analysis_done": deep_done,
        "deep_error": deep_error,
        "has_synthesis": has_synthesis_content(synthesis),
    }


from scanner.known_packages import category_label, lookup_known_package


def _build_regulation_hints(state: dict) -> dict:
    uses_ai = state.get("uses_ai", {}).get("value", False)
    high_risk = state.get("high_risk_ai", {}).get("value", False)
    is_platform = state.get("is_platform", {}).get("value", False)
    has_security = state.get("has_security", {}).get("value", False)
    cloud = state.get("cloud_infra", {}).get("value", False)
    sensitive = state.get("sensitive_data", {}).get("value", False)

    hints = {
        "ai_act": {
            "status": "applies" if uses_ai else "not_detected",
            "reason": "AI/ML libraries or APIs detected in codebase"
            if uses_ai
            else "No AI/ML dependencies detected",
        },
        "gdpr": {
            "status": "applies" if sensitive or is_platform else "unclear",
            "reason": "Sensitive or personal data fields detected"
            if sensitive
            else "Platform or data-processing patterns detected — GDPR likely applies"
            if is_platform
            else "Review data processing practices",
        },
        "nis2": {
            "status": "unclear" if cloud or is_platform else "not_detected",
            "reason": "Cloud infrastructure or platform detected — assess NIS2 entity status"
            if cloud or is_platform
            else "No strong NIS2 infrastructure signals",
        },
        "dsa": {
            "status": "applies" if is_platform else "not_detected",
            "reason": "Online platform or intermediary patterns detected"
            if is_platform
            else "No platform/intermediary signals detected",
        },
        "data_act": {
            "status": "unclear" if cloud else "not_detected",
            "reason": "Cloud/data infrastructure detected — assess IoT or data-holder role"
            if cloud
            else "No Data Act signals detected",
        },
    }
    if high_risk:
        hints["ai_act"]["status"] = "applies"
        hints["ai_act"]["reason"] = "High-risk AI signals (e.g. biometrics) detected"
    return hints


def build_scan_summary(
    context: dict, evidence: dict, sensitive: dict, state: dict
) -> dict:
    py_count = context["file_counts"].get(".py", 0)
    total_files = sum(context["file_counts"].values())

    evidence_list = []
    for pkg in list(evidence.keys())[:12]:
        field_name, _conf, desc = SIGNALS.get(pkg, ("uses_ai", 0.5, pkg))
        category = lookup_known_package(pkg)
        evidence_list.append({
            "pkg": pkg,
            "field": field_name,
            "desc": desc,
            "category": category or field_name,
            "category_label": category_label(category) if category else field_name,
        })

    sensitive_list = []
    for kw in list(sensitive.keys())[:8]:
        sensitive_list.append(
            {"keyword": kw, "label": SENSITIVE_FIELD_KEYWORDS.get(kw, kw)}
        )

    flags = []
    if state["uses_ai"]["value"]:
        flags.append(f"AI/ML ({state['uses_ai']['confidence']:.0%})")
    if state["high_risk_ai"]["value"]:
        flags.append("HIGH-RISK AI")
    if state["is_platform"]["value"]:
        flags.append("Platform")
    if state["has_security"]["value"]:
        flags.append("Security libs present")
    else:
        flags.append("No security libs detected")

    return {
        "total_files": total_files,
        "python_files": py_count,
        "evidence": evidence_list,
        "evidence_count": len(evidence),
        "sensitive": sensitive_list,
        "sensitive_count": len(sensitive),
        "annex_iii_candidates": state.get("annex_iii_candidates", [])[:6],
        "domain_signals": context.get("domain_signals", [])[:6],
        "profile_flags": flags,
        "regulation_hints": _build_regulation_hints(state),
    }


def cleanup_repo(path: str | None) -> None:
    if path and Path(path).exists():
        shutil.rmtree(path, ignore_errors=True)


def prepare_scan_workspace(scan_id: str) -> Path:
    root = Path(tempfile.gettempdir()) / "eu-compliance-scans" / scan_id
    root.mkdir(parents=True, exist_ok=True)
    return root
