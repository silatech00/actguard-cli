# Package taxonomy adapted from EuConform (MIT License).
# Copyright (c) 2026 Benedikt Hiepler — https://github.com/Hiepler/EuConform
# Reimplemented in Python for EU Compliance Scanner.

from __future__ import annotations

from typing import Literal

PackageCategory = Literal[
    "model",
    "ai-framework",
    "embedding",
    "inference-provider",
    "vector-store",
    "dataset",
    "tool",
    "platform",
    "security",
    "cloud",
    "high-risk",
]

KNOWN_AI_PACKAGES: dict[str, PackageCategory] = {
    "llama.cpp": "model",
    "llama-cpp-python": "model",
    "whisper.cpp": "model",
    "ggml": "model",
    "ctransformers": "model",
    "transformers": "ai-framework",
    "torch": "ai-framework",
    "pytorch": "ai-framework",
    "tensorflow": "ai-framework",
    "tensorflow-gpu": "ai-framework",
    "jax": "ai-framework",
    "keras": "ai-framework",
    "pytorch-lightning": "ai-framework",
    "scikit-learn": "ai-framework",
    "sklearn": "ai-framework",
    "scikit_learn": "ai-framework",
    "xgboost": "ai-framework",
    "lightgbm": "ai-framework",
    "spacy": "ai-framework",
    "huggingface-hub": "ai-framework",
    "diffusers": "ai-framework",
    "accelerate": "ai-framework",
    "peft": "ai-framework",
    "trl": "ai-framework",
    "onnxruntime": "ai-framework",
    "onnxruntime-gpu": "ai-framework",
    "mlflow": "ai-framework",
    "sentence-transformers": "embedding",
    "sentence_transformers": "embedding",
    "fastembed": "embedding",
    "openai-embeddings": "embedding",
    "cohere-embed": "embedding",
    "openai": "inference-provider",
    "anthropic": "inference-provider",
    "ollama": "inference-provider",
    "vllm": "inference-provider",
    "together-ai": "inference-provider",
    "replicate": "inference-provider",
    "groq": "inference-provider",
    "mistralai": "inference-provider",
    "cohere": "inference-provider",
    "google-generativeai": "inference-provider",
    "google_generativeai": "inference-provider",
    "ai21": "inference-provider",
    "pinecone": "vector-store",
    "pinecone-client": "vector-store",
    "weaviate": "vector-store",
    "weaviate-client": "vector-store",
    "qdrant": "vector-store",
    "qdrant-client": "vector-store",
    "milvus": "vector-store",
    "pymilvus": "vector-store",
    "chromadb": "vector-store",
    "chromadb-client": "vector-store",
    "pgvector": "vector-store",
    "faiss": "vector-store",
    "faiss-cpu": "vector-store",
    "faiss-gpu": "vector-store",
    "datasets": "dataset",
    "langchain": "tool",
    "langchain-core": "tool",
    "langchain-community": "tool",
    "llamaindex": "tool",
    "llama-index": "tool",
    "llama_index": "tool",
    "semantic-kernel": "tool",
    "autogen": "tool",
    "crewai": "tool",
    "dspy": "tool",
    "haystack-ai": "tool",
    "guidance": "tool",
    "guardrails": "tool",
    "guardrails-ai": "tool",
    "lmql": "tool",
    "outlines": "tool",
    "presidio_analyzer": "tool",
    "presidio-analyzer": "tool",
    "presidio_anonymizer": "tool",
    "presidio-anonymizer": "tool",
    "face_recognition": "high-risk",
    "deepface": "high-risk",
    "mediapipe": "high-risk",
    "streamlit": "platform",
    "flask": "platform",
    "fastapi": "platform",
    "django": "platform",
    "starlette": "platform",
    "stripe": "platform",
    "express": "platform",
    "next": "platform",
    "react": "platform",
    "cryptography": "security",
    "bcrypt": "security",
    "jose": "security",
    "pyjwt": "security",
    "passlib": "security",
    "keyring": "security",
    "boto3": "cloud",
    "azure": "cloud",
    "google_cloud": "cloud",
    "google-cloud-storage": "cloud",
}

KNOWN_AI_SCOPES: dict[str, PackageCategory] = {
    "@langchain": "tool",
    "@huggingface": "ai-framework",
    "@tensorflow": "ai-framework",
    "@anthropic-ai": "inference-provider",
    "@pinecone-database": "vector-store",
    "@qdrant": "vector-store",
    "@mistralai": "inference-provider",
    "@google": "inference-provider",
}

CATEGORY_LABELS: dict[PackageCategory, str] = {
    "model": "Model runtime",
    "ai-framework": "AI framework",
    "embedding": "Embeddings",
    "inference-provider": "AI provider",
    "vector-store": "Vector store",
    "dataset": "Dataset",
    "tool": "AI orchestration",
    "platform": "Platform",
    "security": "Security",
    "cloud": "Cloud infra",
    "high-risk": "High-risk signal",
}


def lookup_known_package(name: str) -> PackageCategory | None:
    lower = name.lower()
    exact = KNOWN_AI_PACKAGES.get(lower)
    if exact:
        return exact
    if lower.startswith("@") and "/" in lower:
        scope_end = lower.index("/")
        scope = lower[:scope_end]
        bare_name = lower[scope_end + 1 :]
        scope_kind = KNOWN_AI_SCOPES.get(scope)
        if scope_kind:
            return scope_kind
        bare_kind = KNOWN_AI_PACKAGES.get(bare_name)
        if bare_kind:
            return bare_kind
    return None


def category_label(category: PackageCategory | None) -> str:
    if not category:
        return "Signal"
    return CATEGORY_LABELS.get(category, category)
