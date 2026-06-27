"""
EU Compliance Agent - MVP v0.1
Analyzes a codebase and generates a compliance report for EU AI Act, NIS2, and DSA.

Preferred entry point: actguard scan / actguard report (see README.md)

Legacy usage:
    python eu_compliance.py /path/to/your/project
"""

import ast
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from xml.sax.saxutils import escape
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env")

# Mistral Large 3 — use the -latest alias so the script tracks the newest release
MISTRAL_MODEL = "mistral-large-latest"
# SDK default is 60s — large grounded reports often need longer
MISTRAL_TIMEOUT_MS = int(os.environ.get("MISTRAL_TIMEOUT_MS", "300000"))  # 5 min
MISTRAL_REPORT_TIMEOUT_MS = int(os.environ.get("MISTRAL_REPORT_TIMEOUT_MS", "600000"))  # 10 min

SUPPORTED_LANGUAGES = [
    "English",
    "French",
    "German",
    "Spanish",
    "Italian",
    "Dutch",
    "Polish",
    "Portuguese",
    "Romanian",
    "Swedish",
]

DRAFT_LEGAL_DISCLAIMER = """## DRAFT FOR LEGAL REVIEW
This is an AI-generated starting point based on automated codebase analysis. It is NOT a finished legal document. A qualified lawyer must review, complete the bracketed placeholders, and adapt this before publication. Inaccurate privacy policies create legal risk - do not publish without review."""

# Dependency / cache dirs — skip anywhere in the tree
SKIP_DIRS = {
    "venv", "env", ".venv", "__pycache__", "node_modules", ".git",
    "dist", "build", "site-packages", ".cursor", ".streamlit",
}

# When auditing a parent folder, skip entire tool-repo subtrees (e.g. EU AUDIT/ACTGUARD/…)
TOOL_REPO_DIR_NAMES = frozenset({"ACTGUARD", "actguard", "eu-compliance-agent"})

# ActGuard install internals — skip only under SCRIPT_DIR, not sibling test projects
TOOL_INTERNAL_DIRS = frozenset({
    "api", "legal_rag", "actguard", "mcp_server", "readiness", "deploy",
    "parsing", "export", "scanner", "tests", "archive", "skills", "docs",
    "legal_texts", ".github", ".pytest_cache",
})

_scan_repo_root: ContextVar[Path | None] = ContextVar("scan_repo_root", default=None)
EXCLUDE_FILES = {"eu_compliance.py", "compliance_report.md"}
MAX_SNIPPETS_PER_PKG = 5
MAX_SENSITIVE_FINDINGS = 15

# ─────────────────────────────────────────────────────────────
# 1. SIGNAL MAP
# Maps library names → (compliance_field, confidence, description)
# ─────────────────────────────────────────────────────────────
SIGNALS = {
    # EU AI Act triggers
    "torch":            ("uses_ai",      0.95, "PyTorch ML framework"),
    "tensorflow":       ("uses_ai",      0.95, "TensorFlow ML framework"),
    "keras":            ("uses_ai",      0.90, "Keras deep learning"),
    "sklearn":          ("uses_ai",      0.85, "scikit-learn ML"),
    "scikit_learn":     ("uses_ai",      0.85, "scikit-learn ML"),
    "transformers":     ("uses_ai",      0.98, "HuggingFace Transformers"),
    "openai":           ("uses_ai",      0.95, "OpenAI API"),
    "anthropic":        ("uses_ai",      0.95, "Anthropic API"),
    "mistralai":        ("uses_ai",      0.95, "Mistral API"),
    "langchain":        ("uses_ai",      0.95, "LangChain framework"),
    "llama_index":      ("uses_ai",      0.95, "LlamaIndex framework"),
    "spacy":            ("uses_ai",      0.90, "spaCy NLP"),
    "presidio_analyzer": ("uses_ai",     0.92, "Presidio PII analyzer"),
    "presidio_anonymizer": ("uses_ai",   0.92, "Presidio PII anonymizer"),
    "xgboost":          ("uses_ai",      0.85, "XGBoost ML"),
    "lightgbm":         ("uses_ai",      0.85, "LightGBM ML"),
    "diffusers":        ("uses_ai",      0.98, "HuggingFace Diffusers (image gen)"),
    "sentence_transformers": ("uses_ai", 0.90, "Sentence Transformers"),
    # High-risk AI signals (biometric, etc.)
    "face_recognition": ("high_risk_ai", 0.99, "facial recognition library"),
    "deepface":         ("high_risk_ai", 0.99, "DeepFace biometrics"),
    "mediapipe":        ("high_risk_ai", 0.85, "MediaPipe pose/face detection"),
    # DSA platform triggers
    "streamlit":        ("is_platform",  0.85, "Streamlit web app"),
    "flask":            ("is_platform",  0.70, "Flask web framework"),
    "fastapi":          ("is_platform",  0.70, "FastAPI web framework"),
    "django":           ("is_platform",  0.80, "Django web framework"),
    "starlette":        ("is_platform",  0.65, "Starlette ASGI framework"),
    "stripe":           ("is_platform",  0.85, "Stripe payments"),
    "express":          ("is_platform",  0.80, "Express.js web framework"),
    "next":             ("is_platform",  0.75, "Next.js framework"),
    "react":            ("is_platform",  0.60, "React frontend"),
    # NIS2 / security signals
    "cryptography":     ("has_security", 0.80, "Python cryptography library"),
    "bcrypt":           ("has_security", 0.90, "bcrypt password hashing"),
    "jose":             ("has_security", 0.80, "JOSE/JWT library"),
    "pyjwt":            ("has_security", 0.80, "PyJWT"),
    "passlib":          ("has_security", 0.80, "Passlib auth"),
    "keyring":          ("has_security", 0.75, "OS keyring for secrets"),
    "boto3":            ("cloud_infra",  0.85, "AWS SDK"),
    "azure":            ("cloud_infra",  0.85, "Azure SDK"),
    "google_cloud":     ("cloud_infra",  0.85, "Google Cloud SDK"),
}

# Package name aliases in requirements.txt / imports
PACKAGE_ALIASES = {
    "scikit-learn": "sklearn",
    "presidio-analyzer": "presidio_analyzer",
    "presidio-anonymizer": "presidio_anonymizer",
    "python-jose": "jose",
    "google-cloud-storage": "google_cloud",
}

# ─────────────────────────────────────────────────────────────
# 2. SCANNER - reads dependencies and Python/JS imports
# ─────────────────────────────────────────────────────────────
@contextmanager
def scan_context(repo_path: str | Path):
    """Set the active scan root so _should_skip can distinguish tool internals."""
    token = _scan_repo_root.set(Path(repo_path).resolve())
    try:
        yield
    finally:
        _scan_repo_root.reset(token)


def _should_skip(path: Path) -> bool:
    resolved = path.resolve()
    if any(part in SKIP_DIRS for part in resolved.parts):
        return True

    repo_root = _scan_repo_root.get()
    if repo_root is not None:
        try:
            rel = resolved.relative_to(repo_root)
            if rel.parts and rel.parts[0] in TOOL_REPO_DIR_NAMES:
                return True
        except ValueError:
            pass

    try:
        rel_tool = resolved.relative_to(SCRIPT_DIR)
    except ValueError:
        return resolved.name in EXCLUDE_FILES

    if not rel_tool.parts:
        return resolved.name in EXCLUDE_FILES
    return rel_tool.parts[0] in TOOL_INTERNAL_DIRS or resolved.name in EXCLUDE_FILES


def _normalize_pkg(name: str) -> str:
    norm = name.strip().lower().replace("-", "_")
    return PACKAGE_ALIASES.get(name.strip().lower(), norm)


