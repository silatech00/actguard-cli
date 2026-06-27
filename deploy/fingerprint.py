"""Build deploy profile from codebase scan."""

from __future__ import annotations

import json
import re
from pathlib import Path

from deploy.signals import (
    ANALYTICS_PACKAGES,
    DEPLOY_CONFIG_FILES,
    DEPLOY_PACKAGE_ALIASES,
    DEPLOY_PACKAGE_SIGNALS,
    EU_REGION_PINS,
    VENDOR_PACKAGES,
)
from eu_compliance import _should_skip


def _normalize_pkg(name: str) -> str:
    lower = name.strip().lower()
    if lower in DEPLOY_PACKAGE_ALIASES:
        return DEPLOY_PACKAGE_ALIASES[lower]
    return lower.replace("-", "_").lstrip("@")


def scan_deploy_signals(repo_path: str) -> dict:
    """Scan repo for deploy-relevant packages, configs, and docker metadata."""
    path = Path(repo_path)
    packages: dict[str, list[str]] = {}
    config_files: list[str] = []
    config_contents: dict[str, str] = {}
    docker_meta: dict[str, str] = {}
    package_json_meta: list[dict] = []

    def add_pkg(pkg: str, source: str) -> None:
        if pkg in DEPLOY_PACKAGE_SIGNALS:
            packages.setdefault(pkg, [])
            if source not in packages[pkg]:
                packages[pkg].append(source)

    for req_file in path.rglob("requirements*.txt"):
        if _should_skip(req_file):
            continue
        rel = str(req_file.relative_to(path))
        for line in req_file.read_text(errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            raw = line.split("==")[0].split(">=")[0].split("<=")[0].split("[")[0].strip()
            add_pkg(_normalize_pkg(raw), rel)

    for pkg_json in path.rglob("package.json"):
        if _should_skip(pkg_json) or "node_modules" in pkg_json.parts:
            continue
        try:
            data = json.loads(pkg_json.read_text())
            rel = str(pkg_json.relative_to(path))
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            for dep in deps:
                norm = _normalize_pkg(dep.split("/")[-1] if "/" in dep else dep)
                add_pkg(norm, rel)
            meta: dict = {"path": rel}
            if data.get("engines"):
                meta["engines"] = data["engines"]
            scripts = data.get("scripts") or {}
            if scripts:
                meta["scripts"] = {k: scripts[k] for k in ("build", "start", "dev") if k in scripts}
            if len(meta) > 1:
                package_json_meta.append(meta)
        except Exception:
            pass

    for pyproject in path.rglob("pyproject.toml"):
        if _should_skip(pyproject):
            continue
        content = pyproject.read_text(errors="ignore")
        rel = str(pyproject.relative_to(path))
        for sig in DEPLOY_PACKAGE_SIGNALS:
            if sig.replace("_", "-") in content.lower() or sig in content.lower():
                add_pkg(sig, rel)

    for cfg_name, label in DEPLOY_CONFIG_FILES.items():
        for cfg in path.rglob(cfg_name):
            if _should_skip(cfg):
                continue
            if cfg.name.lower() != cfg_name.lower() and cfg_name != "dockerfile":
                continue
            rel = str(cfg.relative_to(path))
            if label not in config_files:
                config_files.append(label)
            try:
                config_contents[label] = cfg.read_text(errors="ignore")[:4000]
            except Exception:
                pass

    for dockerfile in path.rglob("Dockerfile"):
        if _should_skip(dockerfile):
            continue
        rel = str(dockerfile.relative_to(path))
        if "Dockerfile" not in config_files:
            config_files.append("Dockerfile")
        text = dockerfile.read_text(errors="ignore")
        config_contents["Dockerfile"] = text[:4000]
        from_match = re.search(r"^FROM\s+(\S+)", text, re.MULTILINE | re.IGNORECASE)
        expose_match = re.search(r"^EXPOSE\s+(\d+)", text, re.MULTILINE | re.IGNORECASE)
        cmd_match = re.search(r"^CMD\s+(.+)$", text, re.MULTILINE | re.IGNORECASE)
        docker_meta = {
            "path": rel,
            "base_image": from_match.group(1) if from_match else "",
            "expose": expose_match.group(1) if expose_match else "",
            "cmd": cmd_match.group(1).strip() if cmd_match else "",
        }

    readme_text = ""
    for readme_name in ("README.md", "readme.md", "README.rst"):
        readme = path / readme_name
        if readme.exists() and not _should_skip(readme):
            readme_text = readme.read_text(errors="ignore").lower()
            break

    if "sliplane" in readme_text and "sliplane" not in config_files:
        config_files.append("sliplane (README)")

    return {
        "packages": packages,
        "config_files": config_files,
        "config_contents": config_contents,
        "docker_meta": docker_meta,
        "package_json_meta": package_json_meta,
    }


def _detect_monorepo(path: Path, deploy_scan: dict) -> dict | None:
    packages = deploy_scan["packages"]
    has_web = (path / "web").is_dir() and (path / "web" / "package.json").exists()
    has_api = (path / "api").is_dir()
    has_frontend = has_web or "next" in packages or "react" in packages
    has_backend = has_api or "fastapi" in packages or "django" in packages or "flask" in packages
    if has_web and has_api:
        return {"frontend": "web/", "backend": "api/"}
    if has_frontend and has_backend:
        frontend = "web/" if has_web else "frontend/"
        backend = "api/" if has_api else "backend/"
        return {"frontend": frontend, "backend": backend}
    return None


def _infer_app_model(packages: dict, deploy_scan: dict, monorepo: dict | None) -> str:
    pkg_set = set(packages.keys())
    if monorepo:
        return "split_monorepo"
    if "streamlit" in pkg_set and not monorepo:
        # Legacy Streamlit-only apps (not a monorepo with web/ + api/)
        has_only_streamlit_entry = "streamlit" in pkg_set and "fastapi" not in pkg_set and "next" not in pkg_set
        if has_only_streamlit_entry:
            return "streamlit"
    if "next" in pkg_set:
        scripts = deploy_scan.get("package_json_meta") or []
        has_api_routes = any(
            "next" in str(m.get("scripts", {})) for m in scripts
        )
        if "fastapi" in pkg_set or "django" in pkg_set or "flask" in pkg_set:
            return "split_monorepo"
        return "next_fullstack" if has_api_routes else "static_spa"
    if "django" in pkg_set:
        return "django_monolith"
    if "fastapi" in pkg_set or "flask" in pkg_set or "starlette" in pkg_set:
        return "python_api"
    if "react" in pkg_set or "express" in pkg_set:
        return "static_spa"
    return "unknown"


def _check_eu_region_pins(config_contents: dict) -> list[str]:
    warnings: list[str] = []
    for cfg, pins in EU_REGION_PINS.items():
        label = DEPLOY_CONFIG_FILES.get(cfg, cfg)
        content = config_contents.get(label, "")
        if not content:
            continue
        lower = content.lower()
        if not any(p.lower() in lower for p in pins):
            warnings.append(f"{label} present but no EU region pin detected ({', '.join(pins)})")
    return warnings


def build_deploy_profile(
    repo_path: str,
    evidence: dict | None = None,
    context: dict | None = None,
) -> dict:
    """Build structured deploy profile for hosting matcher."""
    deploy_scan = scan_deploy_signals(repo_path)
    packages = deploy_scan["packages"]
    pkg_set = set(packages.keys())
    path = Path(repo_path)

    persistence: list[str] = []
    for db_pkg in ("psycopg", "psycopg2", "asyncpg", "supabase", "mongoose", "pymongo", "prisma"):
        if db_pkg in pkg_set:
            persistence.append("postgres" if db_pkg != "mongoose" and db_pkg != "pymongo" else "mongodb")
    if "redis" in pkg_set:
        persistence.append("redis")

    vector_store = None
    for vs in ("chromadb", "qdrant_client", "pinecone", "vllm", "ollama"):
        if vs in pkg_set:
            vector_store = vs
            break

    monorepo = _detect_monorepo(path, deploy_scan)
    app_model = _infer_app_model(packages, deploy_scan, monorepo)

    runtimes: list[str] = []
    if any(p in pkg_set for p in ("fastapi", "django", "flask", "streamlit", "celery")):
        runtimes.append("python")
    if any(p in pkg_set for p in ("next", "react", "express", "nuxt", "remix")):
        runtimes.append("node")

    detected_vendors = sorted(pkg_set & VENDOR_PACKAGES)
    analytics_libs = sorted(pkg_set & ANALYTICS_PACKAGES)

    region_warnings = _check_eu_region_pins(deploy_scan["config_contents"])
    existing_hints = list(deploy_scan["config_files"])

    confidence = "high"
    if app_model == "unknown":
        confidence = "low"
    elif not packages and not existing_hints:
        confidence = "low"
    elif app_model == "split_monorepo" and not monorepo:
        confidence = "medium"

    package_evidence = [
        f"{pkg} ({DEPLOY_PACKAGE_SIGNALS[pkg][1]}) — {sources[0]}"
        for pkg, sources in sorted(packages.items())
        if sources
    ][:20]

    return {
        "app_model": app_model,
        "runtimes": runtimes,
        "persistence": list(dict.fromkeys(persistence)),
        "async_workers": bool(pkg_set & {"celery", "rq", "bullmq"}),
        "websockets": "socketio" in pkg_set,
        "gpu_inference": bool(pkg_set & {"torch", "vllm", "tensorflow"}),
        "vector_store": vector_store,
        "container_ready": "Dockerfile" in existing_hints,
        "monorepo": monorepo,
        "existing_deploy_hints": existing_hints,
        "detected_vendors": detected_vendors,
        "analytics_libs": analytics_libs,
        "docker_meta": deploy_scan.get("docker_meta") or {},
        "package_evidence": package_evidence,
        "region_warnings": region_warnings,
        "confidence": confidence,
    }
