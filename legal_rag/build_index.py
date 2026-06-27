"""One-time script to embed legal chunks and store them in ChromaDB."""

from __future__ import annotations

from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

from legal_rag.chunker import chunk_all_regulations

PACKAGE_DIR = Path(__file__).resolve().parent
CHROMA_DIR = PACKAGE_DIR / "chroma_db"
COLLECTION_NAME = "eu_legal_texts"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
BATCH_SIZE = 64


def build_index() -> int:
    print("Chunking legal texts...")
    chunks = chunk_all_regulations()
    total = len(chunks)
    print(f"Total chunks: {total}")

    print(f"Loading embedding model ({EMBEDDING_MODEL})...")
    model = SentenceTransformer(EMBEDDING_MODEL)

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    if client.get_or_create_collection(COLLECTION_NAME).count() > 0:
        client.delete_collection(COLLECTION_NAME)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    for start in range(0, total, BATCH_SIZE):
        batch = chunks[start : start + BATCH_SIZE]
        texts = [c["text"] for c in batch]
        embeddings = model.encode(texts, show_progress_bar=False).tolist()

        ids = [f"chunk_{start + i}" for i in range(len(batch))]
        metadatas = [
            {
                "regulation": c["regulation"],
                "article": c["article"],
                "title": c["title"] or "",
            }
            for c in batch
        ]

        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )
        done = min(start + BATCH_SIZE, total)
        print(f"Embedded {done}/{total} chunks...")

    print(f"Index built at {CHROMA_DIR} ({collection.count()} documents)")
    return collection.count()


if __name__ == "__main__":
    build_index()