def scan_repo(repo_path: str) -> dict:
    """
    Scans a project directory for compliance-relevant signals.
    Returns: dict of { library_name: [list of source locations] }
    """
    path = Path(repo_path)
    if not path.exists():
        print(f"\nError: path does not exist: {repo_path}")
        sys.exit(1)

    evidence = {}
    snippets = {}

    def add_evidence(pkg: str, source: str, snippet: str = ""):
        if pkg not in evidence:
            evidence[pkg] = []
        if source not in evidence[pkg]:
            evidence[pkg].append(source)
        if snippet:
            snippets.setdefault(pkg, [])
            if len(snippets[pkg]) < MAX_SNIPPETS_PER_PKG and (source, snippet) not in snippets[pkg]:
                snippets[pkg].append((source, snippet))

    # --- requirements*.txt ---
    for req_file in path.rglob("requirements*.txt"):
        if _should_skip(req_file):
            continue
        for line in req_file.read_text(errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("http"):
                continue
            raw_pkg = line.split("==")[0].split(">=")[0].split("<=")[0].split("[")[0].strip()
            pkg = _normalize_pkg(raw_pkg)
            if pkg in SIGNALS:
                rel = str(req_file.relative_to(path))
                add_evidence(pkg, rel)

    # --- package.json (all levels) ---
    for pkg_json in path.rglob("package.json"):
        if _should_skip(pkg_json):
            continue
        try:
            data = json.loads(pkg_json.read_text())
            all_deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            rel = str(pkg_json.relative_to(path))
            for dep in all_deps:
                norm = _normalize_pkg(dep.lstrip("@").split("/")[-1])
                if norm in SIGNALS:
                    add_evidence(norm, rel)
        except Exception:
            pass

    # --- pyproject.toml ---
    for pyproject in path.rglob("pyproject.toml"):
        if _should_skip(pyproject):
            continue
        content = pyproject.read_text(errors="ignore")
        rel = str(pyproject.relative_to(path))
        for sig in SIGNALS:
            if sig.replace("_", "-") in content or sig in content:
                add_evidence(sig, rel)

    # --- Python imports via AST ---
    for py_file in path.rglob("*.py"):
        if _should_skip(py_file) or py_file.name in EXCLUDE_FILES:
            continue
        try:
            source_code = py_file.read_text(encoding="utf-8", errors="ignore")
            source_lines = source_code.splitlines()
            tree = ast.parse(source_code)
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0].lower() for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module.split(".")[0].lower()]
                for name in names:
                    norm = _normalize_pkg(name)
                    if norm in SIGNALS:
                        rel_path = str(py_file.relative_to(path))
                        snippet = source_lines[node.lineno - 1].strip() if 0 < node.lineno <= len(source_lines) else ""
                        add_evidence(norm, f"{rel_path}:{node.lineno}", snippet)
        except Exception:
            continue

    # --- JS/TS imports ---
    js_import = re.compile(r"""(?:import\s+.*?from\s+['"]([^'"]+)['"]|require\(['"]([^'"]+)['"]\))""")
    for js_file in path.rglob("*"):
        if js_file.suffix.lower() not in {".js", ".ts", ".tsx", ".jsx"}:
            continue
        if _should_skip(js_file) or js_file.name in EXCLUDE_FILES:
            continue
        try:
            for i, line in enumerate(js_file.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                for match in js_import.finditer(line):
                    mod = (match.group(1) or match.group(2) or "").split("/")[0]
                    norm = _normalize_pkg(mod.lstrip("@"))
                    if norm in SIGNALS:
                        rel_path = str(js_file.relative_to(path))
                        add_evidence(norm, f"{rel_path}:{i}", line.strip())
        except Exception:
            continue

    return evidence, snippets


# ─────────────────────────────────────────────────────────────
# 2b. SENSITIVE DATA SCANNER
# Looks for variable/field/column names that suggest special
# category data under GDPR Art. 9 / AI Act Annex III triggers.
# ─────────────────────────────────────────────────────────────
SENSITIVE_FIELD_KEYWORDS = {
    "health":            "Health data (GDPR Art. 9 / AI Act Annex III health systems)",
    "diagnosis":         "Medical diagnosis data (high-risk AI signal)",
    "medical":           "Medical data (GDPR Art. 9)",
    "biometric":         "Biometric data (GDPR Art. 9 / AI Act Art. 5 prohibited uses)",
    "fingerprint":       "Biometric identifier",
    "face_id":           "Biometric identifier",
    "genetic":           "Genetic data (GDPR Art. 9)",
    "ethnicity":         "Racial/ethnic origin (GDPR Art. 9)",
    "race":              "Racial/ethnic origin (GDPR Art. 9)",
    "religion":          "Religious belief (GDPR Art. 9)",
    "sexual_orientation": "Sexual orientation (GDPR Art. 9)",
    "political":         "Political opinion (GDPR Art. 9)",
    "ssn":               "National ID / social security number",
    "social_security":   "National ID / social security number",
    "passport":          "Government ID document",
    "national_id":       "Government ID document",
    "credit_score":      "Creditworthiness data (AI Act Annex III financial services)",
    "criminal":          "Criminal record data (GDPR Art. 10)",
    "minor":             "Data relating to minors (GDPR special protections)",
    "child_data":        "Data relating to minors (GDPR special protections)",
    "geolocation":       "Location/geolocation data",
    "gps":               "Location/geolocation data",
    "latitude":          "Location/geolocation data",
    "longitude":         "Location/geolocation data",
}

# Deterministic Annex III / GDPR mapping from sensitive-data keywords
ANNEX_III_MAPPING: dict[str, tuple[str | None, str, str]] = {
    "biometric": (
        "Annex III(1) - Biometric identification and categorisation",
        "Art. 6(2), Annex III(1)",
        "Biometric identification systems are high-risk unless used solely for "
        "identity verification (Art. 6(3) exception may apply)",
    ),
    "fingerprint": (
        "Annex III(1) - Biometric identification and categorisation",
        "Art. 6(2), Annex III(1)",
        "Biometric identification systems are high-risk unless used solely for "
        "identity verification (Art. 6(3) exception may apply)",
    ),
    "face_id": (
        "Annex III(1) - Biometric identification and categorisation",
        "Art. 6(2), Annex III(1)",
        "Biometric identification systems are high-risk unless used solely for "
        "identity verification (Art. 6(3) exception may apply)",
    ),
    "credit_score": (
        "Annex III(5)(b) - Creditworthiness assessment",
        "Annex III(5)(b)",
        "Credit scoring AI is explicitly listed as high-risk",
    ),
    "health": (
        "Possible Annex III(5) - Essential services (if used for eligibility/benefit decisions)",
        "Annex III(5)",
        "Health data processing for AI-driven recommendations may fall under "
        "Annex III(5) if it affects access to insurance, benefits, or essential "
        "services - verify the specific use case",
    ),
    "diagnosis": (
        "Possible Annex III(5) - Essential services (if used for eligibility/benefit decisions)",
        "Annex III(5)",
        "Health data processing for AI-driven recommendations may fall under "
        "Annex III(5) if it affects access to insurance, benefits, or essential "
        "services - verify the specific use case",
    ),
    "medical": (
        "Possible Annex III(5) - Essential services (if used for eligibility/benefit decisions)",
        "Annex III(5)",
        "Health data processing for AI-driven recommendations may fall under "
        "Annex III(5) if it affects access to insurance, benefits, or essential "
        "services - verify the specific use case",
    ),
    "criminal": (
        "Annex III(6) - Law enforcement",
        "Annex III(6)",
        "AI systems used by or for law enforcement involving criminal data are high-risk",
    ),
    "minor": (
        None,
        "GDPR Art. 8",
        "Not an Annex III category itself, but processing children's data triggers "
        "additional GDPR safeguards and AI Act Art. 5 prohibitions on exploiting "
        "vulnerabilities of minors",
    ),
    "child_data": (
        None,
        "GDPR Art. 8",
        "Not an Annex III category itself, but processing children's data triggers "
        "additional GDPR safeguards and AI Act Art. 5 prohibitions on exploiting "
        "vulnerabilities of minors",
    ),
    "ethnicity": (
        "Possible Annex III(1) - if used for categorisation",
        "Annex III(1)",
        "Processing these categories for AI-driven categorisation of individuals "
        "may fall under Annex III(1) - depends on whether the system categorises "
        "people based on these attributes",
    ),
    "race": (
        "Possible Annex III(1) - if used for categorisation",
        "Annex III(1)",
        "Processing these categories for AI-driven categorisation of individuals "
        "may fall under Annex III(1) - depends on whether the system categorises "
        "people based on these attributes",
    ),
    "religion": (
        "Possible Annex III(1) - if used for categorisation",
        "Annex III(1)",
        "Processing these categories for AI-driven categorisation of individuals "
        "may fall under Annex III(1) - depends on whether the system categorises "
        "people based on these attributes",
    ),
    "political": (
        "Possible Annex III(1) - if used for categorisation",
        "Annex III(1)",
        "Processing these categories for AI-driven categorisation of individuals "
        "may fall under Annex III(1) - depends on whether the system categorises "
        "people based on these attributes",
    ),
    "sexual_orientation": (
        "Possible Annex III(1) - if used for categorisation",
        "Annex III(1)",
        "Processing these categories for AI-driven categorisation of individuals "
        "may fall under Annex III(1) - depends on whether the system categorises "
        "people based on these attributes",
    ),
    "ssn": (
        None,
        "GDPR Art. 6/9",
        "Government ID data - not an Annex III trigger itself, but increases GDPR "
        "data minimisation and security obligations",
    ),
    "social_security": (
        None,
        "GDPR Art. 6/9",
        "Government ID data - not an Annex III trigger itself, but increases GDPR "
        "data minimisation and security obligations",
    ),
    "passport": (
        None,
        "GDPR Art. 6/9",
        "Government ID data - not an Annex III trigger itself, but increases GDPR "
        "data minimisation and security obligations",
    ),
    "national_id": (
        None,
        "GDPR Art. 6/9",
        "Government ID data - not an Annex III trigger itself, but increases GDPR "
        "data minimisation and security obligations",
    ),
    "geolocation": (
        None,
        "GDPR Art. 6",
        "Location data processing - relevant to GDPR proportionality but not a "
        "standalone Annex III category",
    ),
    "gps": (
        None,
        "GDPR Art. 6",
        "Location data processing - relevant to GDPR proportionality but not a "
        "standalone Annex III category",
    ),
    "latitude": (
        None,
        "GDPR Art. 6",
        "Location data processing - relevant to GDPR proportionality but not a "
        "standalone Annex III category",
    ),
    "longitude": (
        None,
        "GDPR Art. 6",
        "Location data processing - relevant to GDPR proportionality but not a "
        "standalone Annex III category",
    ),
}

SENSITIVE_SCAN_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".sql"}

