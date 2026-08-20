"""Production-hardening regression tests that stay entirely offline."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone

import httpx
from fastapi.testclient import TestClient

from backend.app.core.config import ConfigurationError, Settings
from backend.app.db.database import SQLDatabase
from backend.app.main import create_app
from backend.app.models.research import ResearchRun, ResearchRunStatus
from backend.app.ingestion.arxiv.client import ArxivClient
from backend.app.ingestion.errors import PdfDownloadError
from backend.app.models.paper import PaperMetadata


class ProductionHardeningTests(unittest.TestCase):
    def test_security_headers_request_id_health_and_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(database_url="sqlite:///:memory:", paper_storage_path=directory)
            client = TestClient(create_app(settings=settings, database=SQLDatabase("sqlite:///:memory:")))
            response = client.get("/health/live", headers={"X-Request-ID": "fixture-request"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["X-Request-ID"], "fixture-request")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(response.headers["X-Frame-Options"], "DENY")
            self.assertIn("paperlens_requests_total", client.get("/metrics").text)
            self.assertEqual(client.get("/health/ready").status_code, 200)

    def test_json_body_limit_returns_typed_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(database_url="sqlite:///:memory:", paper_storage_path=directory, max_request_body_size=128)
            client = TestClient(create_app(settings=settings, database=SQLDatabase("sqlite:///:memory:")))
            response = client.post("/api/papers/ingest", json={"source": "x" * 512})
            self.assertEqual(response.status_code, 413)
            self.assertEqual(response.json()["error"]["code"], "REQUEST_TOO_LARGE")
            self.assertIn("request_id", response.json()["error"])

    def test_restart_recovery_marks_incomplete_work_without_rerunning(self) -> None:
        db = SQLDatabase("sqlite:///:memory:")
        db.create_placeholder(paper_id="paper_pending", source_identity="arxiv:1706.03762", arxiv_id="1706.03762")
        run = ResearchRun(
            id="research_pending",
            research_question="fixture",
            status=ResearchRunStatus.DISCOVERING,
            max_iterations=1,
            max_candidates=1,
            max_ingested_papers=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.create_research_run(run)
        recovered = db.recover_incomplete_work()
        self.assertEqual(recovered, {"papers": 1, "research_runs": 1})
        self.assertEqual(db.get_research_run(run.id).status, ResearchRunStatus.INTERRUPTED)
        self.assertIsNone(db.get_by_id("paper_pending"))

    def test_production_configuration_requires_explicit_migrations(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings(environment="production").validate()

    def test_idempotency_response_is_durable_and_scoped(self) -> None:
        db = SQLDatabase("sqlite:///:memory:")
        db.save_idempotent_response("ingest:fixture", "retry-1", {"id": "paper_fixture"})
        self.assertEqual(db.get_idempotent_response("ingest:fixture", "retry-1"), {"id": "paper_fixture"})
        self.assertIsNone(db.get_idempotent_response("chat:fixture", "retry-1"))

    def test_pdf_redirect_to_untrusted_host_is_rejected(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "arxiv.org":
                return httpx.Response(302, headers={"location": "https://evil.example/paper.pdf"}, request=request)
            return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.7", request=request)

        metadata = PaperMetadata(
            arxiv_id="1706.03762",
            title="fixture",
            source_url="https://arxiv.org/abs/1706.03762",
            pdf_url="https://arxiv.org/pdf/1706.03762.pdf",
        )
        client = ArxivClient(transport=httpx.MockTransport(handler))
        with self.assertRaises(PdfDownloadError):
            import asyncio

            asyncio.run(client.download_pdf(metadata, max_bytes=1024))


if __name__ == "__main__":
    unittest.main()
