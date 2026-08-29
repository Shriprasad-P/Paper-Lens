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
    # Phase 14 names are explicit while the older aliases remain supported for
    # local deployments and existing callers.
    pdf_max_bytes: int | None = None
    pdf_max_pages: int | None = None
    pdf_max_text_chars: int | None = None
    pdf_max_text_chars_per_page: int | None = None
    pdf_max_images_per_page: int = 100
    pdf_max_total_images: int = 1_000
    pdf_parse_timeout_seconds: float = 120.0
    pdf_parse_concurrency: int = 2
    pdf_parser_memory_limit_bytes: int | None = None
    pdf_parser_cpu_limit_seconds: float | None = None
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
    research_worker_enabled: bool = False
    research_worker_concurrency: int = 1
    research_worker_poll_seconds: float = 2.0
    research_claim_lease_seconds: int = 60
    research_max_attempts: int = 3
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
    auth_required: bool = False
    auth_cookie_name: str = "paperlens_session"
    auth_session_ttl_seconds: int = 60 * 60 * 24 * 7

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
        research_worker_enabled_raw = os.getenv("PAPERLENS_RESEARCH_WORKER_ENABLED") or None
        environment = _first_env("PAPERLENS_ENVIRONMENT", "APP_ENV", default=defaults.environment)
        auth_required_raw = os.getenv("PAPERLENS_AUTH_REQUIRED")
        legacy_pdf_bytes = int(os.getenv("PAPERLENS_MAX_PDF_SIZE", str(defaults.max_pdf_size)))
        legacy_pdf_pages = int(os.getenv("PAPERLENS_MAX_PAGE_COUNT", str(defaults.max_page_count)))
        legacy_pdf_text = int(os.getenv("PAPERLENS_MAX_PAPER_TEXT_CHARS", str(defaults.max_paper_text_chars)))
        result = cls(
            app_name=os.getenv("PAPERLENS_APP_NAME", defaults.app_name),
            environment=environment,
            database_url=_first_env("PAPERLENS_DATABASE_URL", "DATABASE_URL", default=defaults.database_url),
            frontend_origin=_first_env("PAPERLENS_FRONTEND_ORIGIN", "FRONTEND_ORIGIN", default=defaults.frontend_origin),
            frontend_origins=os.getenv("PAPERLENS_FRONTEND_ORIGINS") or None,
            backend_public_url=os.getenv("PAPERLENS_BACKEND_PUBLIC_URL", os.getenv("BACKEND_PUBLIC_URL", defaults.backend_public_url)),
            arxiv_request_timeout=float(
                os.getenv("PAPERLENS_ARXIV_REQUEST_TIMEOUT", str(defaults.arxiv_request_timeout))
            ),
            paper_storage_path=_first_env("PAPERLENS_STORAGE_PATH", "PAPER_STORAGE_PATH", default=defaults.paper_storage_path),
            max_pdf_size=legacy_pdf_bytes,
            pdf_max_bytes=int(os.getenv("PDF_MAX_BYTES", os.getenv("PAPERLENS_PDF_MAX_BYTES", str(legacy_pdf_bytes)))),
            pdf_max_pages=int(os.getenv("PDF_MAX_PAGES", os.getenv("PAPERLENS_PDF_MAX_PAGES", str(legacy_pdf_pages)))),
            pdf_max_text_chars=int(os.getenv("PDF_MAX_TEXT_CHARS", os.getenv("PAPERLENS_PDF_MAX_TEXT_CHARS", str(legacy_pdf_text)))),
            pdf_max_text_chars_per_page=_optional_int_env("PDF_MAX_TEXT_CHARS_PER_PAGE", "PAPERLENS_PDF_MAX_TEXT_CHARS_PER_PAGE"),
            pdf_max_images_per_page=max(0, int(os.getenv("PDF_MAX_IMAGES_PER_PAGE", os.getenv("PAPERLENS_PDF_MAX_IMAGES_PER_PAGE", str(defaults.pdf_max_images_per_page))))),
            pdf_max_total_images=max(0, int(os.getenv("PDF_MAX_TOTAL_IMAGES", os.getenv("PAPERLENS_PDF_MAX_TOTAL_IMAGES", str(defaults.pdf_max_total_images))))),
            pdf_parse_timeout_seconds=max(0.1, float(os.getenv("PDF_PARSE_TIMEOUT_SECONDS", os.getenv("PAPERLENS_PDF_PARSE_TIMEOUT_SECONDS", str(defaults.pdf_parse_timeout_seconds))))),
            pdf_parse_concurrency=max(1, min(int(os.getenv("PDF_PARSE_CONCURRENCY", os.getenv("PAPERLENS_PDF_PARSE_CONCURRENCY", str(defaults.pdf_parse_concurrency)))), 8)),
            pdf_parser_memory_limit_bytes=_optional_int_env("PDF_PARSER_MEMORY_LIMIT_BYTES", "PAPERLENS_PDF_PARSER_MEMORY_LIMIT_BYTES"),
            pdf_parser_cpu_limit_seconds=_optional_float_env("PDF_PARSER_CPU_LIMIT_SECONDS", "PAPERLENS_PDF_PARSER_CPU_LIMIT_SECONDS"),
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
            research_worker_enabled=_as_bool(research_worker_enabled_raw) if research_worker_enabled_raw is not None else defaults.research_worker_enabled,
            research_worker_concurrency=max(1, min(int(os.getenv("RESEARCH_WORKER_CONCURRENCY", str(defaults.research_worker_concurrency))), 8)),
            research_worker_poll_seconds=max(0.25, min(float(os.getenv("RESEARCH_WORKER_POLL_SECONDS", str(defaults.research_worker_poll_seconds))), 60.0)),
            research_claim_lease_seconds=max(5, min(int(os.getenv("RESEARCH_CLAIM_LEASE_SECONDS", str(defaults.research_claim_lease_seconds))), 3600)),
            research_max_attempts=max(1, min(int(os.getenv("RESEARCH_MAX_ATTEMPTS", str(defaults.research_max_attempts))), 5)),
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
            auth_required=_as_bool(auth_required_raw) if auth_required_raw is not None else environment.strip().lower() in {"staging", "production"},
            auth_cookie_name=os.getenv("PAPERLENS_AUTH_COOKIE_NAME", defaults.auth_cookie_name),
            auth_session_ttl_seconds=max(300, int(os.getenv("PAPERLENS_AUTH_SESSION_TTL_SECONDS", str(defaults.auth_session_ttl_seconds)))),
        )
        return result

    @property
    def allowed_origins(self) -> list[str]:
        """Return an explicit, de-duplicated CORS allow-list."""

        values = self.frontend_origins or self.frontend_origin
        return list(dict.fromkeys(item.strip() for item in values.split(",") if item.strip()))

    @property
    def requires_authentication(self) -> bool:
        """Whether shared-mode requests must present a durable user session."""

        return bool(self.auth_required or self.environment.strip().lower() in {"staging", "production"})

    @property
    def effective_pdf_max_bytes(self) -> int:
        return int(self.pdf_max_bytes if self.pdf_max_bytes is not None else self.max_pdf_size)

    @property
    def effective_pdf_max_pages(self) -> int:
        return int(self.pdf_max_pages if self.pdf_max_pages is not None else self.max_page_count)

    @property
    def effective_pdf_max_text_chars(self) -> int:
        return int(self.pdf_max_text_chars if self.pdf_max_text_chars is not None else self.max_paper_text_chars)

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
            "pdf_max_bytes": self.effective_pdf_max_bytes,
            "pdf_max_pages": self.effective_pdf_max_pages,
            "pdf_max_text_chars": self.effective_pdf_max_text_chars,
            "max_request_body_size": self.max_request_body_size,
            "max_paper_text_chars": self.max_paper_text_chars,
            "max_page_count": self.max_page_count,
            "max_concurrent_ingestions": self.max_concurrent_ingestions,
        }
        if any(value <= 0 for value in numeric.values()):
            raise ConfigurationError("Resource limits must be positive.")
        if self.pdf_max_text_chars_per_page is not None and self.pdf_max_text_chars_per_page <= 0:
            raise ConfigurationError("PDF_MAX_TEXT_CHARS_PER_PAGE must be positive when configured.")
        if self.pdf_max_images_per_page < 0 or self.pdf_max_total_images < 0:
            raise ConfigurationError("PDF image budgets cannot be negative.")
        if self.pdf_parse_timeout_seconds <= 0 or self.pdf_parse_concurrency < 1 or self.pdf_parse_concurrency > 8:
            raise ConfigurationError("PDF parser timeout and concurrency must be positive and bounded.")
        if self.pdf_parser_memory_limit_bytes is not None and self.pdf_parser_memory_limit_bytes <= 0:
            raise ConfigurationError("PDF_PARSER_MEMORY_LIMIT_BYTES must be positive when configured.")
        if self.pdf_parser_cpu_limit_seconds is not None and self.pdf_parser_cpu_limit_seconds <= 0:
            raise ConfigurationError("PDF_PARSER_CPU_LIMIT_SECONDS must be positive when configured.")
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
        if self.research_worker_concurrency < 1 or self.research_worker_concurrency > 8:
            raise ConfigurationError("RESEARCH_WORKER_CONCURRENCY must be between 1 and 8.")
        if self.research_worker_poll_seconds <= 0 or self.research_claim_lease_seconds < 5:
            raise ConfigurationError("Research worker polling and lease values must be positive and bounded.")
        if self.research_max_attempts < 1 or self.research_max_attempts > 5:
            raise ConfigurationError("RESEARCH_MAX_ATTEMPTS must be between 1 and 5.")
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
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{2,63}", self.auth_cookie_name):
            raise ConfigurationError("PAPERLENS_AUTH_COOKIE_NAME must be a safe cookie name.")
        if self.auth_session_ttl_seconds < 300 or self.auth_session_ttl_seconds > 60 * 60 * 24 * 30:
            raise ConfigurationError("PAPERLENS_AUTH_SESSION_TTL_SECONDS must be between 300 and 2592000.")
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


def _optional_int_env(*names: str) -> int | None:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return int(value)
    return None


def _optional_float_env(*names: str) -> float | None:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return float(value)
    return None
