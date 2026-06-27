"""EU startup rollout guide generator."""

from __future__ import annotations

import json

from eu_compliance import MISTRAL_MODEL, _language_instruction, _mistral_complete, build_profile_text


def _format_hosting_shortlist(shortlist: dict) -> str:
    if not shortlist or not shortlist.get("primary"):
        return "No hosting recommendation available."
    lines = ["HOSTING SHORTLIST (fixed by rules engine — explain, do not change providers):"]
    primary = shortlist["primary"]
    lines.append(
        f"PRIMARY: {primary.get('name')} — region {primary.get('region')} "
        f"(residency tier {primary.get('residency_tier')}, score {primary.get('score')})"
    )
    lines.append(f"  Evidence: {', '.join(primary.get('evidence') or [])}")
    lines.append(f"  Notes: {primary.get('notes', '')}")
    for alt in shortlist.get("alternatives") or []:
        lines.append(
            f"ALTERNATIVE: {alt.get('name')} — region {alt.get('region')} "
            f"(tier {alt.get('residency_tier')}, score {alt.get('score')})"
        )
    arch = shortlist.get("architecture") or {}
    if arch:
        lines.append("ARCHITECTURE:")
        for k, v in arch.items():
            lines.append(f"  {k}: {v}")
    for w in shortlist.get("warnings") or []:
        lines.append(f"WARNING: {w}")
    lines.append(f"Confidence: {shortlist.get('confidence', 'medium')}")
    return "\n".join(lines)


def _format_deploy_profile(profile: dict) -> str:
    if not profile:
        return "No deploy profile."
    return json.dumps(profile, indent=2, default=str)


def generate_rollout_guide(
    state: dict,
    hosting_shortlist: dict,
    technical_report: str = "",
    language: str = "English",
    founder_extras: dict | None = None,
) -> str:
    """Generate EU startup rollout guide grounded in deploy profile and hosting matcher."""
    profile = build_profile_text(state)
    deploy = state.get("deploy_profile") or {}
    project_name = state.get("project_context", {}).get("name", "unknown")
    hosting_block = _format_hosting_shortlist(hosting_shortlist)
    deploy_block = _format_deploy_profile(deploy)
    extras = founder_extras or {}
    subprocessors = extras.get("subprocessors") or []
    gates = extras.get("launch_gates") or []

    lang_instruction = _language_instruction(language)
    if language and language != "English" and not lang_instruction:
        lang_instruction = f"\nWrite the entire guide in {language}.\n"

    prompt = f"""You are an EU startup advisor helping a young founder deploy their product in Europe with sensible compliance and hosting choices.

The audience is founders and vibe coders — NOT lawyers. Be practical and actionable.

PROJECT: {project_name}

CODEBASE / COMPLIANCE PROFILE:
{profile}

DEPLOY PROFILE (from automated stack fingerprint):
{deploy_block}

{hosting_block}

SUB-PROCESSORS DETECTED ({len(subprocessors)}):
{json.dumps(subprocessors[:10], indent=2) if subprocessors else "None"}

LAUNCH GATES:
{json.dumps(gates, indent=2) if gates else "None"}

COMPLIANCE CONTEXT (excerpt):
{technical_report[:3000] if technical_report else "See profile above."}
{lang_instruction}
GROUNDING RULES:
- Use ONLY the hosting providers listed in HOSTING SHORTLIST — do not invent or substitute providers.
- Cite file/stack evidence from the deploy profile for every recommendation.
- Never say "Railway is EU hosting" — if Railway appears, note it is US-operated and requires Amsterdam region pin.
- For Sliplane/Hetzner/Scaleway, note user must select EU server location (DE/FI/FR).
- Phases: Phase 0 (building) → Phase 1 (public beta) → Phase 2 (paid) → Phase 3 (scale).
- Cross-reference compliance gates with launch gates.
- Include deploy config hints only if deploy confidence is medium or high.
- This is NOT legal advice.

Generate markdown with these EXACT section headers:

# EU Startup Rollout Guide

## Detected stack summary
Bullet list of frameworks, databases, workers, AI vendors — each with file evidence.

## Recommended architecture
Frontend / API / database / object storage layout using the fixed hosting shortlist.

## Primary hosting recommendation
Explain the primary provider and region. Include 2 alternatives from the shortlist with tradeoffs (cost, ops, residency).

## EU data residency checklist
Actionable checklist: region pins, volume co-location, sub-processor DPAs, transfer safeguards.

## Phased rollout
### Phase 0 — Building (no users)
### Phase 1 — Public beta
### Phase 2 — Paying customers
### Phase 3 — Scale
For each phase: 3–5 concrete actions tied to scan findings.

## Sub-processor chain
Table or bullets: vendor, purpose, EU/US note, DPA needed.

## Compliance gates per phase
What must be true before each launch gate (friends → beta → paid → enterprise).

## Deploy next steps
Numbered steps an engineer can execute this week (env vars, region selection, DNS).

## Notes for legal review
Items requiring qualified counsel.

---
DISCLAIMER: Automated rollout guidance — not legal advice. Verify hosting and transfer decisions with counsel."""

    content = _mistral_complete(
        [{"role": "user", "content": prompt}],
        label="Rollout guide",
    )
    if not content or not content.strip():
        raise RuntimeError("Mistral returned an empty rollout guide.")
    return content.strip()
