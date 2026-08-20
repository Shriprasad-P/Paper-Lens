"""Deployment and public-beta safety regression tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import ConfigurationError, Settings
from backend.app.db.database import SQLDatabase
from backend.app.ingestion.storage import LocalStorage
from backend.app.main import create_app


class Phase12Tests(unittest.TestCase):
    def test_capabilities_disable_ai_in_staging_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(environment="staging", database_url="sqlite:///:memory:", paper_storage_path=directory)
            client = TestClient(create_app(settings=settings, database=SQLDatabase("sqlite:///:memory:")))
            capabilities = client.get("/api/capabilities")
            self.assertEqual(capabilities.status_code, 200)
            self.assertFalse(capabilities.json()["ai_analysis_enabled"])
            self.assertEqual(client.post("/api/papers/missing/extract").status_code, 503)

    def test_beta_rate_limit_is_server_side_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                database_url="sqlite:///:memory:",
                paper_storage_path=directory,
                rate_limits_enabled=True,
                rate_limit_research_per_minute=1,
            )
            client = TestClient(create_app(settings=settings, database=SQLDatabase("sqlite:///:memory:")))
            first = client.post("/api/research/runs", json={"question": "bounded test", "depth": "QUICK"})
            second = client.post("/api/research/runs", json={"question": "bounded test", "depth": "QUICK"})
            self.assertEqual(first.status_code, 201)
            self.assertEqual(second.status_code, 429)
            self.assertEqual(second.json()["error"]["code"], "RATE_LIMITED")
            self.assertIn("Retry-After", second.headers)

    def test_local_storage_uses_deterministic_private_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalStorage(directory)
            path = storage.save_pdf("paper/../../escape", b"pdf")
            self.assertTrue(path.is_file())
            self.assertEqual(path.name, "source.pdf")
            self.assertTrue(path.is_relative_to(Path(directory).resolve()))
            self.assertTrue(storage.exists(path))
            storage.delete(path)
            self.assertFalse(storage.exists(path))

    def test_production_requires_postgres_and_existing_storage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(environment="production", database_url="sqlite:///./paperlens.db", paper_storage_path=directory, auto_create_schema=False)
            with self.assertRaises(ConfigurationError):
                settings.validate()


if __name__ == "__main__":
    unittest.main()
