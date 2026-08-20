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
        )
