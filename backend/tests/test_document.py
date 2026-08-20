from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from backend.app.db.database import SQLDatabase
from backend.app.document.normalizer import DocumentNormalizer
from backend.app.evidence.registry import EvidenceRegistry
from backend.app.ingestion.raw import ParsedPaper, RawParagraph, RawSection
from backend.app.main import create_app
from backend.app.models.document import EvidenceType, SourceRegion
from backend.app.models.paper import PaperMetadata


def metadata() -> PaperMetadata:
    return PaperMetadata(
        arxiv_id="1234.56789",
        title="A Source-Preserving Paper",
        authors=["Researcher"],
        abstract="Abstract",
        categories=["cs.AI"],
        source_url="https://arxiv.org/abs/1234.56789",
        pdf_url="https://arxiv.org/pdf/1234.56789.pdf",
    )


def parsed_paper() -> ParsedPaper:
    return ParsedPaper(
        parser_name="fixture-parser",
        parser_version="1",
        page_count=3,
        sections=[
            RawSection(
                title="Introduction",
                level=1,
                order=0,
                page_start=1,
                page_end=1,
                paragraphs=[
                    RawParagraph(
                        text="Unicode π is preserved exactly.",
                        page=1,
                        source_region=SourceRegion(page=1, x0=1, y0=2, x1=3, y1=4),
                    ),
                    RawParagraph(text="A paragraph without page provenance.", page=None),
                ],
            ),
            RawSection(
                title="1.1 Details",
                level=2,
                order=1,
                paragraphs=[RawParagraph(text="A nested paragraph.", page=2)],
            ),
            RawSection(title="Duplicate Heading", level=1, order=2, paragraphs=[]),
            RawSection(title="Duplicate Heading", level=1, order=3, paragraphs=[RawParagraph(text="Last.")]),
        ],
    )


class DocumentNormalizerTests(unittest.TestCase):
    def test_normalization_preserves_structure_pages_and_stable_ids(self) -> None:
        normalizer = DocumentNormalizer()
        first = normalizer.normalize(parsed_paper(), paper_id="paper_test", metadata=metadata(), source_hash="pdf-hash")
        second = normalizer.normalize(parsed_paper(), paper_id="paper_test", metadata=metadata(), source_hash="pdf-hash")

        self.assertEqual(first.id, second.id)
        self.assertEqual([section.id for section in first.sections], ["sec_001", "sec_002", "sec_003", "sec_004"])
        self.assertEqual(first.sections[1].parent_id, "sec_001")
        self.assertEqual(first.sections[0].paragraphs[0].id, "para_0001")
        self.assertEqual(first.sections[0].paragraphs[1].page, None)
        self.assertEqual(first.sections[0].paragraphs[0].text, "Unicode π is preserved exactly.")
        self.assertEqual(first.sections[0].paragraphs[0].id, second.sections[0].paragraphs[0].id)
        self.assertEqual(first.sections[0].paragraphs[0].content_hash, second.sections[0].paragraphs[0].content_hash)
        self.assertEqual(first.sections[0].paragraphs[0].source_region.page, 1)


class EvidenceRegistryTests(unittest.TestCase):
    def test_each_paragraph_gets_matching_evidence(self) -> None:
        document = DocumentNormalizer().normalize(
            parsed_paper(), paper_id="paper_test", metadata=metadata(), source_hash="pdf-hash"
        )
        registry = EvidenceRegistry()
        records = registry.build_for_document(document)

        paragraphs = [paragraph for section in document.sections for paragraph in section.paragraphs]
        self.assertEqual(len(records), len(paragraphs))
        self.assertEqual(records[0].evidence_type, EvidenceType.PARAGRAPH)
        self.assertEqual(records[0].source_text, paragraphs[0].text)
        self.assertEqual(records[0].section_id, paragraphs[0].section_id)
        self.assertEqual(records[0].page, paragraphs[0].page)
        self.assertIs(registry.get(records[0].id), records[0])
        self.assertEqual(registry.get_many([records[0].id, "missing"]), [records[0]])


class DocumentPersistenceTests(unittest.TestCase):
    def test_document_and_evidence_reload_and_replace_transactionally(self) -> None:
        db = SQLDatabase("sqlite:///:memory:")
        db.create_placeholder(paper_id="paper_test", source_identity="arxiv:1234.56789", arxiv_id="1234.56789")
        db.save_metadata("paper_test", metadata(), status="COMPLETED")
        normalizer = DocumentNormalizer()
        registry = EvidenceRegistry()
        document = normalizer.normalize(parsed_paper(), paper_id="paper_test", metadata=metadata(), source_hash="pdf-hash")
        evidence = registry.build_for_document(document)
        db.replace_document(document, evidence)
        db.replace_document(document, evidence)

        loaded = db.get_document("paper_test")
        loaded_evidence = db.get_evidence("paper_test", "ev_0001")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.id, document.id)
        self.assertEqual(len(loaded.sections), 4)
        self.assertEqual(loaded.sections[0].paragraphs[0].evidence_id, "ev_0001")
        self.assertEqual(loaded_evidence.source_text, loaded.sections[0].paragraphs[0].text)
        self.assertEqual(loaded_evidence.source_region.page, 1)

        client = TestClient(create_app(database=db))
        document_response = client.get("/api/papers/paper_test/document")
        evidence_response = client.get("/api/papers/paper_test/evidence/ev_0001")
        self.assertEqual(document_response.status_code, 200)
        self.assertEqual(evidence_response.status_code, 200)
        self.assertEqual(evidence_response.json()["paragraph_id"], "para_0001")

    def test_document_and_evidence_api_handles_missing_records(self) -> None:
        db = SQLDatabase("sqlite:///:memory:")
        client = TestClient(create_app(database=db))
        self.assertEqual(client.get("/api/papers/unknown/document").status_code, 404)
        self.assertEqual(client.get("/api/papers/unknown/evidence/ev_0001").status_code, 404)


if __name__ == "__main__":
    unittest.main()
