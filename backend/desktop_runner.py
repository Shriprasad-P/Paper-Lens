"""Standalone local desktop sidecar entry point."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def _run_migrations(root: Path) -> None:
    from alembic import command
    from alembic.config import Config

    ini_path = root / "alembic.ini"
    if not ini_path.exists():
        raise RuntimeError(f"Alembic configuration is missing from the desktop sidecar: {ini_path}")
    config = Config(str(ini_path))
    config.set_main_option("script_location", str(root / "migrations"))
    database_url = os.environ.get("PAPERLENS_DATABASE_URL")
    if not database_url:
        raise RuntimeError("PAPERLENS_DATABASE_URL is required for the desktop sidecar.")
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def main() -> None:
    root = _bundle_root()
    os.chdir(root)
    _run_migrations(root)

    # Keep this import after migrations: app construction performs recovery
    # checks that require the schema to exist. A direct import also lets
    # PyInstaller statically collect the complete FastAPI application graph.
    from backend.app.main import app
    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("PAPERLENS_BACKEND_PORT", "8000")),
        workers=1,
        log_level=os.environ.get("PAPERLENS_LOG_LEVEL", "info").lower(),
        access_log=True,
    )


if __name__ == "__main__":
    main()
