"""Orchestration for the Phase 2 arXiv ingestion pipeline."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path

from ..core.config import Settings
from ..db.database import SQLDatabase
from ..document.normalizer import DocumentNormalizer
from ..evidence.registry import EvidenceRegistry
from ..models.paper import IngestedPaper
from .raw import ParsedPaper
from .arxiv.client import ArxivClient
from .arxiv.parser import normalize_arxiv_input
from .errors import IngestionError, PaperParseError, PdfDownloadError
from .parser import PaperParser
from .storage import PaperStorage

logger = logging.getLogger("paperlens.ingestion")


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
        normalizer: DocumentNormalizer | None = None,
        evidence_registry: EvidenceRegistry | None = None,
    ) -> None:
        resolved = settings or Settings.from_env()
        self.database = database
        self.arxiv_client = arxiv_client or ArxivClient(timeout=resolved.arxiv_request_timeout)
        self.parser = parser
        self.storage = storage or PaperStorage(resolved.paper_storage_path)
        self.storage.root.mkdir(parents=True, exist_ok=True)
        self.max_pdf_size = resolved.max_pdf_size
        self.max_page_count = resolved.max_page_count
        self.max_paper_text_chars = resolved.max_paper_text_chars
        self._concurrency_gate = asyncio.Semaphore(resolved.max_concurrent_ingestions)
        self.normalizer = normalizer or DocumentNormalizer()
        self.evidence_registry = evidence_registry or EvidenceRegistry()

    async def ingest(self, source: str) -> IngestedPaper:
        """Ingest one source under the configured process-local concurrency bound."""

        async with self._concurrency_gate:
            return await self._ingest(source)

    async def _ingest(self, source: str) -> IngestedPaper:
        identifier = normalize_arxiv_input(source)
        paper_id = _paper_id(identifier.source_identity)
        logger.info(json.dumps({"event": "paper_ingestion_started", "component": "ingestion", "paper_id": paper_id}, separators=(",", ":")))

        existing = self.database.get_by_source_identity(identifier.source_identity)
        if existing is not None:
            if self.database.get_document(existing.id) is None:
                parsed_paper = ParsedPaper.from_legacy_sections(existing.sections, parser_name="legacy")
                document = self.normalizer.normalize(
                    parsed_paper,
                    paper_id=existing.id,
                    metadata=existing.metadata,
                )
                self.database.replace_document(document, self.evidence_registry.build_for_document(document))
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
            parse_document = getattr(parser, "parse_document", None)
            if callable(parse_document):
                parsed_paper = await parse_document(local_pdf_path)
            else:
                parsed_paper = ParsedPaper.from_legacy_sections(sections, parser_name=parser.__class__.__name__)
            if not sections or not parsed_paper.sections:
                raise PaperParseError("The paper was retrieved, but its structure could not be extracted reliably.")
            if parsed_paper.page_count is not None and parsed_paper.page_count > self.max_page_count:
                raise PaperParseError("The paper exceeds the configured page-count limit.")
            text_size = sum(len(paragraph.text) for section in parsed_paper.sections for paragraph in section.paragraphs)
            if text_size > self.max_paper_text_chars:
                raise PaperParseError("The paper exceeds the configured extracted-text limit.")
            completed = self.database.save_parsed(paper_id, metadata, sections, local_pdf_path)
            source_hash = hashlib.sha256(pdf_content).hexdigest()
            document = self.normalizer.normalize(
                parsed_paper,
                paper_id=paper_id,
                metadata=metadata,
                source_hash=source_hash,
            )
            evidence = self.evidence_registry.build_for_document(document)
            self.database.replace_document(document, evidence)
            logger.info(json.dumps({"event": "paper_ingestion_completed", "component": "ingestion", "paper_id": paper_id}, separators=(",", ":")))
            return completed
        except IngestionError as exc:
            self.database.update_status(paper_id, "FAILED", error_message=str(exc))
            logger.warning(json.dumps({"event": "paper_ingestion_failed", "component": "ingestion", "paper_id": paper_id, "error_code": type(exc).__name__}, separators=(",", ":")))
            raise
        except Exception as exc:
            self.database.update_status(
                paper_id,
                "FAILED",
                error_message="The paper could not be ingested.",
            )
            logger.warning(json.dumps({"event": "paper_ingestion_failed", "component": "ingestion", "paper_id": paper_id, "error_code": type(exc).__name__}, separators=(",", ":")))
            raise PaperParseError("The paper could not be ingested.") from exc


def _paper_id(source_identity: str) -> str:
    digest = hashlib.sha256(source_identity.encode("utf-8")).hexdigest()[:16]
    return f"paper_{digest}"


def _default_parser() -> PaperParser:
    from .parser import PyMuPDFPaperParser

    return PyMuPDFPaperParser()
