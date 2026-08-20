"""FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .ai.provider import AIProvider, create_ai_provider
from .api.routes import router
from .core.config import Settings
from .db.database import SQLDatabase
from .extraction.service import ResearchExtractionService
from .ingestion.service import IngestionService


def create_app(
    settings: Settings | None = None,
    *,
    database: SQLDatabase | None = None,
    ingestion_service: IngestionService | None = None,
    ai_provider: AIProvider | None = None,
    extraction_service: ResearchExtractionService | None = None,
) -> FastAPI:
    """Create an application instance suitable for production or tests."""

    resolved_settings = settings or Settings.from_env()
    app = FastAPI(title=resolved_settings.app_name, version="0.1.0")
    app.state.settings = resolved_settings
    app.state.database = database or SQLDatabase(resolved_settings.database_url)
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved_settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
