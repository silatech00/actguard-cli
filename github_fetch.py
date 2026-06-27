"""
Selective GitHub repository fetcher via REST API.
Fetches only source code and dependency manifests — not node_modules, venv, or build artifacts.
"""

from __future__ import annotations

import base64
import fnmatch
import io
import os
import re
import tarfile
import tempfile
import time
from pathlib import Path

import requests

API_BASE = "https://api.github.com"
MAX_FILE_SIZE = 1_048_576  # 1 MB
REQUEST_TIMEOUT = 90
RETRY_STATUS = {502, 503, 504}
MAX_RETRIES = 3

SKIP_PATH_PARTS = {
    "node_modules", "venv", ".venv", "env", "__pycache__", ".git", "dist", "build", "vendor",
}

MANIFEST_NAMES = {"requirements.txt", "package.json", "pyproject.toml"}
MANIFEST_GLOBS = ("requirements-*.txt",)
EXTRA_FILENAMES = {
    "readme.md", "readme.rst", "readme",
    "dockerfile", "docker-compose.yml", "docker-compose.yaml", ".env.example",
    "vercel.json", "fly.toml", "railway.toml", "render.yaml", "netlify.toml",
}
SOURCE_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".sql", ".md", ".yml", ".yaml"}


def parse_github_url(url: str) -> tuple[str, str]:
    """Extract (owner, repo) from a GitHub URL or owner/repo shorthand."""
    url = url.strip().rstrip("/")
    if not url:
        raise ValueError("GitHub URL is empty.")

    if re.fullmatch(r"[\w.-]+/[\w.-]+", url):
        owner, repo = url.split("/", 1)
        return owner, repo.removesuffix(".git")

    match = re.search(r"github\.com[:/](?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?/?$", url, re.I)
    if match:
        return match.group("owner"), match.group("repo")

    raise ValueError(
        f"Invalid GitHub URL: {url!r}. "
        "Expected https://github.com/owner/repo or owner/repo."
    )


