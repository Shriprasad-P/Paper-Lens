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
        )
