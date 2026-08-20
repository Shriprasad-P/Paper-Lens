"""Application configuration with environment-backed defaults."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from dataclasses import dataclass
from typing import ClassVar
from urllib.parse import urlparse


class ConfigurationError(ValueError):
    """Raised when runtime configuration is unsafe or malformed."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings kept small until a feature needs more configuration."""

    app_name: str = "PaperLens API"
    environment: str = "development"
    database_url: str = "sqlite:///./paperlens.db"
    frontend_origin: str = "http://localhost:3000"
    frontend_origins: str | None = None
    backend_public_url: str = "http://localhost:8000"
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
    max_request_body_size: int = 1_048_576
    max_paper_text_chars: int = 5_000_000
    max_page_count: int = 500
    request_timeout: float = 120.0
    research_step_timeout: float = 180.0
    max_concurrent_ingestions: int = 2
    metrics_enabled: bool = True
    auto_create_schema: bool = True
    trusted_proxy_ips: str = ""
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_timeout: float = 30.0
    rate_limits_enabled: bool = False
    rate_limit_ingestion_per_minute: int = 4
    rate_limit_ai_per_minute: int = 6
    rate_limit_chat_per_minute: int = 20
    rate_limit_research_per_minute: int = 2
    release_version: str = "0.1.0-beta"
    build_sha: str = "local"
    build_timestamp: str = "unknown"
    paper_storage_provider: str = "local"
    ai_analysis_enabled: bool = False
    semantic_retrieval_enabled: bool = False
    research_agent_enabled: bool = False
    desktop_token: str | None = None

    _allowed_environments: ClassVar[frozenset[str]] = frozenset({"development", "test", "staging", "production"})

    @classmethod
    def from_env(cls) -> "Settings":
        """Build settings from environment variables without requiring a package."""

        defaults = cls()
        ai_provider = os.getenv("AI_PROVIDER", defaults.ai_provider)
        ai_api_key = os.getenv("AI_API_KEY") or None
        embedding_provider = os.getenv("EMBEDDING_PROVIDER", defaults.embedding_provider)
        ai_enabled_raw = os.getenv("PAPERLENS_AI_ANALYSIS_ENABLED") or None
        semantic_enabled_raw = os.getenv("PAPERLENS_SEMANTIC_RETRIEVAL_ENABLED") or None
        research_enabled_raw = os.getenv("PAPERLENS_RESEARCH_AGENT_ENABLED") or None
        result = cls(
            app_name=os.getenv("PAPERLENS_APP_NAME", defaults.app_name),
            environment=_first_env("PAPERLENS_ENVIRONMENT", "APP_ENV", default=defaults.environment),
            database_url=_first_env("PAPERLENS_DATABASE_URL", "DATABASE_URL", default=defaults.database_url),
            frontend_origin=_first_env("PAPERLENS_FRONTEND_ORIGIN", "FRONTEND_ORIGIN", default=defaults.frontend_origin),
            frontend_origins=os.getenv("PAPERLENS_FRONTEND_ORIGINS") or None,
            backend_public_url=os.getenv("PAPERLENS_BACKEND_PUBLIC_URL", os.getenv("BACKEND_PUBLIC_URL", defaults.backend_public_url)),
            arxiv_request_timeout=float(
                os.getenv("PAPERLENS_ARXIV_REQUEST_TIMEOUT", str(defaults.arxiv_request_timeout))
            ),
            paper_storage_path=_first_env("PAPERLENS_STORAGE_PATH", "PAPER_STORAGE_PATH", default=defaults.paper_storage_path),
            max_pdf_size=int(os.getenv("PAPERLENS_MAX_PDF_SIZE", str(defaults.max_pdf_size))),
            ai_provider=ai_provider,
            ai_model=os.getenv("AI_MODEL", defaults.ai_model),
            ai_api_key=ai_api_key,
            ai_base_url=os.getenv("AI_BASE_URL", defaults.ai_base_url),
            ai_request_timeout=float(os.getenv("AI_REQUEST_TIMEOUT", str(defaults.ai_request_timeout))),
            ai_max_retries=int(os.getenv("AI_MAX_RETRIES", str(defaults.ai_max_retries))),
            chat_retrieval_top_k=max(1, min(int(os.getenv("CHAT_RETRIEVAL_TOP_K", str(defaults.chat_retrieval_top_k))), 20)),
            chat_max_context_chars=max(1_000, int(os.getenv("CHAT_MAX_CONTEXT_CHARS", str(defaults.chat_max_context_chars)))),
            chat_min_relevance=max(0.0, float(os.getenv("CHAT_MIN_RELEVANCE", str(defaults.chat_min_relevance)))),
            chat_max_question_chars=max(100, int(os.getenv("CHAT_MAX_QUESTION_CHARS", str(defaults.chat_max_question_chars)))),
            embedding_provider=embedding_provider,
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
            max_request_body_size=max(16_384, int(os.getenv("PAPERLENS_MAX_REQUEST_BODY_SIZE", str(defaults.max_request_body_size)))),
            max_paper_text_chars=max(100_000, int(os.getenv("PAPERLENS_MAX_PAPER_TEXT_CHARS", str(defaults.max_paper_text_chars)))),
            max_page_count=max(1, int(os.getenv("PAPERLENS_MAX_PAGE_COUNT", str(defaults.max_page_count)))),
            request_timeout=max(1.0, float(os.getenv("PAPERLENS_REQUEST_TIMEOUT", str(defaults.request_timeout)))),
            research_step_timeout=max(1.0, float(os.getenv("RESEARCH_STEP_TIMEOUT", str(defaults.research_step_timeout)))),
            max_concurrent_ingestions=max(1, min(int(os.getenv("MAX_CONCURRENT_INGESTIONS", str(defaults.max_concurrent_ingestions))), 8)),
            metrics_enabled=_as_bool(os.getenv("PAPERLENS_METRICS_ENABLED", str(defaults.metrics_enabled))),
            auto_create_schema=_as_bool(os.getenv("PAPERLENS_AUTO_CREATE_SCHEMA", str(defaults.auto_create_schema))),
            trusted_proxy_ips=os.getenv("PAPERLENS_TRUSTED_PROXY_IPS", defaults.trusted_proxy_ips),
            db_pool_size=int(os.getenv("DB_POOL_SIZE", str(defaults.db_pool_size))),
            db_max_overflow=int(os.getenv("DB_MAX_OVERFLOW", str(defaults.db_max_overflow))),
            db_pool_timeout=float(os.getenv("DB_POOL_TIMEOUT", str(defaults.db_pool_timeout))),
            rate_limits_enabled=_as_bool(os.getenv("PAPERLENS_RATE_LIMITS_ENABLED", str(defaults.rate_limits_enabled))),
            rate_limit_ingestion_per_minute=int(os.getenv("PAPERLENS_RATE_LIMIT_INGESTION_PER_MINUTE", str(defaults.rate_limit_ingestion_per_minute))),
            rate_limit_ai_per_minute=int(os.getenv("PAPERLENS_RATE_LIMIT_AI_PER_MINUTE", str(defaults.rate_limit_ai_per_minute))),
            rate_limit_chat_per_minute=int(os.getenv("PAPERLENS_RATE_LIMIT_CHAT_PER_MINUTE", str(defaults.rate_limit_chat_per_minute))),
            rate_limit_research_per_minute=int(os.getenv("PAPERLENS_RATE_LIMIT_RESEARCH_PER_MINUTE", str(defaults.rate_limit_research_per_minute))),
            release_version=os.getenv("PAPERLENS_RELEASE_VERSION", defaults.release_version),
            build_sha=os.getenv("PAPERLENS_BUILD_SHA", defaults.build_sha),
            build_timestamp=os.getenv("PAPERLENS_BUILD_TIMESTAMP", defaults.build_timestamp),
            paper_storage_provider=os.getenv("PAPERLENS_STORAGE_PROVIDER", defaults.paper_storage_provider).lower(),
            ai_analysis_enabled=_as_bool(ai_enabled_raw) if ai_enabled_raw is not None else bool(ai_api_key and ai_provider.lower() not in {"none", "disabled"}),
            semantic_retrieval_enabled=_as_bool(semantic_enabled_raw) if semantic_enabled_raw is not None else embedding_provider.lower() not in {"none", "disabled"},
            research_agent_enabled=_as_bool(research_enabled_raw) if research_enabled_raw is not None else bool(ai_api_key and ai_provider.lower() not in {"none", "disabled"}),
            desktop_token=os.getenv("PAPERLENS_DESKTOP_TOKEN") or None,
        )
        return result

    @property
    def allowed_origins(self) -> list[str]:
        """Return an explicit, de-duplicated CORS allow-list."""

        values = self.frontend_origins or self.frontend_origin
        return list(dict.fromkeys(item.strip() for item in values.split(",") if item.strip()))

    def validate(self) -> None:
        """Validate values that can otherwise cause an unsafe or broken startup."""

        environment = self.environment.strip().lower()
        if environment not in self._allowed_environments:
            raise ConfigurationError("PAPERLENS_ENVIRONMENT must be development, test, staging, or production.")
        if not self.database_url.startswith(("sqlite:", "postgresql", "postgres:")):
            raise ConfigurationError("PAPERLENS_DATABASE_URL must use SQLite or PostgreSQL.")
        parsed_ai_url = urlparse(self.ai_base_url)
        if parsed_ai_url.scheme not in {"http", "https"} or not parsed_ai_url.netloc:
            raise ConfigurationError("AI_BASE_URL must be an absolute HTTP(S) URL.")
        origins = self.allowed_origins
        if not origins:
            raise ConfigurationError("At least one explicit frontend origin is required.")
        if "*" in origins:
            raise ConfigurationError("Wildcard frontend origins are not allowed with credentialed CORS.")
        for origin in origins:
            parsed = urlparse(origin)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ConfigurationError("PAPERLENS_FRONTEND_ORIGIN values must be absolute HTTP(S) origins.")
        backend_url = urlparse(self.backend_public_url)
        if backend_url.scheme not in {"http", "https"} or not backend_url.netloc:
            raise ConfigurationError("BACKEND_PUBLIC_URL must be an absolute HTTP(S) URL.")
        numeric = {
            "max_pdf_size": self.max_pdf_size,
            "max_request_body_size": self.max_request_body_size,
            "max_paper_text_chars": self.max_paper_text_chars,
            "max_page_count": self.max_page_count,
            "max_concurrent_ingestions": self.max_concurrent_ingestions,
        }
        if any(value <= 0 for value in numeric.values()):
            raise ConfigurationError("Resource limits must be positive.")
        if self.ai_max_retries < 0 or self.ai_max_retries > 5:
            raise ConfigurationError("AI_MAX_RETRIES must be between 0 and 5.")
        if self.environment == "production" and self.auto_create_schema:
            raise ConfigurationError("PAPERLENS_AUTO_CREATE_SCHEMA must be false in production; run migrations explicitly.")
        if self.environment == "production" and not self.database_url.startswith(("postgresql", "postgres:")):
            raise ConfigurationError("Production deployments require a PostgreSQL DATABASE_URL.")
        if self.paper_storage_provider != "local":
            raise ConfigurationError("PAPERLENS_STORAGE_PROVIDER must be 'local' until an object-storage adapter is configured.")
        if self.db_pool_size <= 0 or self.db_max_overflow < 0 or self.db_pool_timeout <= 0:
            raise ConfigurationError("Database pool settings must be positive and bounded.")
        limits = {
            "rate_limit_ingestion_per_minute": self.rate_limit_ingestion_per_minute,
            "rate_limit_ai_per_minute": self.rate_limit_ai_per_minute,
            "rate_limit_chat_per_minute": self.rate_limit_chat_per_minute,
            "rate_limit_research_per_minute": self.rate_limit_research_per_minute,
        }
        if any(value <= 0 for value in limits.values()):
            raise ConfigurationError("Rate limits must be positive.")
        if not self.release_version.strip() or not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+-]*", self.release_version.strip()):
            raise ConfigurationError("PAPERLENS_RELEASE_VERSION must be a safe release identifier.")
        if self.desktop_token is not None and len(self.desktop_token) < 16:
            raise ConfigurationError("PAPERLENS_DESKTOP_TOKEN must contain at least 16 characters when configured.")
        storage = Path(self.paper_storage_path).expanduser()
        if storage.exists() and not storage.is_dir():
            raise ConfigurationError("PAPERLENS_STORAGE_PATH must point to a directory.")
        if self.environment == "production":
            if not storage.exists() or not storage.is_dir():
                raise ConfigurationError("PAPERLENS_STORAGE_PATH must exist as a directory in production.")
            if not (storage.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)):
                raise ConfigurationError("PAPERLENS_STORAGE_PATH must be writable in production.")


def _as_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"Invalid boolean configuration value: {value!r}.")


def _first_env(*names: str, default: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value
    return default