def _auth_headers(token: str | None, *, accept: str = "application/vnd.github+json") -> dict[str, str]:
    headers = {"Accept": accept}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _request(method: str, url: str, token: str | None, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    last_resp: requests.Response | None = None

    for attempt in range(MAX_RETRIES):
        resp = requests.request(method, url, headers=_auth_headers(token), **kwargs)
        last_resp = resp

        if resp.status_code in RETRY_STATUS and attempt < MAX_RETRIES - 1:
            time.sleep(2 ** attempt)
            continue

        if resp.status_code == 404:
            raise requests.HTTPError(
                "Repository not found or not accessible. "
                "If this is a private repo, provide a personal access token with read access.",
                response=resp,
            )
        if resp.status_code == 403:
            remaining = resp.headers.get("X-RateLimit-Remaining", "?")
            raise requests.HTTPError(
                f"GitHub API rate limit exceeded or access forbidden (remaining: {remaining}). "
                "Try again later or provide a personal access token.",
                response=resp,
            )
        if resp.status_code in RETRY_STATUS:
            raise requests.HTTPError(
                f"GitHub API temporarily unavailable ({resp.status_code}). "
                "Try again in a moment or provide a personal access token.",
                response=resp,
            )
        resp.raise_for_status()
        return resp

    assert last_resp is not None
    last_resp.raise_for_status()
    return last_resp


def get_default_branch(owner: str, repo: str, token: str | None) -> str:
    repo_resp = _request("GET", f"{API_BASE}/repos/{owner}/{repo}", token)
    return repo_resp.json().get("default_branch", "main")


def _resolve_tree_sha(owner: str, repo: str, ref: str, token: str | None) -> str:
    """Resolve a branch/tag name to a git tree SHA (Git Trees API requires a SHA, not a ref)."""
    ref_resp = _request("GET", f"{API_BASE}/repos/{owner}/{repo}/git/ref/heads/{ref}", token)
    commit_sha = ref_resp.json()["object"]["sha"]
    commit_resp = _request("GET", f"{API_BASE}/repos/{owner}/{repo}/git/commits/{commit_sha}", token)
    return commit_resp.json()["tree"]["sha"]


def get_repo_tree(owner: str, repo: str, token: str | None, default_branch: str | None = None) -> list[dict]:
    """Return recursive tree entries for the repo's default branch."""
    branch = default_branch or get_default_branch(owner, repo, token)
    tree_sha = _resolve_tree_sha(owner, repo, branch, token)
    tree_resp = _request(
        "GET",
        f"{API_BASE}/repos/{owner}/{repo}/git/trees/{tree_sha}?recursive=1",
        token,
    )
    data = tree_resp.json()
    return data.get("tree", [])


def _path_should_skip(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    return any(part in SKIP_PATH_PARTS for part in parts)


def _is_manifest(filename: str) -> bool:
    if filename in MANIFEST_NAMES:
        return True
    return any(fnmatch.fnmatch(filename, pattern) for pattern in MANIFEST_GLOBS)


def _file_is_relevant(path: str, size: int = 0) -> bool:
    if not path or _path_should_skip(path):
        return False
    if size > MAX_FILE_SIZE:
        return False
    filename = Path(path).name
    ext = Path(path).suffix.lower()
    return (
        _is_manifest(filename)
        or filename.lower() in EXTRA_FILENAMES
        or ext in SOURCE_EXTENSIONS
    )


def filter_relevant_files(tree: list[dict]) -> list[dict]:
    """Filter tree entries to compliance-relevant source files and manifests."""
    relevant: list[dict] = []
    for entry in tree:
        if entry.get("type") != "blob":
            continue
        path = entry.get("path", "")
        if _file_is_relevant(path, entry.get("size") or 0):
            relevant.append(entry)
    return relevant


def fetch_file_content(
    owner: str,
    repo: str,
    path: str,
    token: str | None,
    default_branch: str | None = None,
) -> str:
    """Fetch a single file's content as UTF-8 text."""
    if default_branch:
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{default_branch}/{path}"
        resp = _request("GET", raw_url, token)
        try:
            return resp.content.decode("utf-8")
        except UnicodeDecodeError:
            return ""

    contents_resp = _request(
        "GET",
        f"{API_BASE}/repos/{owner}/{repo}/contents/{path}",
        token,
    )
    payload = contents_resp.json()
    if isinstance(payload, list):
        return ""
    encoding = payload.get("encoding", "")
    content_b64 = payload.get("content", "")
    if encoding == "base64" and content_b64:
        try:
            raw = base64.b64decode(content_b64)
            return raw.decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            return ""
    return ""


def _download_via_tree(
    owner: str,
    repo: str,
    token: str | None,
    default_branch: str,
) -> str:
    tree = get_repo_tree(owner, repo, token, default_branch=default_branch)
    relevant = filter_relevant_files(tree)
    total = len([e for e in tree if e.get("type") == "blob"])
    print(f"Fetching {len(relevant)} relevant files out of {total} total...")

    tmpdir = tempfile.mkdtemp(prefix="eu-github-")
    for entry in relevant:
        path = entry["path"]
        dest = Path(tmpdir) / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = fetch_file_content(owner, repo, path, token, default_branch=default_branch)
        dest.write_text(content, encoding="utf-8", errors="ignore")
    return tmpdir


def _download_via_tarball(
    owner: str,
    repo: str,
    token: str | None,
    default_branch: str,
) -> str:
    """Fallback: single tarball download when the Git Trees API is slow or unavailable."""
    print("Git Trees API unavailable — falling back to tarball download...")
    tarball_resp = _request(
        "GET",
        f"{API_BASE}/repos/{owner}/{repo}/tarball/{default_branch}",
        token,
        allow_redirects=True,
    )

    tmpdir = tempfile.mkdtemp(prefix="eu-github-")
    extracted = 0
    with tarfile.open(fileobj=io.BytesIO(tarball_resp.content), mode="r:gz") as archive:
        root_prefix = archive.getnames()[0].split("/")[0] if archive.getnames() else ""
        for member in archive.getmembers():
            if not member.isfile():
                continue
            rel_path = member.name
            if root_prefix and rel_path.startswith(root_prefix + "/"):
                rel_path = rel_path[len(root_prefix) + 1 :]
            if not _file_is_relevant(rel_path, member.size):
                continue
            dest = Path(tmpdir) / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            extracted_file = archive.extractfile(member)
            if extracted_file is None:
                continue
            dest.write_bytes(extracted_file.read())
            extracted += 1

    print(f"Fetched {extracted} relevant files via tarball.")
    return tmpdir


def download_repo_to_tempdir(github_url: str, token: str | None) -> str:
    """
    Fetch filtered repo files into a temp directory preserving relative paths.
    Returns the temp directory path.
    """
    owner, repo = parse_github_url(github_url)
    default_branch = get_default_branch(owner, repo, token)

    try:
        return _download_via_tree(owner, repo, token, default_branch)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status in RETRY_STATUS or status is None:
            return _download_via_tarball(owner, repo, token, default_branch)
        raise


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python github_fetch.py <github_url> [token]")
        sys.exit(1)

    url = sys.argv[1]
    pat = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("GITHUB_TOKEN")

    try:
        root = download_repo_to_tempdir(url, pat)
        print(f"\nDownloaded to: {root}\n")
        for dirpath, _dirnames, filenames in os.walk(root):
            level = dirpath.replace(root, "").count(os.sep)
            indent = "  " * level
            print(f"{indent}{os.path.basename(dirpath)}/")
            for name in sorted(filenames):
                print(f"{indent}  {name}")
    except (ValueError, requests.HTTPError) as exc:
        print(f"Error: {exc}")
        sys.exit(1)
