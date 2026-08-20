from __future__ import annotations
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.db.database import PaperRecord
from backend.app.extraction.service import ResearchExtractionService
from backend.app.main import create_app
from backend.app.models.reader import VisualizationType
from backend.app.visualization.planner import plan_visualizations
from backend.tests.test_extraction import FakeProvider, _document_fixture


class ReaderApiTests(unittest.TestCase):
    def test_reader_payload_is_small_and_source_is_served_safely(self) -> None:
        database, paper_id = _document_fixture()
        with tempfile.TemporaryDirectory(prefix="paperlens-reader-") as temp_dir:
            root = Path(temp_dir)
            storage = root / "papers"
            pdf_path = storage / paper_id / "source.pdf"
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(b"%PDF-1.4\nPaperLens test PDF\n")
            with database.session_factory.begin() as session:
                record = session.get(PaperRecord, paper_id)
                record.local_pdf_path = str(pdf_path)

            settings = Settings(
                database_url="sqlite:///:memory:",
                paper_storage_path=str(storage),
                ai_provider="mock",
                ai_model="fixture-model",
            )
            service = ResearchExtractionService(
                database,
                FakeProvider(),
                settings=settings,
            )
            client = TestClient(create_app(database=database, extraction_service=service, settings=settings))
            self.assertEqual(client.post(f"/api/papers/{paper_id}/extract").status_code, 200)

            reader = client.get(f"/api/papers/{paper_id}/reader")
            self.assertEqual(reader.status_code, 200)
            payload = reader.json()
            self.assertEqual(payload["document"]["paragraph_count"], 7)
            self.assertNotIn("source_text", reader.text)
            self.assertTrue(payload["source"]["available"])
            self.assertTrue(any(item["type"] == "METHOD_FLOW" for item in payload["visualizations"]))

            source = client.get(f"/api/papers/{paper_id}/source")
            self.assertEqual(source.status_code, 200)
            self.assertEqual(source.headers["content-type"], "application/pdf")
            self.assertIn(b"%PDF-1.4", source.content)

            with database.session_factory.begin() as session:
                record = session.get(PaperRecord, paper_id)
                record.local_pdf_path = str(root / "outside.pdf")
            self.assertEqual(client.get(f"/api/papers/{paper_id}/source").status_code, 404)

    def test_reader_without_analysis_returns_explicit_empty_state(self) -> None:
        database, paper_id = _document_fixture()
        settings = Settings(database_url="sqlite:///:memory:", paper_storage_path="/tmp/paperlens-reader")
        client = TestClient(create_app(database=database, settings=settings))
        response = client.get(f"/api/papers/{paper_id}/reader")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["analysis"])
        self.assertEqual(response.json()["visualizations"], [])


class VisualizationPlannerTests(unittest.IsolatedAsyncioTestCase):
    async def test_numeric_and_textual_results_plan_deterministically(self) -> None:
        database, paper_id = _document_fixture()
        service = ResearchExtractionService(
            database,
            FakeProvider(),
            settings=Settings(ai_provider="mock", ai_model="fixture-model"),
        )
        analysis = await service.extract(paper_id)
        specs = plan_visualizations(analysis)
        self.assertTrue(any(spec.type is VisualizationType.METHOD_FLOW for spec in specs))
        self.assertTrue(any(spec.type is VisualizationType.TABLE for spec in specs))