DOMAIN_SIGNAL_PATTERNS = [
    (r"\b(médico-?légal|medico-?legal|medical|diagnosis|diagnostic|patient|victim)\b", "Medical/legal health domain"),
    (r"\b(pseudonym|anonymi[sz]|PII|personal\s+data|données\s+personnelles)\b", "Personal data processing"),
    (r"\b(biometric|fingerprint|facial\s+recognition|face\s+id)\b", "Biometric processing"),
    (r"\b(credit\s+score|underwriting)\b", "Financial decisioning"),
    (r"\b(recruitment|hiring|screening|hr_screening)\b", "HR / recruitment screening"),
    (r"\b(eligibility_score|visa_eligibility|check_eligibility|eligibility\s+scor)\b", "Automated eligibility scoring"),
    (r"\b(immigration|asylum|border\s+control|visa\s+eligibility)\b", "Migration / immigration domain"),
    (r"\b(approve|deny|reject).{0,40}\b(user|applicant|candidate)\b", "Automated approve/deny decisions"),
]

SCORES_PEOPLE_PATTERNS = [
    (r"\b(eligibility_score|visa_eligibility_score|credit_score|risk_score)\b", "numeric scoring of individuals"),
    (r"\b(check_eligibility|score_applicant|rank_candidates)\b", "eligibility or ranking function"),
    (r"\b(automated|ai).{0,30}\b(decision|scor|assess|evaluat)\b", "AI-driven assessment of people"),
]


def _is_sensitive_noise(line: str, kw: str) -> bool:
    """Filter false positives from comments, config dicts, and non-English homonyms."""
    stripped = line.strip()
    if stripped.startswith("#") or stripped.startswith("//"):
        return True
    if re.search(rf'["\']{re.escape(kw)}["\']\s*:', line, re.I):
        return True
    if "GDPR Art." in line or "AI Act" in line or "high-risk AI signal" in line:
        return True
    if kw == "location" and re.search(r"\blocation\s+ou\b|\blocation\s+d['\"]", line, re.I):
        return True
    if re.search(r'"LOCATION"\s*:', line):
        return True
    return False


