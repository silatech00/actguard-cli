"""
AI-powered deep codebase analysis (map-reduce) for EU compliance profiling.

Runs after the rule-based scan and before Q&A to produce semantic understanding
and context-specific follow-up questions.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from eu_compliance import (
    EXCLUDE_FILES,
    SIGNALS,
    _mistral_complete,
    _parse_json_response,
    _should_skip,
    build_profile_text,
)

ENTRY_POINT_KEYWORDS = ("main", "app", "api", "routes", "models", "schema")
README_PATTERN = re.compile(r"^readme(\..+)?$", re.IGNORECASE)
AI_PLATFORM_FIELDS = {"uses_ai", "high_risk_ai", "is_platform"}
LARGE_FILE_CHARS = 12000

# NOTE: these must stay in sync with the option strings in
# eu_compliance.get_questions(); they validate the LLM's suggested pre-fills.
PROJECT_STAGE_OPTIONS = [
    "Still building it (no real users yet)",
    "Just launched (a few early users)",
    "Live with active users",
    "It's open source (we don't run it as a paid service)",
]
SECTOR_OPTIONS = [
    "Software / tech",
    "Finance",
    "Healthcare",
    "Online platform / marketplace",
    "Something else",
]
AI_USE_CASE_OPTIONS = [
    "Creates content (text, images, code)",
    "Recommends or personalises things",
    "Sorts, scores or predicts things",
    "Makes decisions about people (health, money, hiring, identity)",
    "Something else",
]


def build_file_tree(repo_dir: str) -> list[dict]:
    """Walk the repo and return a flat list of file entries with relative paths."""
    root = Path(repo_dir)
    tree: list[dict] = []
    for file in root.rglob("*"):
        if not file.is_file() or _should_skip(file) or file.name in EXCLUDE_FILES:
            continue
        tree.append({"path": str(file.relative_to(root))})
    return tree


def _paths_from_evidence(evidence: dict) -> set[str]:
    paths: set[str] = set()
    for sources in evidence.values():
        for source in sources:
            path = source.split(":")[0]
            if path:
                paths.add(path)
    return paths


def _paths_from_sensitive(sensitive: dict) -> set[str]:
    paths: set[str] = set()
    for locations in sensitive.values():
        for location, _snippet in locations:
            path = location.split(":")[0]
            if path:
                paths.add(path)
    return paths


def _is_readme(path: str) -> bool:
    return bool(README_PATTERN.match(Path(path).name))


def _is_entry_point(path: str) -> bool:
    lower = path.lower()
    return any(kw in lower for kw in ENTRY_POINT_KEYWORDS)


def _is_infra_config(path: str) -> bool:
    """Docker, CI, env templates, and settings files reveal deployment context."""
    name = Path(path).name.lower()
    normalized = path.replace("\\", "/").lower()
    if name in ("dockerfile", "docker-compose.yml", "docker-compose.yaml", ".env.example"):
        return True
    if ".github/workflows/" in normalized:
        return True
    if name.endswith(".py") and ("config" in name or "settings" in name):
        return True
    return False


def _ai_platform_paths(evidence: dict) -> set[str]:
    paths: set[str] = set()
    for pkg, sources in evidence.items():
        if pkg not in SIGNALS:
            continue
        field_name, _conf, _desc = SIGNALS[pkg]
        if field_name not in AI_PLATFORM_FIELDS:
            continue
        for source in sources:
            path = source.split(":")[0]
            if path:
                paths.add(path)
    return paths


def select_key_files(
    file_tree: list[dict],
    evidence: dict,
    sensitive: dict,
    max_files: int = 20,
) -> list[str]:
    """
    Pick the most compliance-relevant files for per-file AI analysis.
    Priority: README → infra/config → sensitive hits → AI/platform hits → entry points.
    """
    all_paths = {entry["path"] for entry in file_tree if entry.get("path")}
    evidence_paths = _paths_from_evidence(evidence)
    sensitive_paths = _paths_from_sensitive(sensitive)
    ai_paths = _ai_platform_paths(evidence)

    readme_files = sorted(p for p in all_paths if _is_readme(p) and "/" not in p)
    if not readme_files:
        readme_files = sorted(p for p in all_paths if _is_readme(p))[:1]
    infra_files = sorted(p for p in all_paths if _is_infra_config(p))
    entry_files = sorted(p for p in all_paths if _is_entry_point(p))

    # Order by compliance relevance: the code that actually touches sensitive
    # data or AI/automated decisions matters more than infra boilerplate.
    priority_groups = [
        readme_files,
        sorted(sensitive_paths & all_paths),
        sorted(ai_paths & all_paths),
        sorted(entry_files),
        sorted(evidence_paths & all_paths),
        infra_files,
    ]

    selected: list[str] = []
    seen: set[str] = set()
    for group in priority_groups:
        for path in group:
            if path not in seen:
                seen.add(path)
                selected.append(path)

    if len(selected) > max_files:
        selected = selected[:max_files]
    return selected


def _coerce_text(value) -> str | None:
    """Normalize LLM JSON values to a single string for merging/display."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        for key in ("description", "text", "summary", "purpose", "value", "name"):
            if key in value and value[key]:
                return _coerce_text(value[key])
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        parts = [_coerce_text(item) for item in value]
        parts = [part for part in parts if part]
        return "; ".join(parts) if parts else None
    return str(value)


