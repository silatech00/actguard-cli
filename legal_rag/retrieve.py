"""Retrieve relevant legal article chunks from the local ChromaDB index."""

from __future__ import annotations

import gc
import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from actguard.config import REPO_ROOT, chroma_dir

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

COLLECTION_NAME = "eu_legal_texts"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_MODEL_DIRNAME = "all-MiniLM-L6-v2"

CHROMA_DIR = chroma_dir()

_model: SentenceTransformer | None = None
_collection: Any = None


def _bundled_model_path() -> Path | None:
    model_dir = REPO_ROOT / "models" / EMBEDDING_MODEL_DIRNAME
    if model_dir.is_dir() and (model_dir / "config.json").exists():
        return model_dir
    return None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        bundled = _bundled_model_path()
        if bundled is not None:
            os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(REPO_ROOT / "models"))
            _model = SentenceTransformer(str(bundled))
        else:
            _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def _get_collection():
    global _collection
    if _collection is None:
        import chromadb

        if not CHROMA_DIR.exists():
            raise FileNotFoundError(
                f"ChromaDB index not found at {CHROMA_DIR}. "
                "Run: python -m legal_rag.build_index"
            )
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _collection = client.get_collection(COLLECTION_NAME)
    return _collection


def release_rag_resources() -> None:
    """Unload embedding model and Chroma collection to free RAM after a job."""
    global _model, _collection
    if _model is None and _collection is None:
        return
    _model = None
    _collection = None
    gc.collect()
    logger.info("Released RAG resources (embedding model + Chroma collection).")


@contextmanager
def rag_job_context():
    """Load RAG on first retrieve during the job; release when the job finishes."""
    try:
        yield
    finally:
        release_rag_resources()


def retrieve_relevant_articles(
    query: str,
    regulation: str | None = None,
    top_k: int = 3,
) -> list[dict]:
    """Return the top_k most similar legal chunks for a query."""
    model = _get_model()
    collection = _get_collection()

    query_embedding = model.encode([query], show_progress_bar=False).tolist()

    where = {"regulation": regulation} if regulation else None
    results = collection.query(
        query_embeddings=query_embedding,
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    articles: list[dict] = []
    if not results["ids"] or not results["ids"][0]:
        return articles

    for doc_id, doc, meta, distance in zip(
        results["ids"][0],
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        score = 1.0 - distance
        articles.append(
            {
                "regulation": meta.get("regulation", ""),
                "article": meta.get("article", ""),
                "title": meta.get("title", ""),
                "text": doc,
                "score": round(score, 4),
            }
        )

    return articles
