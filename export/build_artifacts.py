"""Build eucompliance.* evidence artifacts (own namespace, EuConform-inspired)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from parsing.implementation_parser import StructuredImplementationGuide
from parsing.report_parser import StructuredReport

TOOL_NAME = "actguard"
TOOL_VERSION = "0.2.0"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_scan_artifact(scan_summary: dict, state: dict, project_name: str) -> dict:
    return {
        "schemaVersion": "eucompliance.scan.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "target": {
            "name": project_name,
            "repoType": "unknown",
            "detectedStack": list((state.get("project_context") or {}).get("file_counts", {}).keys()),
        },
        "signals": {
            "evidence": scan_summary.get("evidence", []),
            "sensitive": scan_summary.get("sensitive", []),
            "profile_flags": scan_summary.get("profile_flags", []),
        },
        "regulationHints": scan_summary.get("regulation_hints", {}),
        "annexIIICandidates": scan_summary.get("annex_iii_candidates", []),
    }


def build_report_artifact(structured: StructuredReport) -> dict:
    return {
        "schemaVersion": "eucompliance.report.v1",
        "generatedAt": structured.generated_at,
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "projectName": structured.project_name,
        "language": structured.language,
        "plainSummary": structured.plain_summary,
        "sections": [
            {
                "id": s.id,
                "title": s.title,
                "applicability": s.applicability,
                "riskClassification": s.risk_classification,
                "gaps": s.gaps,
                "actions": s.actions,
            }
            for s in structured.sections
        ],
        "priorityMatrix": structured.priority_matrix,
        "disclaimer": structured.disclaimer,
    }


def build_implementation_artifact(structured: StructuredImplementationGuide) -> dict:
    return {
        "schemaVersion": "eucompliance.implementation.v1",
        "generatedAt": structured.generated_at,
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "projectName": structured.project_name,
        "language": structured.language,
        "projectContext": structured.project_context,
        "tasks": [
            {
                "id": t.id,
                "priority": t.priority,
                "title": t.title,
                "regulation": t.regulation,
                "type": t.type,
                "why": t.why,
                "files": t.files,
                "steps": t.steps,
                "acceptanceCriteria": t.acceptance_criteria,
                "effort": t.effort,
            }
            for t in structured.tasks
        ],
        "agentPrompt": structured.agent_prompt,
        "legalNotes": structured.legal_notes,
    }


def build_bundle(
    scan_artifact: dict,
    report_artifact: dict,
    *,
    markdown: str | None = None,
    implementation_artifact: dict | None = None,
    implementation_md: str | None = None,
) -> dict:
    files: list[dict[str, Any]] = [
        {
            "path": "eucompliance.scan.json",
            "schemaVersion": scan_artifact["schemaVersion"],
            "sha256": _sha256(json.dumps(scan_artifact, sort_keys=True).encode()),
        },
        {
            "path": "eucompliance.report.json",
            "schemaVersion": report_artifact["schemaVersion"],
            "sha256": _sha256(json.dumps(report_artifact, sort_keys=True).encode()),
        },
    ]
    if markdown:
        files.append({
            "path": "compliance_report.md",
            "schemaVersion": "text/markdown",
            "sha256": _sha256(markdown.encode("utf-8")),
        })
    if implementation_artifact:
        files.append({
            "path": "eucompliance.implementation.json",
            "schemaVersion": implementation_artifact["schemaVersion"],
            "sha256": _sha256(json.dumps(implementation_artifact, sort_keys=True).encode()),
        })
    if implementation_md:
        files.append({
            "path": "implementation_guide.md",
            "schemaVersion": "text/markdown",
            "sha256": _sha256(implementation_md.encode("utf-8")),
        })
    bundle = {
        "schemaVersion": "eucompliance.bundle.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "files": files,
        "scan": scan_artifact,
        "report": report_artifact,
    }
    if implementation_artifact:
        bundle["implementation"] = implementation_artifact
    return bundle
