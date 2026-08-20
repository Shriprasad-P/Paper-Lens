"""Application configuration with environment-backed defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings kept small until a feature needs more configuration."""

    app_name: str = "PaperLens API"
    environment: str = "development"
    database_url: str = "sqlite:///./paperlens.db"
    frontend_origin: str = "http://localhost:3000"
    arxiv_request_timeout: float = 30.0
    paper_storage_path: str = "data/papers"
    max_pdf_size: int = 50 * 1024 * 1024
    ai_provider: str = "openai_compatible"
    ai_model: str = "gpt-4o-mini"
    ai_api_key: str | None = None
    ai_base_url: str = "https://api.openai.com/v1"
    ai_request_timeout: float = 60.0
    ai_max_retries: int = 2
    chat_retrieval_top_k: int = 8
    chat_max_context_chars: int = 12_000
    chat_min_relevance: float = 0.1
    chat_max_question_chars: int = 4_000
    embedding_provider: str = "none"
    embedding_model: str = "hash-v1"
    embedding_dimension: int = 64
    embedding_version: str = "v1"
    semantic_retrieval_top_k: int = 8
    hybrid_retrieval_enabled: bool = False
    retrieval_mode: str = "LEXICAL"
    research_max_search_queries: int = 6
    research_max_candidates: int = 30
    research_max_ingested_papers: int = 8
    research_max_iterations: int = 3
    research_ingestion_concurrency: int = 2
    research_max_context_chars: int = 12_000
    research_max_provider_calls: int = 32

    @classmethod
    def from_env(cls) -> "Settings":
        """Build settings from environment variables without requiring a package."""

        defaults = cls()
        return cls(
            app_name=os.getenv("PAPERLENS_APP_NAME", defaults.app_name),
            environment=os.getenv("PAPERLENS_ENVIRONMENT", defaults.environment),
            database_url=os.getenv("PAPERLENS_DATABASE_URL", defaults.database_url),
            frontend_origin=os.getenv("PAPERLENS_FRONTEND_ORIGIN", defaults.frontend_origin),
            arxiv_request_timeout=float(
                os.getenv("PAPERLENS_ARXIV_REQUEST_TIMEOUT", str(defaults.arxiv_request_timeout))
            ),
            paper_storage_path=os.getenv("PAPERLENS_STORAGE_PATH", defaults.paper_storage_path),
            max_pdf_size=int(os.getenv("PAPERLENS_MAX_PDF_SIZE", str(defaults.max_pdf_size))),
            ai_provider=os.getenv("AI_PROVIDER", defaults.ai_provider),
            ai_model=os.getenv("AI_MODEL", defaults.ai_model),
            ai_api_key=os.getenv("AI_API_KEY") or None,
            ai_base_url=os.getenv("AI_BASE_URL", defaults.ai_base_url),
            ai_request_timeout=float(os.getenv("AI_REQUEST_TIMEOUT", str(defaults.ai_request_timeout))),
            ai_max_retries=int(os.getenv("AI_MAX_RETRIES", str(defaults.ai_max_retries))),
            chat_retrieval_top_k=max(1, min(int(os.getenv("CHAT_RETRIEVAL_TOP_K", str(defaults.chat_retrieval_top_k))), 20)),
            chat_max_context_chars=max(1_000, int(os.getenv("CHAT_MAX_CONTEXT_CHARS", str(defaults.chat_max_context_chars)))),
            chat_min_relevance=max(0.0, float(os.getenv("CHAT_MIN_RELEVANCE", str(defaults.chat_min_relevance)))),
            chat_max_question_chars=max(100, int(os.getenv("CHAT_MAX_QUESTION_CHARS", str(defaults.chat_max_question_chars)))),
            embedding_provider=os.getenv("EMBEDDING_PROVIDER", defaults.embedding_provider),
            embedding_model=os.getenv("EMBEDDING_MODEL", defaults.embedding_model),
            embedding_dimension=max(8, int(os.getenv("EMBEDDING_DIMENSION", str(defaults.embedding_dimension)))),
            embedding_version=os.getenv("EMBEDDING_VERSION", defaults.embedding_version),
            semantic_retrieval_top_k=max(1, min(int(os.getenv("SEMANTIC_RETRIEVAL_TOP_K", str(defaults.semantic_retrieval_top_k))), 20)),
            hybrid_retrieval_enabled=os.getenv("HYBRID_RETRIEVAL_ENABLED", str(defaults.hybrid_retrieval_enabled)).lower() in {"1", "true", "yes", "on"},
            retrieval_mode=os.getenv("RETRIEVAL_MODE", defaults.retrieval_mode).upper(),
            research_max_search_queries=max(3, min(int(os.getenv("RESEARCH_MAX_SEARCH_QUERIES", str(defaults.research_max_search_queries))), 8)),
            research_max_candidates=max(1, min(int(os.getenv("RESEARCH_MAX_CANDIDATES", str(defaults.research_max_candidates))), 30)),
            research_max_ingested_papers=max(1, min(int(os.getenv("RESEARCH_MAX_INGESTED_PAPERS", str(defaults.research_max_ingested_papers))), 8)),
            research_max_iterations=max(1, min(int(os.getenv("RESEARCH_MAX_ITERATIONS", str(defaults.research_max_iterations))), 3)),
            research_ingestion_concurrency=max(1, min(int(os.getenv("RESEARCH_INGESTION_CONCURRENCY", str(defaults.research_ingestion_concurrency))), 4)),
            research_max_context_chars=max(2_000, min(int(os.getenv("RESEARCH_MAX_CONTEXT_CHARS", str(defaults.research_max_context_chars))), 24_000)),
            research_max_provider_calls=max(1, min(int(os.getenv("RESEARCH_MAX_PROVIDER_CALLS", str(defaults.research_max_provider_calls))), 64)),
        )
