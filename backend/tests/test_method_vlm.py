from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend.app.core.config import Settings
from backend.app.extraction.classifier import SectionClassification, SectionType
from backend.app.extraction.extractors import MethodPayload
from backend.app.extraction.service import ResearchExtractionService
from backend.app.extraction.vlm import extract_method_from_pdf
from backend.tests.test_extraction import FakeProvider, _document_fixture


class MethodVLMTests(unittest.IsolatedAsyncioTestCase):
    async def test_page_workflow_is_grounded_and_ordered(self) -> None:
        database, paper_id = _document_fixture()
        document = database.get_document(paper_id)
        assert document is not None
        method = next(section for section in document.sections if section.title == "Method")
        classifications = [SectionClassification(section_id=method.id, classification=SectionType.METHOD)]
        response = {
            "summary": "Encode then decode.", "evidence_ids": ["ev_0003"],
            "steps": [
                {"label": "Encode", "description": "Encode inputs.", "evidence_ids": ["ev_0003"]},
                {"label": "Decode", "description": "Decode outputs.", "evidence_ids": ["ev_0003"]},
            ],
            "relations": [{"source_step_index": 0, "target_step_index": 1, "relationship": "feeds"}],
        }
        with patch("backend.app.extraction.vlm._infer", return_value=json.dumps(response)):
            result = await extract_method_from_pdf(document, classifications, Path("unused.pdf"), model="qwen", python=None)
        assert result is not None
        self.assertEqual([step.order for step in result.steps], [0, 1])
        self.assertEqual(result.origin.value, "MODEL_INFERRED")

        response["steps"][1]["evidence_ids"] = ["ev_missing"]
        with patch("backend.app.extraction.vlm._infer", return_value=json.dumps(response)):
            with self.assertRaises(ValueError):
                await extract_method_from_pdf(document, classifications, Path("unused.pdf"), model="qwen", python=None)

    async def test_service_uses_vlm_graph_and_cache_identity(self) -> None:
        database, paper_id = _document_fixture()
        payload = MethodPayload.model_validate({
            "summary": "Encode then decode.", "evidence_ids": ["ev_0003"], "origin": "MODEL_INFERRED",
            "steps": [
                {"label": "Encode", "description": "Encode inputs.", "order": 0, "evidence_ids": ["ev_0003"], "origin": "MODEL_INFERRED"},
                {"label": "Decode", "description": "Decode outputs.", "order": 1, "evidence_ids": ["ev_0003"], "origin": "MODEL_INFERRED"},
            ],
            "relations": [{"source_step_index": 0, "target_step_index": 1, "relationship": "feeds"}],
        })
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "paper.pdf"
            source.touch()
            settings = Settings(ai_provider="mock", ai_model="fixture-model", paper_storage_path=directory, vlm_enabled=True)
            service = ResearchExtractionService(database, FakeProvider(), settings=settings)
            with patch.object(database, "get_source_pdf_path", return_value=source), patch(
                "backend.app.extraction.service.extract_method_from_pdf", new_callable=AsyncMock, return_value=payload
            ) as visual:
                analysis = await service.extract(paper_id)
            self.assertEqual(visual.await_count, 1)
            self.assertEqual([step.label for step in analysis.method.steps], ["Encode", "Decode"])
            self.assertEqual(analysis.extraction["method"].model, settings.vlm_model)


if __name__ == "__main__":
    unittest.main()
