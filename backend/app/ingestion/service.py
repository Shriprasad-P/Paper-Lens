"""Orchestration for the Phase 2 arXiv ingestion pipeline."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..core.config import Settings
from ..db.database import SQLDatabase
from ..models.paper import IngestedPaper
from .arxiv.client import ArxivClient
from .arxiv.parser import normalize_arxiv_input
from .errors import IngestionError, PaperParseError, PdfDownloadError
from .parser import PaperParser
from .storage import PaperStorage


class IngestionService:
    """Keep API, transport, parsing, and persistence responsibilities separate."""

    def __init__(
        self,
        database: SQLDatabase,
        *,
        settings: Settings | None = None,
        arxiv_client: ArxivClient | None = None,
        parser: PaperParser | None = None,
        storage: PaperStorage | None = None,
    ) -> None:
        resolved = settings or Settings.from_env()
        self.database = database
        self.arxiv_client = arxiv_client or ArxivClient(timeout=resolved.arxiv_request_timeout)
        self.parser = parser
        self.storage = storage or PaperStorage(resolved.paper_storage_path)
        self.max_pdf_size = resolved.max_pdf_size

    async def ingest(self, source: str) -> IngestedPaper:
        identifier = normalize_arxiv_input(source)
        paper_id = _paper_id(identifier.source_identity)

        existing = self.database.get_by_source_identity(identifier.source_identity)
        if existing is not None:
            return existing

        self.database.create_placeholder(
            paper_id=paper_id,
            source_identity=identifier.source_identity,
            arxiv_id=identifier.canonical_id,
        )
        self.database.update_status(paper_id, "FETCHING_METADATA")

        try:
            metadata = await self.arxiv_client.fetch_metadata(identifier)
            self.database.save_metadata(paper_id, metadata, status="DOWNLOADING")
            pdf_content = await self.arxiv_client.download_pdf(metadata, max_bytes=self.max_pdf_size)
            try:
                local_pdf_path = self.storage.save_pdf(paper_id, pdf_content)
            except OSError as exc:
                raise PdfDownloadError("Unable to store the paper PDF.") from exc

            self.database.update_status(paper_id, "PARSING")
            parser = self.parser or _default_parser()
            sections = await parser.parse(local_pdf_path)
            if not sections:
                raise PaperParseError("The paper was retrieved, but its structure could not be extracted reliably.")
            return self.database.save_parsed(paper_id, metadata, sections, local_pdf_path)
        except IngestionError as exc:
            self.database.update_status(paper_id, "FAILED", error_message=str(exc))
            raise
        except Exception as exc:
            self.database.update_status(
                paper_id,
                "FAILED",
                error_message="The paper could not be ingested.",
            )
            raise PaperParseError("The paper could not be ingested.") from exc


def _paper_id(source_identity: str) -> str:
    digest = hashlib.sha256(source_identity.encode("utf-8")).hexdigest()[:16]
    return f"paper_{digest}"


def _default_parser() -> PaperParser:
    from .parser import PyMuPDFPaperParser

    return PyMuPDFPaperParser()
