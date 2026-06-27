"""Minimal fixture repos for deploy fingerprint tests."""

from __future__ import annotations

import textwrap
from pathlib import Path


def write_actguard_like_repo(root: Path) -> None:
    (root / "api").mkdir()
    (root / "web").mkdir()
    (root / "api" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    (root / "requirements.txt").write_text("fastapi\nuvicorn\npsycopg[binary]\nmistralai\n")
    (root / "web" / "package.json").write_text(
        '{"name":"web","dependencies":{"next":"15.0.0","react":"19.0.0"},'
        '"scripts":{"build":"next build","start":"next start"}}'
    )
    (root / "Dockerfile").write_text("FROM python:3.11-slim\nEXPOSE 8000\nCMD uvicorn api.main:app\n")
    (root / "railway.toml").write_text('[build]\nbuilder = "DOCKERFILE"\n')


def write_streamlit_repo(root: Path) -> None:
    (root / "app.py").write_text("import streamlit as st\nst.title('Demo')\n")
    (root / "requirements.txt").write_text("streamlit\nopenai\n")


def write_next_spa_repo(root: Path) -> None:
    (root / "package.json").write_text(
        '{"dependencies":{"react":"19.0.0","next":"15.0.0"},'
        '"scripts":{"build":"next build"}}'
    )
