"""Deploy-relevant package and config signals (beyond compliance SIGNALS)."""

from __future__ import annotations

from typing import Literal

DeploySignalCategory = Literal[
    "database",
    "cache",
    "worker",
    "framework",
    "vector_store",
    "analytics",
    "vendor",
    "realtime",
    "orm",
]

DEPLOY_PACKAGE_SIGNALS: dict[str, tuple[DeploySignalCategory, str]] = {
    "psycopg": ("database", "PostgreSQL driver"),
    "psycopg2": ("database", "PostgreSQL driver"),
    "asyncpg": ("database", "PostgreSQL async driver"),
    "sqlalchemy": ("database", "SQLAlchemy ORM"),
    "prisma": ("orm", "Prisma ORM"),
    "drizzle": ("orm", "Drizzle ORM"),
    "mongoose": ("database", "MongoDB driver"),
    "pymongo": ("database", "MongoDB driver"),
    "redis": ("cache", "Redis client"),
    "celery": ("worker", "Celery task queue"),
    "rq": ("worker", "RQ task queue"),
    "bullmq": ("worker", "BullMQ task queue"),
    "supabase": ("database", "Supabase client"),
    "chromadb": ("vector_store", "ChromaDB embedded vector store"),
    "qdrant_client": ("vector_store", "Qdrant vector store"),
    "pinecone": ("vector_store", "Pinecone vector store"),
    "vllm": ("vector_store", "vLLM local inference"),
    "ollama": ("vector_store", "Ollama local inference"),
    "torch": ("vector_store", "PyTorch (local ML inference)"),
    "streamlit": ("framework", "Streamlit app"),
    "fastapi": ("framework", "FastAPI"),
    "flask": ("framework", "Flask"),
    "django": ("framework", "Django"),
    "next": ("framework", "Next.js"),
    "nuxt": ("framework", "Nuxt.js"),
    "sveltekit": ("framework", "SvelteKit"),
    "remix": ("framework", "Remix"),
    "express": ("framework", "Express.js"),
    "react": ("framework", "React"),
    "socketio": ("realtime", "Socket.IO"),
    "stripe": ("vendor", "Stripe payments"),
    "openai": ("vendor", "OpenAI API"),
    "anthropic": ("vendor", "Anthropic API"),
    "mistralai": ("vendor", "Mistral API"),
    "sendgrid": ("vendor", "SendGrid email"),
    "resend": ("vendor", "Resend email"),
    "posthog": ("analytics", "PostHog analytics"),
    "mixpanel": ("analytics", "Mixpanel analytics"),
    "segment": ("analytics", "Segment analytics"),
    "boto3": ("vendor", "AWS SDK"),
    "google_cloud": ("vendor", "Google Cloud SDK"),
    "azure": ("vendor", "Azure SDK"),
}

DEPLOY_PACKAGE_ALIASES: dict[str, str] = {
    "psycopg2-binary": "psycopg2",
    "psycopg-binary": "psycopg",
    "@prisma/client": "prisma",
    "drizzle-orm": "drizzle",
    "bull": "bullmq",
    "socket.io": "socketio",
    "socket.io-client": "socketio",
    "@supabase/supabase-js": "supabase",
    "react-ga4": "analytics",
    "react-ga": "analytics",
    "@next/third-parties": "analytics",
}

ANALYTICS_PACKAGES = frozenset({"posthog", "mixpanel", "segment", "analytics"})

VENDOR_PACKAGES = frozenset(
    k for k, (cat, _) in DEPLOY_PACKAGE_SIGNALS.items() if cat == "vendor"
)

DEPLOY_CONFIG_FILES: dict[str, str] = {
    "dockerfile": "Dockerfile",
    "docker-compose.yml": "docker-compose.yml",
    "docker-compose.yaml": "docker-compose.yaml",
    "vercel.json": "vercel.json",
    "fly.toml": "fly.toml",
    "railway.toml": "railway.toml",
    "render.yaml": "render.yaml",
    "netlify.toml": "netlify.toml",
}

EU_REGION_PINS: dict[str, tuple[str, ...]] = {
    "railway.toml": ("europe-west4", "europe-west4-drams3a"),
    "vercel.json": ("fra1", "cdg1", "eu"),
    "fly.toml": ("ams", "fra", "cdg", "lhr"),
}