def _coerce_str_list(items) -> list[str]:
    if not isinstance(items, list):
        return []
    result: list[str] = []
    for item in items:
        text = _coerce_text(item)
        if text:
            result.append(text)
    return result


def _dedupe_preserve_order(items: list) -> list:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = _coerce_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def has_synthesis_content(synthesis: dict | None) -> bool:
    """True if the synthesis dict contains any user-visible analysis."""
    if not synthesis:
        return False
    return bool(
        (synthesis.get("product_description") or "").strip()
        or (synthesis.get("product_summary") or "").strip()
        or synthesis.get("ai_features")
        or synthesis.get("data_flows")
        or (synthesis.get("user_facing_assessment") or "").strip()
        or synthesis.get("uncertainties")
    )


def _extract_synthesis_dict(parsed: dict) -> dict:
    """Unwrap common LLM response shapes into the flat synthesis schema."""
    if not parsed:
        return {}
    if any(
        key in parsed
        for key in ("product_summary", "product_description", "suggested_answers")
    ):
        return parsed
    for key in ("corrected_synthesis", "synthesis", "corrected", "result", "output", "analysis"):
        nested = parsed.get(key)
        if isinstance(nested, dict) and any(
            k in nested
            for k in ("product_summary", "product_description", "suggested_answers")
        ):
            return nested
    return parsed


def _empty_file_analysis() -> dict:
    return {
        "purpose": None,
        "data_handled": [],
        "ai_or_automated_processing": None,
        "user_facing": None,
        "external_services": [],
        "automated_decisions_about_people": None,
        "data_collection_points": [],
    }


def _empty_suggested_answer() -> dict:
    return {"value": None, "confidence": "low", "reasoning": ""}


def _empty_synthesis() -> dict:
    return {
        "product_summary": "",
        "product_description": "",
        "ai_features": [],
        "data_flows": [],
        "user_facing_assessment": "",
        "uncertainties": [],
        "suggested_answers": {
            "project_stage": _empty_suggested_answer(),
            "sector": _empty_suggested_answer(),
            "ai_use_case": _empty_suggested_answer(),
            "company_size": {
                "value": None,
                "confidence": "low",
                "reasoning": "Company size cannot be reliably inferred from code — always ask the user",
            },
            "mau": {
                "value": None,
                "confidence": "low",
                "reasoning": "User counts cannot be inferred from code — always ask the user",
            },
        },
    }


def _split_content_at_line(content: str, max_chars: int = LARGE_FILE_CHARS) -> list[str]:
    """Split large files at a line boundary near the midpoint."""
    if len(content) <= max_chars:
        return [content]
    midpoint = len(content) // 2
    split_at = content.rfind("\n", 0, midpoint)
    if split_at <= 0:
        split_at = midpoint
    return [content[:split_at], content[split_at:]]


