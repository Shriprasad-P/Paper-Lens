from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pymupdf
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.db.database import SQLDatabase
from backend.app.ingestion.arxiv.client import ArxivClient
from backend.app.ingestion.arxiv.parser import normalize_arxiv_input
from backend.app.ingestion.errors import (
    ArxivMetadataError,
    ArxivNotFoundError,
    InvalidArxivIdentifierError,
    PdfValidationError,
)
from backend.app.ingestion.parser import PyMuPDFPaperParser
from backend.app.ingestion.service import IngestionService
from backend.app.ingestion.storage import PaperStorage
from backend.app.main import create_app
from backend.app.models.paper import PaperMetadata, ParsedSection


ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v5</id>
    <title>Attention Is All You Need</title>
    <summary>  A concise abstract.\nWith a second line. </summary>
    <published>2017-06-12T17:57:34Z</published>
    <updated>2026-01-01T00:00:00Z</updated>
    <author><name>Alice Researcher</name></author>
    <author><name>Bob Researcher</name></author>
    <category term="cs.CL" />
    <category term="cs.LG" />
  </entry>
</feed>"""


def response_handler(content: bytes | str, *, status_code: int = 200, headers: dict[str, str] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=content, headers=headers, request=request)

    return handler


class ArxivNormalizationTests(unittest.TestCase):
    def test_supported_inputs_normalize(self) -> None:
        cases = {
            "https://arxiv.org/abs/1706.03762": "1706.03762",
            "https://arxiv.org/pdf/1706.03762": "1706.03762",
            "1706.03762": "1706.03762",
            "1706.03762v5": "1706.03762v5",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(normalize_arxiv_input(source).canonical_id, expected)

    def test_invalid_and_untrusted_inputs_are_rejected(self) -> None:
        for source in (
            "",
            "https://example.com/abs/1706.03762",
            "https://arxiv.org/abs/1706.03762?redirect=https://example.com",
            "not-an-arxiv-id",
        ):
            with self.subTest(source=source), self.assertRaises(InvalidArxivIdentifierError):
                normalize_arxiv_input(source)


class ArxivClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_metadata_success(self) -> None:
        client = ArxivClient(transport=httpx.MockTransport(response_handler(ATOM)))
        metadata = await client.fetch_metadata(normalize_arxiv_input("1706.03762"))
        self.assertEqual(metadata.title, "Attention Is All You Need")
        self.assertEqual(metadata.authors, ["Alice Researcher", "Bob Researcher"])
        self.assertEqual(metadata.categories, ["cs.CL", "cs.LG"])
        self.assertEqual(metadata.published_at, datetime(2017, 6, 12, 17, 57, 34, tzinfo=timezone.utc))

    async def test_not_found_and_malformed_metadata(self) -> None:
        empty = b'<feed xmlns="http://www.w3.org/2005/Atom" />'
        with self.assertRaises(ArxivNotFoundError):
            await ArxivClient(transport=httpx.MockTransport(response_handler(empty))).fetch_metadata(
                normalize_arxiv_input("1706.03762")
            )

        malformed = httpx.MockTransport(response_handler(b"not xml"))
        with self.assertRaises(ArxivMetadataError):
            await ArxivClient(transport=malformed).fetch_metadata(normalize_arxiv_input("1706.03762"))

    async def test_network_failure_and_pdf_validation(self) -> None:
        def fail(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("offline", request=request)

        with self.assertRaises(ArxivMetadataError):
            await ArxivClient(transport=httpx.MockTransport(fail)).fetch_metadata(
                normalize_arxiv_input("1706.03762")
            )

        metadata = PaperMetadata(
            arxiv_id="1706.03762",
            title="Paper",
            source_url="https://arxiv.org/abs/1706.03762",
            pdf_url="https://arxiv.org/pdf/1706.03762.pdf",
        )
        client = ArxivClient(
            transport=httpx.MockTransport(response_handler(b"<html>not pdf</html>", headers={"content-type": "text/html"}))
        )
        with self.assertRaises(PdfValidationError):
            await client.download_pdf(metadata, max_bytes=1000)


class ParserTests(unittest.IsolatedAsyncioTestCase):
    async def test_pymupdf_parser_extracts_heading_sections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "fixture.pdf"
            document = pymupdf.open()
            page = document.new_page()
            page.insert_text((72, 72), "ABSTRACT\nThis is the abstract.\n1 Introduction\nThis is the introduction.")
            document.save(pdf_path)
            document.close()

            sections = await PyMuPDFPaperParser().parse(pdf_path)

        self.assertEqual([section.title for section in sections], ["ABSTRACT", "1 Introduction"])
        self.assertIn("This is the introduction.", sections[1].text)


class PersistenceAndServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_ingestion_persists_and_is_idempotent(self) -> None:
        class FakeClient:
            metadata_calls = 0
            pdf_calls = 0

            async def fetch_metadata(self, identifier):
                self.metadata_calls += 1
                return PaperMetadata(
                    arxiv_id=identifier.canonical_id,
                    title="Test Paper",
                    authors=["Author"],
                    abstract="Abstract",
                    source_url=f"https://arxiv.org/abs/{identifier.canonical_id}",
                    pdf_url=f"https://arxiv.org/pdf/{identifier.canonical_id}.pdf",
                )

            async def download_pdf(self, metadata, *, max_bytes):
                self.pdf_calls += 1
                return b"%PDF-1.7 test"

        class FakeParser:
            async def parse(self, file_path):
                self.file_path = file_path
                return [ParsedSection(title="Introduction", order=0, text="Text")]

        with tempfile.TemporaryDirectory() as directory:
            db = SQLDatabase("sqlite:///:memory:")
            client = FakeClient()
            service = IngestionService(
                db,
                settings=Settings(database_url="sqlite:///:memory:", paper_storage_path=directory),
                arxiv_client=client,
                parser=FakeParser(),
                storage=PaperStorage(directory),
            )
            first = await service.ingest("1706.03762")
            second = await service.ingest("https://arxiv.org/abs/1706.03762")

        self.assertEqual(first.id, second.id)
        self.assertEqual(first.status, "COMPLETED")
        self.assertEqual(first.sections[0].title, "Introduction")
        self.assertEqual(client.metadata_calls, 1)
        self.assertEqual(client.pdf_calls, 1)

    async def test_api_maps_invalid_input_and_returns_persisted_paper(self) -> None:
        class FakeClient:
            async def fetch_metadata(self, identifier):
                return PaperMetadata(
                    arxiv_id=identifier.canonical_id,
                    title="API Paper",
                    authors=["Author"],
                    source_url=f"https://arxiv.org/abs/{identifier.canonical_id}",
                    pdf_url=f"https://arxiv.org/pdf/{identifier.canonical_id}.pdf",
                )

            async def download_pdf(self, metadata, *, max_bytes):
                return b"%PDF-1.7 test"

        class FakeParser:
            async def parse(self, file_path):
                return [ParsedSection(title="Abstract", order=0, text="Text")]

        with tempfile.TemporaryDirectory() as directory:
            db = SQLDatabase("sqlite:///:memory:")
            service = IngestionService(
                db,
                settings=Settings(paper_storage_path=directory),
                arxiv_client=FakeClient(),
                parser=FakeParser(),
                storage=PaperStorage(directory),
            )
            client = TestClient(create_app(database=db, ingestion_service=service))
            invalid = client.post("/api/papers/ingest", json={"source": "https://example.com/paper"})
            success = client.post("/api/papers/ingest", json={"source": "1706.03762"})
            fetched = client.get(f"/api/papers/{success.json()['id']}")

        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(success.status_code, 200)
        self.assertEqual(success.json()["metadata"]["title"], "API Paper")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["status"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
