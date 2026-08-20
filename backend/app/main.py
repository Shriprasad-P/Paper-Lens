"""FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .ai.provider import AIProvider, create_ai_provider
from .api.routes import router
from .core.config import ConfigurationError, Settings
from .core.hardening import DesktopTokenMiddleware, Metrics, RateLimitMiddleware, RequestBodyLimitMiddleware, RequestContextMiddleware, SecurityHeadersMiddleware, error_body
from .db.database import SQLDatabase
from .extraction.service import ResearchExtractionService
from .ingestion.service import IngestionService
from .verification.service import PaperVerificationService
from .chat.service import PaperChatService
from .research.agent import ResearchAgent
from .research.discovery import ArxivDiscoveryProvider
from .research.planner import ResearchPlanner


def create_app(
    settings: Settings | None = None,
    *,
    database: SQLDatabase | None = None,
    ingestion_service: IngestionService | None = None,
    ai_provider: AIProvider | None = None,
    extraction_service: ResearchExtractionService | None = None,
    verification_service: PaperVerificationService | None = None,
    chat_service: PaperChatService | None = None,
    research_agent: ResearchAgent | None = None,
) -> FastAPI:
    """Create an application instance suitable for production or tests."""

    resolved_settings = settings or Settings.from_env()
    resolved_settings.validate()
    app = FastAPI(title=resolved_settings.app_name, version=resolved_settings.release_version)
    app.state.settings = resolved_settings
    app.state.database = database or SQLDatabase(
        resolved_settings.database_url,
        create_schema=resolved_settings.auto_create_schema,
        pool_size=resolved_settings.db_pool_size,
        max_overflow=resolved_settings.db_max_overflow,
        pool_timeout=resolved_settings.db_pool_timeout,
    )
    app.state.metrics = Metrics()
    app.state.database.recover_incomplete_work()
    app.state.ingestion_service = ingestion_service or IngestionService(
        app.state.database,
        settings=resolved_settings,
    )
    resolved_provider = ai_provider or create_ai_provider(resolved_settings)
    app.state.extraction_service = extraction_service or ResearchExtractionService(
        app.state.database,
        resolved_provider,
        settings=resolved_settings,
    )
    app.state.verification_service = verification_service or PaperVerificationService(
        app.state.database,
        resolved_provider,
        settings=resolved_settings,
    )
    app.state.chat_service = chat_service or PaperChatService(
        app.state.database,
        resolved_provider,
        settings=resolved_settings,
    )
    app.state.research_agent = research_agent or ResearchAgent(
        app.state.database,
        ResearchPlanner(resolved_provider, settings=resolved_settings),
        ArxivDiscoveryProvider(timeout=resolved_settings.arxiv_request_timeout),
        app.state.ingestion_service,
        app.state.extraction_service,
        settings=resolved_settings,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "Authorization", "Idempotency-Key", "X-Request-ID", "X-PaperLens-Desktop-Token"],
    )
    if resolved_settings.desktop_token:
        app.add_middleware(DesktopTokenMiddleware, token=resolved_settings.desktop_token)
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=resolved_settings.max_request_body_size)
    if resolved_settings.rate_limits_enabled:
        app.add_middleware(
            RateLimitMiddleware,
            limits={
                "ingestion": resolved_settings.rate_limit_ingestion_per_minute,
                "ai": resolved_settings.rate_limit_ai_per_minute,
                "chat": resolved_settings.rate_limit_chat_per_minute,
                "research": resolved_settings.rate_limit_research_per_minute,
            },
        )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)

    @app.exception_handler(ConfigurationError)
    async def configuration_error_handler(request: Request, exc: ConfigurationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        return JSONResponse(status_code=500, content=error_body("CONFIGURATION_ERROR", "Service configuration is invalid.", request_id))

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        return JSONResponse(status_code=422, content=error_body("INVALID_REQUEST", "The request could not be validated.", request_id))

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        message = str(exc.detail) if isinstance(exc.detail, str) else "The request could not be completed."
        code = _error_code(exc.status_code)
        return JSONResponse(status_code=exc.status_code, headers=exc.headers, content=error_body(code, message, request_id))

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        # Keep implementation details and provider/database exceptions out of API responses.
        return JSONResponse(status_code=500, content=error_body("INTERNAL_ERROR", "The request could not be completed.", request_id))

    app.include_router(router)
    return app


def _error_code(status_code: int) -> str:
    return {
        400: "INVALID_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        413: "REQUEST_TOO_LARGE",
        422: "INVALID_REQUEST",
        429: "RATE_LIMITED",
        502: "PROVIDER_UNAVAILABLE",
        503: "SERVICE_UNAVAILABLE",
    }.get(status_code, "REQUEST_FAILED")


app = create_app()