def _merge_file_analyses(part1: dict, part2: dict) -> dict:
    """Merge two partial analyses of the same file."""
    merged = _empty_file_analysis()
    purposes = [
        _coerce_text(p)
        for p in (part1.get("purpose"), part2.get("purpose"))
        if _coerce_text(p)
    ]
    merged["purpose"] = " ".join(purposes) if purposes else None

    data = list(part1.get("data_handled") or []) + list(part2.get("data_handled") or [])
    merged["data_handled"] = _dedupe_preserve_order(data)

    services = list(part1.get("external_services") or []) + list(part2.get("external_services") or [])
    merged["external_services"] = _dedupe_preserve_order(services)

    ai_parts = [
        _coerce_text(p)
        for p in (part1.get("ai_or_automated_processing"), part2.get("ai_or_automated_processing"))
        if _coerce_text(p)
    ]
    merged["ai_or_automated_processing"] = " ".join(ai_parts) if ai_parts else None

    decision_parts = [
        _coerce_text(p)
        for p in (
            part1.get("automated_decisions_about_people"),
            part2.get("automated_decisions_about_people"),
        )
        if _coerce_text(p)
    ]
    merged["automated_decisions_about_people"] = " ".join(decision_parts) if decision_parts else None

    collection = list(part1.get("data_collection_points") or []) + list(
        part2.get("data_collection_points") or []
    )
    merged["data_collection_points"] = _dedupe_preserve_order(collection)

    uf1, uf2 = part1.get("user_facing"), part2.get("user_facing")
    if uf1 is True or uf2 is True:
        merged["user_facing"] = True
    elif uf1 is False and uf2 is False:
        merged["user_facing"] = False
    else:
        merged["user_facing"] = uf1 if uf1 is not None else uf2
    return merged


