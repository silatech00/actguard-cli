"""Deterministic EU hosting provider matcher."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_CATALOG_PATH = Path(__file__).resolve().parent / "providers.yaml"


@lru_cache(maxsize=1)
def load_providers() -> dict[str, dict[str, Any]]:
    with _CATALOG_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("providers", {})


def _score_provider(provider_id: str, meta: dict, profile: dict) -> tuple[int, list[str]]:
    score = 50
    evidence: list[str] = []
    app_model = profile.get("app_model", "unknown")
    fits = set(meta.get("fits") or [])
    not_fit = set(meta.get("not_fit") or [])
    tier = meta.get("residency_tier", 3)

    if app_model in fits:
        score += 25
        evidence.append(f"app_model={app_model}")
    elif app_model == "unknown":
        score += 5
    else:
        score -= 15

    if profile.get("container_ready") and "docker" in fits:
        score += 15
        evidence.append("Dockerfile")

    if profile.get("async_workers") and "celery_workers" in not_fit:
        score -= 40
        evidence.append("async_workers incompatible")

    if profile.get("async_workers") and "celery_workers" in fits:
        score += 15

    if app_model == "streamlit" and "streamlit" in not_fit:
        score -= 50
    if app_model == "streamlit" and "streamlit" in fits:
        score += 20
        evidence.append("streamlit")

    if profile.get("gpu_inference") and "gpu_inference" in fits:
        score += 15
    if profile.get("gpu_inference") and "gpu_inference" in not_fit:
        score -= 30

    if app_model == "next_fullstack" and "next_fullstack" in fits:
        score += 20
        evidence.append("next.js")

    if app_model == "split_monorepo":
        if provider_id in ("sliplane", "hetzner", "fly_io", "railway"):
            score += 10
            evidence.append("split_monorepo")

    vendors = profile.get("detected_vendors") or []
    if "boto3" in vendors and provider_id == "aws_eu":
        score += 25
        evidence.append("boto3 detected")
    if "google_cloud" in vendors and provider_id == "gcp_eu":
        score += 25
        evidence.append("google_cloud detected")

    if tier == 1:
        score += 10
    elif tier == 3:
        score -= 5

  # Prefer EU-native for young startups unless locked into hyperscaler
    if tier == 1 and not (set(vendors) & {"boto3", "google_cloud", "azure"}):
        score += 8

    for pkg_ev in (profile.get("package_evidence") or [])[:5]:
        if any(k in pkg_ev.lower() for k in ("fastapi", "postgres", "docker")):
            if provider_id == "sliplane" and "fastapi" in pkg_ev.lower():
                score += 5
            break

    return max(0, min(100, score)), evidence


def _suggest_architecture(profile: dict, primary_id: str) -> dict[str, str]:
    app_model = profile.get("app_model", "unknown")
    monorepo = profile.get("monorepo")
    persistence = profile.get("persistence") or []

    if app_model == "split_monorepo" and monorepo:
        fe = monorepo.get("frontend", "web/")
        be = monorepo.get("backend", "api/")
        if primary_id == "vercel":
            return {
                "frontend": f"Vercel (fra1) — {fe}",
                "api": f"EU container host — {be}",
                "db": "Managed Postgres in same EU region" if "postgres" in persistence else "N/A",
            }
        return {
            "frontend": f"{primary_id} service — {fe}",
            "api": f"{primary_id} service — {be}",
            "db": "Co-located Postgres on same provider/region" if "postgres" in persistence else "N/A",
        }

    if app_model == "next_fullstack":
        return {
            "frontend": "Vercel fra1 (Next.js)",
            "api": "Next.js API routes on Vercel",
            "db": "Neon/Supabase EU or Vercel Postgres EU" if persistence else "N/A",
        }

    if app_model == "streamlit":
        return {
            "frontend": "N/A",
            "api": "Dedicated container (Sliplane/Hetzner/Fly EU)",
            "db": "Co-located if Postgres detected" if persistence else "N/A",
        }

    if app_model == "python_api":
        return {
            "frontend": "Static CDN or separate frontend host",
            "api": f"Container on {primary_id} EU region",
            "db": "Managed Postgres same region" if "postgres" in persistence else "N/A",
        }

    return {
        "frontend": "Static hosting or framework PaaS",
        "api": "Container or serverless based on stack",
        "db": "EU-region database if persistence detected",
    }


def match_hosting_providers(deploy_profile: dict | None) -> dict:
    """Return ranked hosting shortlist from deploy profile."""
    profile = deploy_profile or {}
    providers = load_providers()
    warnings = list(profile.get("region_warnings") or [])

    if "railway.toml" in (profile.get("existing_deploy_hints") or []):
        content_warning = any("railway.toml" in w for w in warnings)
        if content_warning:
            warnings.append(
                "Railway is a US platform — not EU by default. "
                "Pin each service to europe-west4-drams3a (Amsterdam) if you stay on Railway."
            )

    scored: list[tuple[str, dict, int, list[str]]] = []
    for pid, meta in providers.items():
        score, evidence = _score_provider(pid, meta, profile)
        scored.append((pid, meta, score, evidence))

    scored.sort(key=lambda x: (-x[2], x[1].get("residency_tier", 9)))

    def to_rec(pid: str, meta: dict, score: int, evidence: list[str]) -> dict:
        regions = meta.get("eu_regions") or []
        return {
            "provider": pid,
            "name": meta.get("name", pid),
            "region": regions[0] if regions else "",
            "residency_tier": meta.get("residency_tier"),
            "score": score,
            "evidence": evidence or profile.get("package_evidence", [])[:4],
            "dpa_url": meta.get("dpa_url", ""),
            "notes": meta.get("notes", ""),
            "cost_band": meta.get("cost_band", ""),
            "ops_burden": meta.get("ops_burden", ""),
        }

    if not scored:
        return {
            "primary": None,
            "alternatives": [],
            "warnings": warnings,
            "architecture": {},
            "confidence": profile.get("confidence", "low"),
        }

    primary_id, primary_meta, primary_score, primary_ev = scored[0]
    alternatives = [
        to_rec(pid, meta, score, ev)
        for pid, meta, score, ev in scored[1:3]
    ]

    return {
        "primary": to_rec(primary_id, primary_meta, primary_score, primary_ev),
        "alternatives": alternatives,
        "warnings": warnings,
        "architecture": _suggest_architecture(profile, primary_id),
        "confidence": profile.get("confidence", "medium"),
    }