def scan_sensitive_fields(repo_path: str) -> dict:
    """
    Scans source files for variable/field/column names suggesting
    special-category data (GDPR Art. 9/10) or AI Act high-risk triggers.
    Returns: dict of { keyword: [(file:line, snippet), ...] }
    """
    import re
    path = Path(repo_path)
    findings = {}

    # Build a regex that matches any keyword as part of an identifier
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(k) for k in SENSITIVE_FIELD_KEYWORDS) + r")[a-z_]*\b",
        re.IGNORECASE,
    )

    for file in path.rglob("*"):
        if file.suffix.lower() not in SENSITIVE_SCAN_EXTENSIONS:
            continue
        if _should_skip(file) or file.name in EXCLUDE_FILES:
            continue
        try:
            for i, line in enumerate(file.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                for match in pattern.finditer(line):
                    kw = match.group(1).lower()
                    if kw not in SENSITIVE_FIELD_KEYWORDS or _is_sensitive_noise(line, kw):
                        continue
                    rel_path = str(file.relative_to(path))
                    entry = (f"{rel_path}:{i}", line.strip()[:120])
                    findings.setdefault(kw, [])
                    if sum(len(v) for v in findings.values()) < MAX_SENSITIVE_FINDINGS:
                        if len(findings[kw]) < 3 and entry not in findings[kw]:
                            findings[kw].append(entry)
        except Exception:
            continue

    return findings


def scan_project_context(repo_path: str) -> dict:
    """Build a project inventory: structure, README, domain signals, entry points."""
    path = Path(repo_path).resolve()
    context = {
        "path": str(path),
        "name": path.name,
        "readme": "",
        "structure": [],
        "file_counts": {},
        "entry_points": [],
        "domain_signals": [],
        "env_patterns": [],
    }

    for readme_name in ("README.md", "README.rst", "readme.md"):
        readme = path / readme_name
        if readme.exists() and not _should_skip(readme):
            context["readme"] = readme.read_text(encoding="utf-8", errors="ignore")[:2500]
            break

    for item in sorted(path.iterdir())[:40]:
        if item.name.startswith("."):
            continue
        context["structure"].append(f"{item.name}/" if item.is_dir() else item.name)

    for f in path.rglob("*"):
        if not f.is_file() or _should_skip(f):
            continue
        ext = f.suffix.lower() or "(no ext)"
        context["file_counts"][ext] = context["file_counts"].get(ext, 0) + 1

    for ep in ("app.py", "main.py", "server.py", "index.ts", "src/main.py"):
        ep_path = path / ep
        if ep_path.exists() and not _should_skip(ep_path):
            context["entry_points"].append(ep)

    domain_seen = set()

    def _scan_text_for_domain_signals(text: str, rel: str) -> None:
        for pattern, label in DOMAIN_SIGNAL_PATTERNS:
            if label in domain_seen:
                continue
            match = re.search(pattern, text, re.I)
            if match:
                line_no = text[: match.start()].count("\n") + 1
                line = text.splitlines()[line_no - 1].strip()[:120]
                context["domain_signals"].append(f"{label} — {rel}:{line_no}: `{line}`")
                domain_seen.add(label)

    readme_text = context.get("readme") or ""
    if readme_text:
        _scan_text_for_domain_signals(readme_text, "README.md")

    for py_file in path.rglob("*.py"):
        if _should_skip(py_file) or py_file.name in EXCLUDE_FILES:
            continue
        if "fixtures" in py_file.parts or "tests" in py_file.parts:
            continue
        try:
            text = py_file.read_text(encoding="utf-8", errors="ignore")
            rel = str(py_file.relative_to(path))
            _scan_text_for_domain_signals(text, rel)
        except Exception:
            continue

    env_pattern = re.compile(r"(API_KEY|SECRET|PASSWORD|TOKEN|PRIVATE_KEY)\s*[=:]", re.I)
    for cfg in path.rglob("*"):
        if not cfg.is_file() or _should_skip(cfg):
            continue
        if cfg.suffix.lower() not in {".py", ".env", ".example", ".toml", ".yaml", ".yml"} and cfg.name not in {".env.example", ".env"}:
            continue
        if cfg.name in EXCLUDE_FILES:
            continue
        try:
            for i, line in enumerate(cfg.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if env_pattern.search(line):
                    rel = str(cfg.relative_to(path))
                    context["env_patterns"].append(f"{rel}:{i}: `{line.strip()[:80]}`")
                    if len(context["env_patterns"]) >= 8:
                        break
        except Exception:
            continue
        if len(context["env_patterns"]) >= 8:
            break

    return context


# ─────────────────────────────────────────────────────────────
# 3. KNOWLEDGE STATE - structured compliance profile
# ─────────────────────────────────────────────────────────────
def build_state(evidence: dict, snippets: dict, sensitive: dict, context: dict) -> dict:
    """
    Converts raw scan evidence into a structured knowledge state
    with confidence scores per compliance-relevant fact.
    """
    state = {
        # From codebase scan (each is a dict with value/confidence/evidence)
        "uses_ai":      {"value": False, "confidence": 0.0, "evidence": [], "snippets": []},
        "high_risk_ai": {"value": False, "confidence": 0.0, "evidence": [], "snippets": []},
        "is_platform":  {"value": False, "confidence": 0.0, "evidence": [], "snippets": []},
        "has_security": {"value": False, "confidence": 0.0, "evidence": [], "snippets": []},
        "cloud_infra":  {"value": False, "confidence": 0.0, "evidence": [], "snippets": []},
        # Sensitive data findings (GDPR Art. 9/10 / AI Act Annex III signals)
        "sensitive_data": {"value": False, "evidence": []},
        "scores_people": {"value": False, "confidence": 0.0, "evidence": []},
        # Project context from inventory scan
        "project_context": context,
        "domain_signals": list(context.get("domain_signals") or []),
        # From Q&A (strings, filled later)
        "ai_use_case":  "",
        "sector":       "",
        "company_size": "",
        "mau":          "",
        # Deep analysis (filled after rule-based scan)
        "deep_synthesis": None,
        "user_chat_context": [],
    }

    for pkg, sources in evidence.items():
        if pkg not in SIGNALS:
            continue
        field_name, conf, desc = SIGNALS[pkg]
        slot = state[field_name]
        slot["value"] = True
        slot["confidence"] = max(slot["confidence"], conf)
        for src in sources[:5]:  # cap evidence entries per library
            entry = f"{pkg} ({desc}) — {src}"
            if entry not in slot["evidence"]:
                slot["evidence"].append(entry)
        for source, snippet in snippets.get(pkg, []):
            slot["snippets"].append(f"{source}: `{snippet}`  ({desc})")

    # Sensitive data findings
    for kw, locations in sensitive.items():
        label = SENSITIVE_FIELD_KEYWORDS.get(kw, kw)
        state["sensitive_data"]["value"] = True
        for source, snippet in locations:
            state["sensitive_data"]["evidence"].append(
                f"{label} — {source}: `{snippet}`"
            )

    # Rule-based Annex III candidates and supplementary GDPR notes
    state["annex_iii_candidates"] = []
    state["additional_gdpr_notes"] = []
    seen_categories: set[str] = set()
    seen_notes: set[str] = set()

    for kw in sensitive:
        mapping = ANNEX_III_MAPPING.get(kw)
        if not mapping:
            continue
        category, article, note = mapping
        if category:
            key = f"{category}|{article}"
            if key not in seen_categories:
                seen_categories.add(key)
                state["annex_iii_candidates"].append({
                    "category": category,
                    "article": article,
                    "note": note,
                    "trigger": kw,
                })
        else:
            note_key = f"{article}|{note}"
            if note_key not in seen_notes:
                seen_notes.add(note_key)
                state["additional_gdpr_notes"].append({
                    "article": article,
                    "note": note,
                    "trigger": kw,
                })

    state["doc_conflicts"] = []

    _apply_derived_compliance_signals(state, context)

    return state


def _apply_derived_compliance_signals(state: dict, context: dict) -> None:
    """Promote scan-derived signals used by readiness scoring and reports."""
    repo_path = Path(context.get("path", ""))
    scores_slot = state["scores_people"]
    scores_seen: set[str] = set()

    def _add_score_evidence(label: str, source: str) -> None:
        entry = f"{label} — {source}"
        if entry in scores_seen:
            return
        scores_seen.add(entry)
        scores_slot["value"] = True
        scores_slot["confidence"] = max(scores_slot["confidence"], 0.85)
        scores_slot["evidence"].append(entry)

    combined_text_parts: list[str] = [context.get("readme") or ""]
    if repo_path.is_dir():
        for py_file in repo_path.rglob("*.py"):
            if _should_skip(py_file) or py_file.name in EXCLUDE_FILES:
                continue
            if "fixtures" in py_file.parts or "tests" in py_file.parts:
                continue
            try:
                combined_text_parts.append(py_file.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue

    for text in combined_text_parts:
        if not text:
            continue
        for pattern, label in SCORES_PEOPLE_PATTERNS:
            match = re.search(pattern, text, re.I)
            if not match:
                continue
            line_no = text[: match.start()].count("\n") + 1
            line = text.splitlines()[line_no - 1].strip()[:120]
            _add_score_evidence(label, f"scan:{line_no}: `{line}`")

    for signal in state.get("domain_signals") or []:
        lower = signal.lower()
        if any(
            term in lower
            for term in (
                "eligibility",
                "scoring",
                "recruitment",
                "financial decisioning",
                "approve/deny",
            )
        ):
            _add_score_evidence("domain signal", signal)

    annex = state.get("annex_iii_candidates") or []
    uses_ai = state["uses_ai"]["value"]
    if uses_ai and annex:
        hr_slot = state["high_risk_ai"]
        for item in annex:
            category = item.get("category") or ""
            trigger = item.get("trigger") or ""
            entry = f"{category} (trigger: {trigger})"
            if entry not in hr_slot["evidence"]:
                hr_slot["evidence"].append(entry)
        hr_slot["value"] = True
        hr_slot["confidence"] = max(hr_slot["confidence"], 0.9)


# ─────────────────────────────────────────────────────────────
# 4. DYNAMIC Q&A - only asks what the scan couldn't determine
# ─────────────────────────────────────────────────────────────
def generate_dynamic_questions(synthesis: dict, max_questions: int = 2) -> list[dict]:
    """Turn synthesis uncertainties into free-text follow-up questions.

    Kept deliberately few (max 2) so the form stays short and approachable —
    the heavy lifting is done by deeper code analysis, not by interrogating
    the user.
    """
    uncertainties = synthesis.get("uncertainties") or []
    questions: list[dict] = []
    for i, uncertainty in enumerate(uncertainties[:max_questions]):
        text = str(uncertainty).strip()
        if not text:
            continue
        questions.append({
            "key": f"dynamic_{i}",
            "q": text,
            "type": "text",
            "help": "A short answer is fine — this just helps us tailor the report.",
        })
    return questions


def get_questions(state: dict) -> list[dict]:
    """
    Returns a short, plain-language question list for the few facts that the
    code scan genuinely cannot determine. Pure logic, no I/O.
    """
    questions = []

    synthesis = state.get("deep_synthesis")
    if synthesis:
        questions.extend(generate_dynamic_questions(synthesis))

    questions.append({
        "key": "project_stage",
        "q": "Is this live yet?",
        "help": "Rules apply more strictly once real users are involved.",
        "opts": [
            "Still building it (no real users yet)",
            "Just launched (a few early users)",
            "Live with active users",
            "It's open source (we don't run it as a paid service)",
        ],
    })

    if state["uses_ai"]["value"]:
        questions.append({
            "key": "ai_use_case",
            "q": "What does the AI mainly do?",
            "help": "Some uses (like health, credit, or hiring decisions) carry stricter rules.",
            "opts": [
                "Creates content (text, images, code)",
                "Recommends or personalises things",
                "Sorts, scores or predicts things",
                "Makes decisions about people (health, money, hiring, identity)",
                "Something else",
            ],
        })

    questions.append({
        "key": "sector",
        "q": "What's your line of business?",
        "help": "Industry affects which rules matter most.",
        "opts": [
            "Software / tech",
            "Finance",
            "Healthcare",
            "Online platform / marketplace",
            "Something else",
        ],
    })

    questions.append({
        "key": "company_size",
        "q": "How big is your team?",
        "help": "Smaller companies get lighter obligations for some rules.",
        "opts": [
            "Under 50 people",
            "50–249 people",
            "250+ people",
        ],
    })

    if state["is_platform"]["value"]:
        questions.append({
            "key": "mau",
            "q": "Roughly how many people use your platform each month?",
            "help": "Very large platforms (45M+ in the EU) face extra obligations.",
            "opts": [
                "Under 1 million",
                "1–45 million",
                "Over 45 million",
            ],
        })

    return questions


def apply_answers(state: dict, answers: dict) -> dict:
    """Merge {question_key: answer_string} into state and return updated state."""
    updated = dict(state)
    for key, answer in answers.items():
        updated[key] = answer
    return updated


def run_qa(state: dict) -> dict:
    """
    Asks targeted questions only for compliance-critical fields
    that couldn't be inferred from the codebase.
    """
    questions = get_questions(state)
    if not questions:
        return state

    print("\n── Quick questions (code can't answer these) ──────────\n")

    for item in questions:
        print(f"▸ {item['q']}")
        if item.get("type") == "text":
            answer = input("  Your answer: ").strip()
        else:
            for i, opt in enumerate(item["opts"], 1):
                print(f"  {i}. {opt}")
            answer = input("  Your answer (number or text): ").strip()
            try:
                idx = int(answer) - 1
                if 0 <= idx < len(item["opts"]):
                    answer = item["opts"][idx]
            except ValueError:
                pass
        state = apply_answers(state, {item["key"]: answer})
        print()

    return state


# ─────────────────────────────────────────────────────────────
# 5. REPORT GENERATION via Mistral
# ─────────────────────────────────────────────────────────────
def build_profile_text(state: dict) -> str:
    """Converts knowledge state to a readable text profile for the LLM prompt."""
    lines = []
    ctx = state.get("project_context", {})

    lines.append(f"PROJECT: {ctx.get('name', 'unknown')} at {ctx.get('path', 'unknown')}")
    if ctx.get("entry_points"):
        lines.append(f"- Entry points: {', '.join(str(x) for x in ctx['entry_points'])}")
    if ctx.get("structure"):
        lines.append(f"- Top-level structure: {', '.join(str(x) for x in ctx['structure'][:20])}")
    if ctx.get("file_counts"):
        top_ext = sorted(ctx["file_counts"].items(), key=lambda x: -x[1])[:8]
        lines.append("- File mix: " + ", ".join(f"{ext}={n}" for ext, n in top_ext))
    if ctx.get("readme"):
        lines.append("- README excerpt:")
        for readme_line in ctx["readme"].splitlines()[:12]:
            if readme_line.strip():
                lines.append(f"    · {readme_line.strip()[:100]}")
    if ctx.get("domain_signals"):
        lines.append("- Domain-specific signals (from application code):")
        for sig in ctx["domain_signals"][:10]:
            lines.append(f"    · {sig}")
    if ctx.get("env_patterns"):
        lines.append("- Environment / secret patterns detected:")
        for env in ctx["env_patterns"][:6]:
            lines.append(f"    · {env}")
    lines.append("")

    label_map = {
        "uses_ai":      "AI/ML usage",
        "high_risk_ai": "High-risk AI signals",
        "is_platform":  "Platform / web service",
        "has_security": "Security measures",
        "cloud_infra":  "Cloud infrastructure",
    }

    for key, label in label_map.items():
        slot = state[key]
        if slot["value"]:
            lines.append(f"- {label}: DETECTED ({slot['confidence']:.0%} confidence)")
            for ev in slot["evidence"][:5]:
                lines.append(f"    · {ev}")
            for snip in slot.get("snippets", [])[:5]:
                lines.append(f"    · Code: {snip}")
        else:
            lines.append(f"- {label}: Not detected")

    # Sensitive data fields detected in the codebase
    sd = state["sensitive_data"]
    if sd["value"]:
        lines.append("- Sensitive/special-category data fields: DETECTED in codebase")
        for ev in sd["evidence"][:MAX_SENSITIVE_FINDINGS]:
            lines.append(f"    · {ev}")
    else:
        lines.append("- Sensitive/special-category data fields: None detected by scan")

    candidates = state.get("annex_iii_candidates", [])
    if candidates:
        lines.append("- CANDIDATE ANNEX III CLASSIFICATIONS (rule-based, pre-computed):")
        for c in candidates:
            lines.append(
                f"    · {c['category']} ({c['article']}) — triggered by '{c['trigger']}': {c['note']}"
            )
    else:
        lines.append("- CANDIDATE ANNEX III CLASSIFICATIONS: None pre-computed from scan")

    gdpr_notes = state.get("additional_gdpr_notes", [])
    if gdpr_notes:
        lines.append("- Additional GDPR notes from sensitive data scan:")
        for n in gdpr_notes:
            lines.append(f"    · {n['article']} (trigger: {n['trigger']}): {n['note']}")

    conflicts = state.get("doc_conflicts", [])
    if conflicts:
        lines.append("- DOCUMENT VS CODE CONFLICTS (high priority):")
        for conflict in conflicts:
            lines.append(f"    · {conflict}")

    synthesis = state.get("deep_synthesis")
    if synthesis:
        lines.append("AI-SYNTHESIZED PRODUCT UNDERSTANDING:")
        if synthesis.get("product_summary"):
            lines.append(f"- Product summary: {synthesis['product_summary']}")
        for feature in synthesis.get("ai_features", [])[:8]:
            lines.append(f"    · AI feature: {feature}")
        for flow in synthesis.get("data_flows", [])[:8]:
            lines.append(f"    · Data flow: {flow}")
        if synthesis.get("user_facing_assessment"):
            lines.append(f"- User-facing assessment: {synthesis['user_facing_assessment']}")

    user_context: list[str] = []
    synthesis_uncertainties = (synthesis or {}).get("uncertainties", [])
    for i, uncertainty in enumerate(synthesis_uncertainties[:4]):
        key = f"dynamic_{i}"
        if state.get(key):
            user_context.append(f"Q: {uncertainty}\nA: {state[key]}")
    for msg in state.get("user_chat_context", []):
        if msg and str(msg).strip():
            user_context.append(str(msg).strip())
    if user_context:
        lines.append("ADDITIONAL CONTEXT FROM USER:")
        for entry in user_context:
            lines.append(f"    · {entry}")

    qa_labels = {
        "project_stage": "Project stage",
        "ai_use_case":  "AI use case",
        "sector":       "Industry sector",
        "company_size": "Company size",
        "mau":          "Monthly active users",
    }
    for key, label in qa_labels.items():
        if state.get(key):
            lines.append(f"- {label}: {state[key]}")

    return "\n".join(lines)


def build_rag_queries(state: dict) -> list[tuple[str, str]]:
    """Build retrieval queries per regulation from the knowledge state."""
    queries: list[tuple[str, str]] = []

    ai_parts: list[str] = []
    if state["uses_ai"]["value"]:
        ai_parts.append("AI system machine learning automated decision-making")
    if state["high_risk_ai"]["value"]:
        ai_parts.append("high-risk AI biometric identification emotion recognition")
    if state["sensitive_data"]["value"]:
        ai_parts.append("processing health diagnosis personal sensitive data")
    if state.get("ai_use_case"):
        ai_parts.append(str(state["ai_use_case"]))
    if state.get("sector"):
        ai_parts.append(f"sector {state['sector']}")
    if ai_parts:
        queries.append(("AI Act", " ".join(ai_parts)))

    nis2_parts: list[str] = []
    if state["has_security"]["value"]:
        nis2_parts.append("cybersecurity risk management incident reporting")
    else:
        nis2_parts.append("network information security essential important entity")
    if state["cloud_infra"]["value"]:
        nis2_parts.append("cloud infrastructure supply chain security")
    if state.get("sector"):
        nis2_parts.append(str(state["sector"]))
    queries.append(("NIS2", " ".join(nis2_parts)))

    dsa_parts: list[str] = []
    if state["is_platform"]["value"]:
        dsa_parts.append("online platform intermediary service content moderation")
    if state.get("mau"):
        dsa_parts.append(f"monthly active users {state['mau']}")
    if state.get("company_size"):
        dsa_parts.append(str(state["company_size"]))
    queries.append(("DSA", " ".join(dsa_parts) if dsa_parts else "digital services intermediary obligations"))

    gdpr_parts: list[str] = []
    if state["sensitive_data"]["value"]:
        triggers = [e.split(" — ")[0] for e in state["sensitive_data"]["evidence"][:5]]
        gdpr_parts.append("processing of " + " and ".join(triggers))
        gdpr_parts.append("special category personal data lawful basis consent DPIA")
    if state.get("additional_gdpr_notes"):
        gdpr_parts.append("children data minimisation security")
    if gdpr_parts:
        queries.append(("GDPR", " ".join(gdpr_parts)))

    stage = state.get("project_stage", "")
    if stage.startswith("Open source"):
        queries.append(
            ("AI Act", "open source AI component exemption obligations")
        )

    return queries


def retrieve_legal_context(state: dict, top_k: int = 3) -> str:
    """Retrieve relevant legal articles and format them for the LLM prompt."""
    try:
        from legal_rag.retrieve import retrieve_relevant_articles
    except ImportError:
        return ""

    sections: list[str] = []
    seen: set[tuple[str, str]] = set()

    for regulation, query in build_rag_queries(state):
        try:
            results = retrieve_relevant_articles(query, regulation=regulation, top_k=top_k)
        except FileNotFoundError:
            return ""
        except Exception as exc:
            print(f"      RAG warning: retrieval failed for {regulation}: {exc}")
            continue

        for result in results:
            key = (result["regulation"], result["article"])
            if key in seen:
                continue
            seen.add(key)
            title = f" — {result['title']}" if result.get("title") else ""
            sections.append(
                f"### {result['regulation']} — {result['article']}{title}\n{result['text']}"
            )

    if not sections:
        return ""

    return (
        "RELEVANT LEGAL TEXT (retrieved from official regulation documents):\n\n"
        + "\n\n---\n\n".join(sections)
    )


def _retrieve_articles_for_queries(
    queries: list[tuple[str, str]],
    top_k: int = 3,
) -> str:
    """Retrieve legal articles for explicit (regulation, query) pairs."""
    try:
        from legal_rag.retrieve import retrieve_relevant_articles
    except ImportError:
        return ""

    sections: list[str] = []
    seen: set[tuple[str, str]] = set()

    for regulation, query in queries:
        try:
            results = retrieve_relevant_articles(query, regulation=regulation, top_k=top_k)
        except FileNotFoundError:
            return ""
        except Exception as exc:
            print(f"      RAG warning: retrieval failed for {regulation}: {exc}")
            continue

        for result in results:
            key = (result["regulation"], result["article"])
            if key in seen:
                continue
            seen.add(key)
            title = f" — {result['title']}" if result.get("title") else ""
            sections.append(
                f"### {result['regulation']} — {result['article']}{title}\n{result['text']}"
            )

    if not sections:
        return ""

    return (
        "RELEVANT LEGAL TEXT (retrieved from official regulation documents):\n\n"
        + "\n\n---\n\n".join(sections)
    )


def _project_stage_instructions(state: dict) -> str:
    """Return prompt framing instructions based on project_stage answer."""
    stage = state.get("project_stage", "")
    if stage.startswith("Still building"):
        return (
            "PROJECT STAGE FRAMING (pre-launch):\n"
            "This project has not yet launched. Frame all 'Key gaps' as "
            "'Before launch, you should also address...' and frame 'Priority actions' "
            "as a pre-launch checklist. Regulatory deadlines that have already passed "
            "should be reframed as 'this obligation will apply from day one of launch' "
            "rather than 'you are already late'."
        )
    if stage.startswith("Just launched"):
        return (
            "PROJECT STAGE FRAMING (early stage):\n"
            "This project recently launched with limited users. Note where obligations "
            "scale with user numbers or company size (e.g. NIS2 entity thresholds, "
            "DSA VLOP/VLOSE thresholds) and that requirements may not yet bind but "
            "will as the project grows — frame these as 'plan for' rather than "
            "'urgent gap'."
        )
    if stage.startswith("It's open source"):
        return (
            "PROJECT STAGE FRAMING (open source):\n"
            "This is an open-source project not operated as a commercial service by "
            "the team. For each regulation, clarify TWO separate things: (1) whether the "
            "AI Act, NIS2, DSA, or GDPR apply to the act of RELEASING this code as "
            "open source (note: the AI Act includes exemptions for free and open "
            "source AI components in some circumstances, though these exemptions do "
            "not apply to prohibited AI practices, high-risk systems, or GPAI models "
            "with systemic risk - check the retrieved legal text for the exact "
            "conditions), and (2) what obligations would apply to a DOWNSTREAM USER "
            "or organization who deploys this code as a live service (they would "
            "likely be the 'deployer' or 'provider' for AI Act purposes, and the "
            "'controller' for GDPR purposes). Frame priority actions as two lists: "
            "'For this repository/project itself' and 'Guidance to include for "
            "downstream deployers (e.g. in your README or documentation)'."
        )
    return ""


def _mistral_complete(
    messages: list[dict],
    *,
    response_format: dict | None = None,
    timeout_ms: int | None = None,
    label: str = "Mistral API",
    max_retries: int = 3,
) -> str:
    """Call configured LLM provider (Mistral default) with retry on timeouts."""
    from actguard.llm import complete

    return complete(
        messages,
        response_format=response_format,
        timeout_ms=timeout_ms or MISTRAL_TIMEOUT_MS,
        label=label,
        max_retries=max_retries,
    )


def _parse_json_response(text: str) -> dict:
    """Parse JSON from an LLM response, tolerating markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def extract_doc_claims(doc_text: str) -> dict:
    """Extract structured compliance-relevant claims from privacy policy / ToS text."""
    if not doc_text or not doc_text.strip():
        return {}

    prompt = f"""Extract structured compliance claims from this privacy policy or terms of service.
Return ONLY valid JSON with these keys:
- "data_collected": list of data types the document says are collected
- "automated_decision_making": {{"mentioned": bool, "quote": string or null}}
- "data_sharing": list of third parties mentioned for data sharing
- "user_rights_mentioned": list of GDPR rights mentioned (access, deletion, portability, etc.)
- "service_description": one sentence describing what the document says the service does

DOCUMENT TEXT:
{doc_text[:12000]}"""

    try:
        content = _mistral_complete(
            [{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            label="Document claim extraction",
        )
        return _parse_json_response(content)
    except Exception:
        return {}


def detect_conflicts(state: dict, doc_claims: dict) -> list[str]:
    """Identify contradictions between codebase analysis and document claims."""
    if not doc_claims:
        return []

    profile = build_profile_text(state)
    claims_json = json.dumps(doc_claims, indent=2)

    prompt = f"""You are a compliance analyst. Compare the codebase analysis with claims from the company's privacy policy / terms of service.
Identify specific contradictions where the code evidence conflicts with what the document states.

Examples of contradictions:
- Code shows AI/automated decision-making but document says no automated decisions
- Code shows sensitive data fields (e.g. health data) not mentioned in data_collected
- Code shows third-party API calls (e.g. OpenAI) but document doesn't mention this data sharing
- Document describes the service as one type but platform/scale signals suggest otherwise

CODEBASE ANALYSIS:
{profile}

DOCUMENT CLAIMS (extracted):
{claims_json}

Return ONLY valid JSON: {{"conflicts": ["conflict 1 citing code evidence AND document claim", ...]}}
If no contradictions found, return {{"conflicts": []}}.
Each conflict string must cite both the code evidence and the contradicting document claim."""

    try:
        content = _mistral_complete(
            [{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            label="Conflict detection",
        )
        parsed = _parse_json_response(content)
        conflicts = parsed.get("conflicts", [])
        if isinstance(conflicts, list):
            return [str(c) for c in conflicts if c]
        return []
    except Exception:
        return []


def _language_instruction(language: str) -> str:
    """Return prompt instruction for non-English report generation."""
    if not language or language == "English":
        return ""
    return (
        f"\nLANGUAGE INSTRUCTION:\n"
        f"Write the entire report in {language}. Section headers should be in {language}, "
        f"but on first mention of each regulation, include the official English name in "
        f"parentheses (e.g. for French: 'Loi sur l'IA (AI Act)', for German: "
        f"'KI-Verordnung (AI Act)'). Legal/technical terms without a standard translation "
        f"may remain in English. The RELEVANT LEGAL TEXT provided below is in English — "
        f"paraphrase its content in {language} rather than quoting it directly, and reference "
        f"article numbers following {language} convention (e.g. 'Article X' / 'Artikel X').\n"
    )


def generate_report(state: dict, language: str = "English") -> str:
    """Sends the knowledge state to Mistral and returns a compliance report."""
    profile = build_profile_text(state)
    legal_context = retrieve_legal_context(state)

    legal_block = ""
    if legal_context:
        legal_block = f"""
{legal_context}

"""
        print("      Retrieved relevant legal articles from local index.")

    grounding_legal = (
        "- When citing articles, prefer the ones provided in RELEVANT LEGAL TEXT above, "
        "quoting or paraphrasing their actual content rather than relying on general knowledge. "
        "If the retrieved articles don't cover something you need to cite, say "
        "'the relevant provisions' rather than guessing an article number."
        if legal_context
        else "- If uncertain about a specific article number, refer to \"the relevant provisions\" rather than guessing."
    )

    conflicts = state.get("doc_conflicts", [])
    conflicts_block = ""
    if conflicts:
        conflicts_block = (
            "\nDOCUMENT VS CODE CONFLICTS (high priority - address these explicitly "
            "in the relevant report sections):\n"
            + "\n".join(f"- {c}" for c in conflicts)
            + "\n"
        )

    annex_iii_instruction = (
        "- Use the candidate Annex III classifications above as your starting point for risk "
        "classification. Confirm whether each candidate applies given the AI use case described, "
        "rather than deriving the classification from scratch. If no candidates were found, "
        "classification should default to limited-risk or minimal-risk depending on the AI use case, "
        "and you should state this explicitly rather than searching for a high-risk category that "
        "doesn't fit."
    )

    stage_block = _project_stage_instructions(state)
    stage_instruction = f"\n{stage_block}\n" if stage_block else ""
    lang_instruction = _language_instruction(language)

    prompt = f"""You are an EU technology regulation compliance expert. A company has had their codebase at the path below analyzed automatically. Generate a practical compliance self-assessment based ONLY on the findings from that specific project.

COMPANY PROFILE (extracted from automated codebase analysis, including specific code snippets and detected data fields):
{profile}
{legal_block}{conflicts_block}{stage_instruction}{lang_instruction}
IMPORTANT GROUNDING INSTRUCTIONS:
- The AI-SYNTHESIZED PRODUCT UNDERSTANDING section reflects an automated reading of the codebase and may contain errors — where ADDITIONAL CONTEXT FROM USER provides a correction or clarification, prioritize the user's answer over the synthesized understanding.
- The project analyzed is named "{state.get('project_context', {}).get('name', 'unknown')}" — every gap and recommendation MUST reference specific files, lines, libraries, or README facts from THIS project only.
- Do NOT cite eu_compliance.py or the compliance scanner tool — those are not part of the audited application.
- Wherever the profile includes a "Code:" line, a domain signal, or a sensitive data field with a file:line reference, cite that specific file, line, or field name directly in your gap analysis.
- Do not write generic boilerplate gaps that could apply to any company — every gap should reference something specific from the profile above.
- Use the README excerpt and domain signals to understand what the product actually does (e.g. medtech, fintech, SaaS).
- If "Sensitive/special-category data fields: DETECTED" appears, treat it as a primary driver of risk classification — but only if the matches are from application code, not scanner configuration.
- If the profile says a category was "Not detected", briefly state that and move on — don't speculate.
{annex_iii_instruction}
{grounding_legal}
- Be thorough: this report should reflect deep analysis of the evidence provided, not a generic template.
- If DOCUMENT VS CODE CONFLICTS are listed above, reference relevant conflicts in each regulation section's Key gaps.

Generate a structured compliance report for the following EU regulations.
Use these exact section headers (one per regulation):

## EU AI Act (Regulation 2024/1689)
- **Applicability**: Applies / Does not apply / Unclear — one sentence explaining why, citing specific evidence
- **Risk classification**: Prohibited practice / High-risk / Limited-risk / Minimal-risk — justify using the candidate Annex III classifications, sensitive data fields, and AI use case detected
- **Key gaps**: 2–3 specific compliance gaps, each referencing a specific file, snippet, or field from the profile
- **Priority actions**: specific steps with regulatory deadlines

## NIS2 Directive (Directive 2022/2555)
- **Applicability**: Essential entity / Important entity / Not in scope — one sentence why
- **Key gaps**: 2–3 specific gaps referencing the security/cloud signals detected (or their absence)
- **Priority actions**: specific steps with deadlines

## DSA — Digital Services Act (Regulation 2022/2065)
- **Applicability**: VLOP / VLOSE / Intermediary service / Not in scope — one sentence why
- **Key gaps**: 2–3 specific gaps
- **Priority actions**: specific steps with deadlines

## GDPR (Regulation 2016/679)
- **Applicability**: State plainly that GDPR applies to virtually all EU-facing services that process personal data (do not ask whether it applies — note it plainly based on the evidence)
- **Special category data identified**: List the specific fields/files from the sensitive data evidence, with Art. 9 legal basis requirements where applicable
- **Key gaps**: e.g. missing consent records, no documented legal basis, no DPIA evidence for high-risk processing (Art. 35) — reference document conflicts if listed
- **Priority actions**: specific steps with deadlines

## Overall priority matrix
Rank the top 5 actions across all four regulations (AI Act, NIS2, DSA, GDPR) by urgency (most urgent first). Be specific and reference regulatory articles where relevant. You may present this section as a markdown table with columns: Priority, Action, Regulation, Deadline.

STRICT FORMATTING RULES (this output is parsed by a machine — follow them exactly):
- Write each regulation header on its own line as a level-2 heading in the canonical English form shown above (e.g. `## EU AI Act (Regulation 2024/1689)`). Do NOT bold the header, do NOT prefix it with a number, and do NOT add any extra top-level title or restate the report title.
- Even when the report language is not English, keep these five section headers AND the field labels (Applicability, Risk classification, Special category data identified, Key gaps, Priority actions) in the exact English form above — they are machine-read anchors. Translate only the body text after each label.
- Write each field as a bold bullet exactly like `- **Applicability**: ...`. Never express these fields as sub-headings (do not use `###`).
- The priority section header must be exactly `## Overall priority matrix`.

Keep the tone practical and non-alarmist. If a regulation clearly does not apply, say so briefly and move on.

---
DISCLAIMER: This is an automated self-assessment tool and does not constitute legal advice. Consult a qualified legal professional for binding compliance decisions."""

    print(f"      Calling Mistral API ({MISTRAL_MODEL})...")
    report = _mistral_complete(
        [{"role": "user", "content": prompt}],
        timeout_ms=MISTRAL_REPORT_TIMEOUT_MS,
        label="Report generation",
    )
    if not report.strip():
        raise RuntimeError("Mistral returned an empty report.")
    return report


def generate_plain_summary(
    full_report: str,
    synthesis: dict,
    language: str = "English",
) -> str:
    """Write a plain-language summary for non-legal readers, prepended to the technical report."""
    product_description = ""
    if synthesis:
        product_description = (
            synthesis.get("product_description")
            or synthesis.get("product_summary")
            or ""
        )

    lang_note = ""
    if language and language != "English":
        lang_note = f"\nWrite the entire summary in {language}.\n"

    prompt = f"""You've been given a technical EU compliance report full of legal references and article numbers.
Write a short summary for someone who is NOT a lawyer and doesn't know what 'Annex III' or 'Art. 21' means.

PRODUCT CONTEXT (from codebase analysis):
{product_description or "Not available — infer from the report below."}

TECHNICAL REPORT:
{full_report}
{lang_note}
Write for a smart but non-technical founder. Use everyday words, short sentences, and
the second person ("you"). Never use article numbers, regulation nicknames without
explanation, or words like "Annex", "Art.", "obligations", "provisions". If you must
name a regulation, add a 4-5 word plain gloss the first time (e.g. "the EU AI Act (the
EU's rules for AI systems)").

Structure your response as markdown with this exact header:
## What This Means For You (Plain Language Summary)

Then include:

1. One sentence restating what their project does (using the product context above).
2. A subsection titled "Which EU rules apply to you, in plain terms" — for each
   regulation that applies, write 1-2 sentences covering: WHY it applies to THIS project
   (reference the actual feature), and what it basically asks you to do, in plain words
   (e.g. instead of 'Article 13 transparency obligations apply', write 'Because your app
   uses AI to write replies, you need to tell users when they're reading something the AI
   generated'). If a regulation clearly does not apply, skip it here.
3. A subsection titled "What to do first" — a short numbered list (max 5 items) of the
   most important next steps, ordered by priority. Each item is ONE sentence, starts with
   a verb, says what to do AND why it matters in plain terms (e.g. 'Add a short note in
   your app saying replies are AI-generated, so users aren't misled.').
4. One closing sentence: 'The sections below go into the legal detail — share those with a lawyer if you want to confirm everything here.'

Keep the tone friendly and reassuring, not alarming — the goal is to help them understand what's needed, not to scare them."""

    print(f"      Calling Mistral API for plain-language summary ({MISTRAL_MODEL})...")
    summary = _mistral_complete(
        [{"role": "user", "content": prompt}],
        timeout_ms=MISTRAL_REPORT_TIMEOUT_MS,
        label="Plain-language summary",
    )
    if not summary.strip():
        raise RuntimeError("Mistral returned an empty plain-language summary.")

    if "## What This Means For You" not in summary and "##" in summary:
        return summary
    if "## What This Means For You" not in summary:
        return f"## What This Means For You (Plain Language Summary)\n\n{summary.strip()}"
    return summary.strip()


def _format_structured_report_for_guide(structured) -> str:
    """Summarize parsed compliance report gaps/actions for the implementation guide prompt."""
    lines: list[str] = []
    if hasattr(structured, "priority_matrix"):
        priority = structured.priority_matrix
        sections = structured.sections
    else:
        priority = structured.get("priority_matrix", [])
        sections = structured.get("sections", [])

    if priority:
        lines.append("OVERALL PRIORITY MATRIX:")
        for i, item in enumerate(priority, 1):
            lines.append(f"  {i}. {item}")

    for section in sections:
        if hasattr(section, "title"):
            title = section.title
            gaps = section.gaps
            actions = section.actions
        else:
            title = section.get("title", section.get("id", "Unknown"))
            gaps = section.get("gaps", [])
            actions = section.get("actions", [])
        lines.append(f"\n{title}:")
        if gaps:
            lines.append("  Key gaps:")
            for gap in gaps:
                lines.append(f"    - {gap}")
        if actions:
            lines.append("  Priority actions:")
            for action in actions:
                lines.append(f"    - {action}")

    return "\n".join(lines) if lines else "No structured gaps/actions extracted."


def generate_implementation_guide(
    state: dict,
    technical_report: str,
    structured_report,
    language: str = "English",
) -> str:
    """Generate an engineer-ready implementation guide from the compliance report."""
    profile = build_profile_text(state)
    synthesis = state.get("deep_synthesis") or {}
    product_description = (
        synthesis.get("product_description")
        or synthesis.get("product_summary")
        or ""
    )
    structured_summary = _format_structured_report_for_guide(structured_report)
    project_name = state.get("project_context", {}).get("name", "unknown")

    conflicts = state.get("doc_conflicts", [])
    conflicts_block = ""
    if conflicts:
        conflicts_block = (
            "\nDOCUMENT VS CODE CONFLICTS (address in relevant tasks):\n"
            + "\n".join(f"- {c}" for c in conflicts)
            + "\n"
        )

    lang_instruction = _language_instruction(language)
    if language and language != "English":
        lang_instruction = (
            lang_instruction
            or f"\nWrite the entire guide in {language}.\n"
        )

    prompt = f"""You are a senior software engineer translating an EU compliance self-assessment into an actionable implementation guide for developers and AI coding agents.

The audience is NOT lawyers — they are developers or vibe coders who want to fix compliance issues without reading legal prose. Turn every compliance gap and priority action into concrete, implementable tasks.

PROJECT: {project_name}

CODEBASE PROFILE (from automated scan — cite these file paths in tasks):
{profile}

AI-SYNTHESIZED PRODUCT UNDERSTANDING:
{product_description or "See codebase profile above."}

COMPLIANCE REPORT GAPS AND ACTIONS (source of truth for tasks):
{structured_summary}

FULL TECHNICAL COMPLIANCE REPORT (for additional context):
{technical_report}
{conflicts_block}{lang_instruction}
GROUNDING RULES:
- Every task MUST trace to a specific gap, action, or scan finding from the materials above.
- Cite real file paths from the codebase profile — no generic tasks like "add GDPR compliance".
- Do NOT reference eu_compliance.py or the compliance scanner tool.
- Include ALL types of work: code changes, config, documentation, policy drafts, and process steps — tag each task with the correct type.
- Order tasks P0 (most urgent) through P3. Use P0 sparingly for blocking/legal-risk items.
- Implementation steps must be numbered and actionable — something an engineer or AI agent can execute.
- Acceptance criteria must be testable/verifiable.
- The Agent prompt section must be a single self-contained block an AI coding agent can follow without reading the rest of the guide.

Generate markdown with these EXACT section headers:

# Compliance Implementation Guide

## Project context
Brief summary: what the product does, detected stack/framework, key compliance-relevant signals from the scan.

## How to use this guide
2–3 sentences: human engineers work through the backlog in priority order; AI agents can use the Agent prompt section below.

## Prioritized backlog
For each task use this exact heading format: ### P0 — Task title  (or P1, P2, P3)

Under each task heading, include these bullet fields:
- **Regulation:** (e.g. GDPR, AI Act, NIS2, DSA)
- **Type:** code | config | docs | policy | process | infra
- **Why:** one sentence tied to a specific gap from the report
- **Files / areas:** concrete paths from scan evidence, or "N/A — organizational" for process tasks
- **Implementation steps:**
  1. First step
  2. Second step
  (numbered list)
- **Acceptance criteria:**
  - Criterion one
  - Criterion two
- **Effort:** small | medium | large

Include all tasks needed to address the compliance gaps — typically 8–15 tasks covering code, docs, policies, and process.

## Agent prompt
Wrap the entire agent prompt in a fenced code block (```). The prompt must:
- State the project name and stack
- Instruct the agent to work through tasks in priority order
- Include every task condensed: priority, title, regulation, files, steps, acceptance criteria
- Say: match existing code conventions; add compliance controls without removing features
- Say: tasks under "Notes for legal review" need lawyer input — implement technical scaffolding only

## Notes for legal review
Bullet list of items that still require qualified legal counsel (not implementable by engineering alone).

---
DISCLAIMER: This is an automated implementation guide derived from a self-assessment. It does not constitute legal advice. Have a qualified legal professional review compliance decisions."""

    print(f"      Calling Mistral API for implementation guide ({MISTRAL_MODEL})...")
    guide = _mistral_complete(
        [{"role": "user", "content": prompt}],
        timeout_ms=MISTRAL_REPORT_TIMEOUT_MS,
        label="Implementation guide",
    )
    if not guide.strip():
        raise RuntimeError("Mistral returned an empty implementation guide.")
    return guide.strip()


def generate_privacy_policy(state: dict, language: str = "English") -> str:
    """Generate a draft Privacy Policy grounded in codebase analysis."""
    profile = build_profile_text(state)

    rag_queries = [
        ("GDPR", "information to be provided to data subjects transparency obligations"),
        ("GDPR", "data subject rights articles 15 16 17 18 20 21 22"),
        ("AI Act", "transparency obligations automated decision-making"),
        ("AI Act", "information to be provided deployers users"),
    ]
    legal_context = _retrieve_articles_for_queries(rag_queries, top_k=4)
    legal_block = f"\n{legal_context}\n\n" if legal_context else ""

    lang_instruction = _language_instruction(language)

    prompt = f"""You are drafting a Privacy Policy for a company based on automated codebase analysis.
This is a FIRST DRAFT for legal review — not a finished document.

CODEBASE PROFILE (evidence from automated scan and Q&A):
{profile}
{legal_block}{lang_instruction}
INSTRUCTIONS:
- Draft a Privacy Policy with these standard sections: Who we are / What data we collect /
  Why we process it (legal basis) / Who we share it with / International transfers /
  Data retention / Your rights (Art. 15-22 GDPR) / Automated decision-making and AI processing /
  Contact for DPO or privacy queries / How to file a complaint with a supervisory authority.
- Only describe data collection and processing activities that are evidenced in the profile below.
  Use placeholder brackets like [COMPANY NAME], [CONTACT EMAIL], [RETENTION PERIOD - SPECIFY]
  for information that cannot be inferred from code and must be filled in by the company.
- Do NOT invent specific claims not grounded in the profile (e.g. do not describe a cookie policy
  unless there is evidence of cookie usage — if uncertain, use a clearly-marked optional placeholder).
- Do not cite file paths or internal code structure — describe data categories in user-facing language.
- Where sensitive data fields were detected, list the categories of personal data in plain language.
- If AI/ML usage was detected, include an automated decision-making / AI processing disclosure section.
- If cloud infrastructure was detected, name likely sub-processors (e.g. AWS, GCP, Azure) in the
  third-party processors / international transfers section.
- Use the sector from the profile to inform tone and any sector-specific disclosures.
- Output clean markdown suitable for publication after legal review."""

    print(f"      Calling Mistral API for Privacy Policy draft ({MISTRAL_MODEL})...")
    body = _mistral_complete(
        [{"role": "user", "content": prompt}],
        timeout_ms=MISTRAL_REPORT_TIMEOUT_MS,
        label="Privacy Policy generation",
    )
    if not body.strip():
        raise RuntimeError("Mistral returned an empty Privacy Policy draft.")
    return f"{DRAFT_LEGAL_DISCLAIMER}\n\n---\n\n{body}"


def generate_tos(state: dict, language: str = "English") -> str:
    """Generate a draft Terms of Service grounded in codebase analysis."""
    profile = build_profile_text(state)

    rag_queries = [
        ("DSA", "terms of service requirements online platforms"),
        ("DSA", "intermediary service provider obligations terms conditions"),
    ]
    legal_context = _retrieve_articles_for_queries(rag_queries, top_k=4)
    legal_block = f"\n{legal_context}\n\n" if legal_context else ""

    platform_note = ""
    if state["is_platform"]["value"]:
        platform_note = (
            "- Include user accounts and acceptable use policy sections (platform detected).\n"
        )
    ai_note = ""
    if state["uses_ai"]["value"]:
        ai_note = (
            "- Include an AI-generated content disclaimer section (AI/ML usage detected).\n"
        )

    lang_instruction = _language_instruction(language)

    prompt = f"""You are drafting Terms of Service for a company based on automated codebase analysis.
This is a FIRST DRAFT for legal review — not a finished document.

CODEBASE PROFILE (evidence from automated scan and Q&A):
{profile}
{legal_block}{lang_instruction}
INSTRUCTIONS:
- Draft Terms of Service with standard sections: Service description / User obligations /
  Acceptable use / Intellectual property / Limitation of liability / Governing law [PLACEHOLDER] /
  Termination / Changes to terms.
{platform_note}{ai_note}- Only describe service features and obligations evidenced in the profile below.
  Use placeholder brackets like [COMPANY NAME], [CONTACT EMAIL], [GOVERNING LAW - SPECIFY],
  [JURISDICTION - SPECIFY] for information that cannot be inferred from code.
- Do NOT invent specific claims not grounded in the profile.
- Do not cite file paths or internal code structure.
- Output clean markdown suitable for publication after legal review."""

    print(f"      Calling Mistral API for Terms of Service draft ({MISTRAL_MODEL})...")
    body = _mistral_complete(
        [{"role": "user", "content": prompt}],
        timeout_ms=MISTRAL_REPORT_TIMEOUT_MS,
        label="Terms of Service generation",
    )
    if not body.strip():
        raise RuntimeError("Mistral returned an empty Terms of Service draft.")
    return f"{DRAFT_LEGAL_DISCLAIMER}\n\n---\n\n{body}"


# ─────────────────────────────────────────────────────────────
# 6. MAIN ORCHESTRATOR
# ─────────────────────────────────────────────────────────────
def main():
    print("\n╔══════════════════════════════════════╗")
    print("║   EU Compliance Agent  v0.1          ║")
    print("║   AI Act · NIS2 · DSA · GDPR         ║")
    print("╚══════════════════════════════════════╝")

    # Get target repo path
    if len(sys.argv) > 1:
        repo_path = sys.argv[1]
    else:
        repo_path = input("\nPath to your project folder: ").strip()

    repo_path = str(Path(repo_path).resolve())
    output_dir = Path(repo_path)

    # ── Step 1: Scan ──────────────────────────────────────────
    print(f"\n[1/5] Scanning codebase at: {repo_path}")
    context = scan_project_context(repo_path)
    evidence, snippets = scan_repo(repo_path)
    sensitive = scan_sensitive_fields(repo_path)

    py_count = context["file_counts"].get(".py", 0)
    print(f"      Scanned {sum(context['file_counts'].values())} files ({py_count} Python modules)")

    if evidence:
        print(f"      Found {len(evidence)} compliance-relevant signal(s):")
        for pkg in list(evidence.keys())[:8]:
            field_name, conf, desc = SIGNALS[pkg]
            print(f"      · {pkg} ({desc}) → {field_name}")
        if len(evidence) > 8:
            print(f"      · ...and {len(evidence) - 8} more")
    else:
        print("      No known libraries detected — proceeding with Q&A only.")

    if sensitive:
        print(f"      ⚠ Found {len(sensitive)} type(s) of sensitive/special-category data fields:")
        for kw in list(sensitive.keys())[:6]:
            print(f"      · {SENSITIVE_FIELD_KEYWORDS.get(kw, kw)}")

    if context.get("domain_signals"):
        print(f"      Found {len(context['domain_signals'])} domain-specific signal(s):")
        for sig in context["domain_signals"][:5]:
            print(f"      · {sig.split(' — ')[0]}")

    # ── Step 2: Build knowledge state ─────────────────────────
    print("\n[2/5] Building compliance profile...")
    state = build_state(evidence, snippets, sensitive, context)

    flags = []
    if state["uses_ai"]["value"]:
        flags.append(f"AI/ML ({state['uses_ai']['confidence']:.0%})")
    if state["high_risk_ai"]["value"]:
        flags.append("⚠ HIGH-RISK AI")
    if state["is_platform"]["value"]:
        flags.append("Platform")
    if state["has_security"]["value"]:
        flags.append("Security libs present")
    else:
        flags.append("No security libs detected")
    print("      " + " · ".join(flags))

    # ── Step 3: Deep analysis (optional) ───────────────────────
    print("\n[3/5] Deep AI analysis...")
    try:
        from deep_analysis import build_file_tree, run_deep_analysis

        file_tree = build_file_tree(repo_path)
        synthesis = run_deep_analysis(
            repo_path, file_tree, evidence, sensitive, state, max_files=20
        )
        state["deep_synthesis"] = synthesis
        if synthesis.get("product_summary"):
            print(f"      {synthesis['product_summary'][:120]}...")
        if synthesis.get("uncertainties"):
            print(f"      Generated {len(synthesis['uncertainties'])} context-specific question(s)")
    except Exception as exc:
        print(f"      Deep analysis skipped: {exc}")

    # ── Step 4: Dynamic Q&A ────────────────────────────────────
    print("\n[4/5] Gap analysis...")
    state = run_qa(state)

    # ── Step 5: Generate report ────────────────────────────────
    print("\n[5/5] Generating report via Mistral...")
    try:
        technical_report = generate_report(state)
        synthesis = state.get("deep_synthesis") or {}
        plain_summary = generate_plain_summary(technical_report, synthesis)
        report = f"{plain_summary}\n\n---\n\n{technical_report}"
    except (ImportError, ValueError, RuntimeError) as e:
        print(f"\nError: {e}")
        sys.exit(1)

    output_file = output_dir / "compliance_report.md"

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("# ActGuard — EU Compliance Self-Assessment Report\n\n")
        f.write(f"> **Project:** {context.get('name', 'unknown')}  \n")
        f.write(f"> **Path:** `{repo_path}`  \n")
        f.write("> ⚠️ **Automated self-assessment only. This is not legal advice.**\n\n")
        f.write("---\n\n")
        f.write(report)

    print(f"\n✓ Markdown report saved to: {output_file}")

    print()
    print("─" * 60)
    print(report)
    print("─" * 60)
    print(f"\n✓ Done.")


if __name__ == "__main__":
    main()