def _analyze_file_chunk(path: str, content: str, part_label: str | None = None) -> dict:
    """Run Mistral analysis on a single file chunk."""
    part_note = f"\nNOTE: {part_label}\n" if part_label else ""
    prompt = f"""You are a senior EU compliance engineer reading one source file. Read the
ACTUAL code carefully — trace what data enters, how it is processed, and where it goes.
Be concrete and cite specific identifiers (function, class, route, field or variable names)
as evidence. Do not invent anything that is not in the code; if something is unclear, say so.

Return ONLY valid JSON with these keys:
{{
  "purpose": "one sentence - what this file does",
  "data_handled": ["specific data types/fields processed, each with the identifier where it appears, e.g. 'email (User.email field)'"],
  "ai_or_automated_processing": "describe any AI/ML/automated decision logic, naming the model/library/function, or null if none",
  "automated_decisions_about_people": "describe any logic that scores, ranks, filters, approves/denies, or otherwise makes decisions about individuals (credit, hiring, health, eligibility, moderation), naming the function — or null if none",
  "data_collection_points": ["where personal data enters or leaves the system, e.g. 'POST /signup collects name+email', 'sends user message to OpenAI API'"],
  "user_facing": true/false/null (null if unclear from this file alone),
  "external_services": ["third-party APIs/services this file calls, by name"]
}}
{part_note}
FILE: {path}
CONTENT:
{content}"""

    try:
        raw = _mistral_complete(
            [{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            label=f"File analysis ({path})",
        )
        parsed = _parse_json_response(raw)
        if not parsed:
            return _empty_file_analysis()
        result = _empty_file_analysis()
        result["purpose"] = _coerce_text(parsed.get("purpose"))
        result["data_handled"] = _coerce_str_list(parsed.get("data_handled"))
        result["ai_or_automated_processing"] = _coerce_text(parsed.get("ai_or_automated_processing"))
        result["automated_decisions_about_people"] = _coerce_text(
            parsed.get("automated_decisions_about_people")
        )
        result["data_collection_points"] = _coerce_str_list(parsed.get("data_collection_points"))
        result["user_facing"] = parsed.get("user_facing")
        result["external_services"] = _coerce_str_list(parsed.get("external_services"))
        return result
    except Exception:
        return _empty_file_analysis()


def _analyze_file_static(path: str, content: str) -> dict:
    """Rule-based per-file analysis when the LLM step is unavailable."""
    result = _empty_file_analysis()
    lower = content.lower()
    rel_lower = path.lower()

    if "streamlit" in lower or "st." in content:
        result["user_facing"] = True
    if any(kw in rel_lower for kw in ("app.py", "main.py", "routes", "api")):
        result["user_facing"] = True

    data_fields: list[str] = []
    for match in re.finditer(
        r"\b(passport|ethnicity|criminal|email|phone|ssn|social_security|health|biometric)[a-z_]*\b",
        content,
        re.I,
    ):
        data_fields.append(match.group(0))
    result["data_handled"] = _dedupe_preserve_order(data_fields)[:8]

    if re.search(r"\b(openai|mistral|anthropic|llm|chat_completion|generate)\b", content, re.I):
        result["ai_or_automated_processing"] = "AI/LLM API usage detected in file"

    decision_match = re.search(
        r"\b(eligibility_score|visa_eligibility|check_eligibility|credit_score|"
        r"score_applicant|rank_|approve|deny|reject)\b",
        content,
        re.I,
    )
    if decision_match:
        result["automated_decisions_about_people"] = (
            f"Possible automated decision/scoring logic ({decision_match.group(0)})"
        )

    for svc in ("openai", "openrouter", "anthropic", "mistral", "stripe", "twilio"):
        if svc in lower:
            result["external_services"].append(svc)

    if path.lower().endswith("readme.md"):
        first_lines = [ln.strip() for ln in content.splitlines() if ln.strip() and not ln.startswith("#")]
        if first_lines:
            result["purpose"] = first_lines[0][:200]
    elif result["data_handled"]:
        result["purpose"] = f"Handles personal data fields: {', '.join(result['data_handled'][:4])}"
    elif result["ai_or_automated_processing"]:
        result["purpose"] = "Contains AI/automation logic"

    return result


def analyze_file(path: str, content: str) -> dict:
    """Map step: analyze a single file with Mistral (splitting very large files)."""
    chunks = _split_content_at_line(content)
    if len(chunks) == 1:
        llm_result = _analyze_file_chunk(path, chunks[0])
    else:
        part1 = _analyze_file_chunk(path, chunks[0], "This is part 1/2 of a larger file")
        part2 = _analyze_file_chunk(path, chunks[1], "This is part 2/2 of a larger file")
        llm_result = _merge_file_analyses(part1, part2)

    static_result = _analyze_file_static(path, content)
    merged = _merge_file_analyses(llm_result, static_result)
    if not merged.get("purpose") and static_result.get("purpose"):
        merged["purpose"] = static_result["purpose"]
    return merged


def _normalize_suggested_answer(raw: dict | None, allowed: list[str] | None = None) -> dict:
    if not isinstance(raw, dict):
        return _empty_suggested_answer()
    value = raw.get("value")
    if value is not None:
        value = _coerce_text(value)
    if value is not None and allowed is not None and value not in allowed:
        value = None
    confidence = raw.get("confidence", "low")
    if confidence not in ("high", "medium", "low"):
        confidence = "low"
    return {
        "value": value,
        "confidence": confidence,
        "reasoning": str(raw.get("reasoning") or ""),
    }


def _normalize_synthesis(parsed: dict) -> dict:
    empty = _empty_synthesis()
    suggested = parsed.get("suggested_answers") if isinstance(parsed.get("suggested_answers"), dict) else {}

    return {
        "product_summary": _coerce_text(parsed.get("product_summary")) or "",
        "product_description": (
            _coerce_text(parsed.get("product_description"))
            or _coerce_text(parsed.get("product_summary"))
            or ""
        ),
        "ai_features": _coerce_str_list(parsed.get("ai_features")),
        "data_flows": _coerce_str_list(parsed.get("data_flows")),
        "user_facing_assessment": _coerce_text(parsed.get("user_facing_assessment")) or "",
        "uncertainties": _coerce_str_list(parsed.get("uncertainties")),
        "suggested_answers": {
            "project_stage": _normalize_suggested_answer(
                suggested.get("project_stage"), PROJECT_STAGE_OPTIONS
            ),
            "sector": _normalize_suggested_answer(suggested.get("sector"), SECTOR_OPTIONS),
            "ai_use_case": _normalize_suggested_answer(
                suggested.get("ai_use_case"), AI_USE_CASE_OPTIONS
            ),
            "company_size": {
                "value": None,
                "confidence": "low",
                "reasoning": (
                    suggested.get("company_size", {}).get("reasoning")
                    if isinstance(suggested.get("company_size"), dict)
                    else "Company size cannot be reliably inferred from code — always ask the user"
                ),
            },
            "mau": {
                "value": None,
                "confidence": "low",
                "reasoning": (
                    suggested.get("mau", {}).get("reasoning")
                    if isinstance(suggested.get("mau"), dict)
                    else "User counts cannot be inferred from code — always ask the user"
                ),
            },
        },
    }


def build_fallback_synthesis(
    per_file_results: list[dict],
    rule_based_state: dict,
    error: str | None = None,
) -> dict:
    """Build a readable synthesis from scan results when the synthesis API call fails."""
    ctx = rule_based_state.get("project_context", {})
    name = ctx.get("name", "this project")
    readme = (ctx.get("readme") or "").strip()
    readme_lines = [
        line.strip()
        for line in readme.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    readme_intro = " ".join(readme_lines[:3])[:400] if readme_lines else ""

    purposes: list[str] = []
    ai_features: list[str] = []
    data_flows: list[str] = []
    for item in per_file_results:
        path = item.get("path", "")
        purpose = _coerce_text(item.get("purpose"))
        if purpose:
            purposes.append(f"{path}: {purpose}")
        ai = _coerce_text(item.get("ai_or_automated_processing"))
        if ai:
            ai_features.append(f"{path}: {ai}")
        for svc in item.get("external_services") or []:
            svc_text = _coerce_text(svc)
            if svc_text:
                data_flows.append(f"{path} → {svc_text}")
        for field in item.get("data_handled") or []:
            field_text = _coerce_text(field)
            if field_text:
                data_flows.append(f"{path} processes: {field_text}")

    flags: list[str] = []
    if rule_based_state.get("uses_ai", {}).get("value"):
        flags.append("AI/ML libraries detected")
    if rule_based_state.get("is_platform", {}).get("value"):
        flags.append("platform/web service signals")
    if rule_based_state.get("sensitive_data", {}).get("value"):
        flags.append("sensitive data fields detected")

    if readme_intro:
        product_summary = f"{name}: {readme_intro}"
    elif purposes:
        product_summary = f"{name} — " + "; ".join(purposes[:3])
    else:
        product_summary = f"{name} was scanned for EU compliance signals."
    if flags:
        product_summary += " Detected: " + ", ".join(flags) + "."

    product_description = (
        f"We reviewed **{len(per_file_results)}** key file(s) in **{name}**. "
        + (
            readme_intro
            if readme_intro
            else "No README summary was available, so this description is based on automated file and dependency scanning."
        )
        + " This is a fallback summary because the full AI synthesis step could not complete."
    )

    user_facing = "Unclear from automated scan alone."
    for item in per_file_results:
        if item.get("user_facing") is True:
            user_facing = "Likely user-facing based on per-file analysis."
            break
        if item.get("user_facing") is False:
            user_facing = "Likely internal/backend tooling based on per-file analysis."

    uncertainties: list[str] = []
    if rule_based_state.get("sensitive_data", {}).get("value"):
        uncertainties.append(
            "Is this real personal data from actual users, or just test/sample data? "
            "(e.g. real users / internal testing only)"
        )
    elif rule_based_state.get("uses_ai", {}).get("value"):
        uncertainties.append(
            "In one line, what does the AI feature actually do for your users? "
            "(e.g. suggests replies in chat)"
        )

    if not ai_features and rule_based_state.get("uses_ai", {}).get("value"):
        ai_features = ["AI/ML libraries detected in dependency scan"]

    result = _normalize_synthesis({
        "product_summary": product_summary,
        "product_description": product_description,
        "ai_features": ai_features[:8],
        "data_flows": _dedupe_preserve_order(data_flows)[:8],
        "user_facing_assessment": user_facing,
        "uncertainties": uncertainties,
        "suggested_answers": {},
    })
    result["_used_fallback"] = True
    if error:
        result["_synthesis_error"] = error
    return result


def synthesize_analysis(per_file_results: list[dict], rule_based_state: dict) -> dict:
    """Reduce step: synthesize per-file analyses into product understanding."""
    profile_summary = build_profile_text(rule_based_state)
    files_json = json.dumps(per_file_results, indent=2)
    uses_ai = rule_based_state.get("uses_ai", {}).get("value", False)

    stage_opts = "\n".join(f'    - "{o}"' for o in PROJECT_STAGE_OPTIONS)
    sector_opts = "\n".join(f'    - "{o}"' for o in SECTOR_OPTIONS)
    ai_opts = "\n".join(f'    - "{o}"' for o in AI_USE_CASE_OPTIONS)

    ai_use_case_block = ""
    if uses_ai:
        ai_use_case_block = f"""
    "ai_use_case": {{
      "value": "<one of the ai_use_case options below, or null>",
      "confidence": "high" | "medium" | "low",
      "reasoning": "brief explanation"
    }},"""

    prompt = f"""You are analyzing a codebase for EU regulatory compliance (AI Act, GDPR, NIS2, DSA).
Synthesize the per-file analyses and rule-based scan summary below.

Return ONLY valid JSON:
{{
  "product_summary": "2-3 sentence description of what this product/project does",
  "product_description": "A friendly 2-4 sentence description of what this project/app does, written for the team that built it to confirm — be specific and reference what was actually found, but written conversationally, not legally",
  "ai_features": ["distinct AI/automated features, each with a brief description"],
  "data_flows": ["notable data flows, e.g. 'patient data -> OpenAI API for recommendations'"],
  "user_facing_assessment": "best assessment of whether and how this is user-facing",
  "uncertainties": ["AT MOST 2 short, plain-language questions a non-technical founder can answer in one line. No legal jargon, no file paths. Refer to the feature in everyday words and add a tiny example answer in parentheses, e.g. 'Do real patients use the symptom checker, or is it just test data? (e.g. live patients / internal testing only)'. Skip generic questions like company size."],
  "suggested_answers": {{
    "project_stage": {{
      "value": "<one of the project_stage options below, or null>",
      "confidence": "high" | "medium" | "low",
      "reasoning": "brief explanation"
    }},
    "sector": {{
      "value": "<one of the sector options below, or null>",
      "confidence": "high" | "medium" | "low",
      "reasoning": "brief explanation"
    }},{ai_use_case_block}
    "company_size": {{
      "value": null,
      "confidence": "low",
      "reasoning": "Company size cannot be reliably inferred from code — always ask the user"
    }},
    "mau": {{
      "value": null,
      "confidence": "low",
      "reasoning": "User counts cannot be inferred from code — always ask the user"
    }}
  }}
}}

project_stage options:
{stage_opts}

sector options:
{sector_opts}
{f"ai_use_case options:{chr(10)}{ai_opts}" if uses_ai else ""}

IMPORTANT for suggested_answers:
- For company_size and mau, ALWAYS return value: null and confidence: "low" — never guess these.
- For project_stage, sector, and ai_use_case, only return "high" or "medium" confidence if there is clear evidence (e.g. README badge "v0.1.0 - under development" supports project_stage at high confidence; empty/template README supports low confidence).
- suggested_answers values MUST exactly match one of the option strings above, or be null.

RULE-BASED SCAN SUMMARY:
{profile_summary}

PER-FILE ANALYSES:
{files_json}"""

    try:
        raw = _mistral_complete(
            [{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            timeout_ms=180000,
            label="Deep analysis synthesis",
        )
        parsed = _parse_json_response(raw)
        if not parsed:
            msg = "empty or unparseable JSON response"
            print(f"      Deep analysis synthesis: {msg}.")
            return build_fallback_synthesis(per_file_results, rule_based_state, error=msg)
        return _normalize_synthesis(_extract_synthesis_dict(parsed))
    except Exception as exc:
        print(f"      Deep analysis synthesis failed: {exc}")
        return build_fallback_synthesis(per_file_results, rule_based_state, error=str(exc))


def review_synthesis(
    synthesis: dict,
    per_file_results: list[dict],
    rule_based_state: dict,
) -> dict:
    """Self-review pass: correct unsupported or overconfident claims in the synthesis."""
    profile_summary = build_profile_text(rule_based_state)
    synthesis_json = json.dumps(synthesis, indent=2)
    files_json = json.dumps(per_file_results, indent=2)

    prompt = f"""You are reviewing an AI-generated analysis of a codebase for accuracy.
For each claim in the synthesis below (product_description, ai_features, data_flows,
user_facing_assessment, suggested_answers), check whether it's directly supported by the
per-file evidence or rule-based findings provided.

Return a corrected version of the synthesis as valid JSON with the SAME structure as the input:
- Claims with NO supporting evidence should be removed or rephrased as speculative
  (e.g. change 'this is a healthcare app' to 'this MAY be healthcare-related, based on field names like diagnosis_notes — but the actual domain isn't confirmed by the code')
- Confidence levels in suggested_answers should be adjusted DOWN if the reasoning doesn't hold up
- Anything well-supported stays as-is
- For company_size and mau, always keep value: null and confidence: "low"
- suggested_answers values must exactly match the allowed option strings from the original synthesis, or be null

SYNTHESIS TO REVIEW:
{synthesis_json}

RULE-BASED SCAN SUMMARY:
{profile_summary}

PER-FILE EVIDENCE:
{files_json}"""

    try:
        raw = _mistral_complete(
            [{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            timeout_ms=180000,
            label="Synthesis self-review",
        )
        parsed = _parse_json_response(raw)
        if not parsed:
            print("      Synthesis self-review: empty response — keeping original synthesis.")
            return synthesis
        corrected = _normalize_synthesis(_extract_synthesis_dict(parsed))
        if not has_synthesis_content(corrected) and has_synthesis_content(synthesis):
            print("      Synthesis self-review: corrected output was empty — keeping original synthesis.")
            return synthesis
        return corrected
    except Exception as exc:
        print(f"      Synthesis self-review failed: {exc}")
        return synthesis


def run_deep_analysis(
    repo_dir: str,
    file_tree: list[dict],
    evidence: dict,
    sensitive: dict,
    rule_based_state: dict,
    max_files: int = 8,
    progress_callback=None,
) -> dict:
    """Chain key-file selection, per-file analysis, synthesis, and self-review."""
    key_files = select_key_files(file_tree, evidence, sensitive, max_files=max_files)
    per_file_results: list[dict] = []
    root = Path(repo_dir)

    total = len(key_files)
    for i, rel_path in enumerate(key_files, 1):
        msg = f"Analyzing file {i}/{total}: {rel_path}..."
        if progress_callback:
            progress_callback(msg)
        else:
            print(msg)

        file_path = root / rel_path
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            content = ""

        analysis = analyze_file(rel_path, content)
        per_file_results.append({"path": rel_path, **analysis})

    synthesis = synthesize_analysis(per_file_results, rule_based_state)

    if synthesis.get("_used_fallback"):
        if progress_callback:
            progress_callback("Using fallback summary (AI synthesis unavailable)…")
        else:
            print("Using fallback summary (AI synthesis unavailable)…")
        final = synthesis
    else:
        if progress_callback:
            progress_callback("Reviewing analysis for accuracy…")
        else:
            print("Reviewing analysis for accuracy…")
        final = review_synthesis(synthesis, per_file_results, rule_based_state)

    final["_meta"] = {
        "files_analyzed": len(per_file_results),
        "key_files": key_files,
        "used_fallback": bool(final.get("_used_fallback")),
    }
    return final


if __name__ == "__main__":
    import sys

    from eu_compliance import build_state, scan_project_context, scan_repo, scan_sensitive_fields

    if len(sys.argv) < 2:
        print("Usage: python deep_analysis.py /path/to/project [max_files]")
        sys.exit(1)

    repo = str(Path(sys.argv[1]).resolve())
    max_f = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    print(f"Deep analysis of: {repo}")
    context = scan_project_context(repo)
    evidence, snippets = scan_repo(repo)
    sensitive = scan_sensitive_fields(repo)
    state = build_state(evidence, snippets, sensitive, context)
    tree = build_file_tree(repo)

    synthesis = run_deep_analysis(repo, tree, evidence, sensitive, state, max_files=max_f)
    print("\n── Synthesis ──")
    print(json.dumps(synthesis, indent=2))
