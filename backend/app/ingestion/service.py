"""Orchestration for the Phase 2 arXiv ingestion pipeline."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path

from ..core.config import Settings
from ..db.database import SQLDatabase
from ..document.normalizer import DocumentNormalizer
from ..evidence.registry import EvidenceRegistry
from ..models.paper import IngestedPaper, ParsedSection
from .raw import ParsedPaper
from .arxiv.client import ArxivClient
from .arxiv.parser import normalize_arxiv_input
from .errors import IngestionError, PaperParseError, PdfDownloadError
from .isolation import IsolatedPaperParser
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
        self.max_pdf_size = resolved.effective_pdf_max_bytes
        self.max_page_count = resolved.effective_pdf_max_pages
        self.max_paper_text_chars = resolved.effective_pdf_max_text_chars
        self._concurrency_gate = asyncio.Semaphore(resolved.max_concurrent_ingestions)
        parser_impl = parser or _default_parser()
        self.pdf_parser = parser_impl if isinstance(parser_impl, IsolatedPaperParser) else IsolatedPaperParser(
            parser_impl,
            max_bytes=resolved.effective_pdf_max_bytes,
            max_page_count=resolved.effective_pdf_max_pages,
            max_text_chars=resolved.effective_pdf_max_text_chars,
            max_text_chars_per_page=resolved.pdf_max_text_chars_per_page,
            max_images_per_page=resolved.pdf_max_images_per_page,
            max_total_images=resolved.pdf_max_total_images,
            timeout_seconds=resolved.pdf_parse_timeout_seconds,
            memory_limit_bytes=resolved.pdf_parser_memory_limit_bytes,
            cpu_limit_seconds=resolved.pdf_parser_cpu_limit_seconds,
            concurrency=resolved.pdf_parse_concurrency,
        )
        self.normalizer = normalizer or DocumentNormalizer()
        self.evidence_registry = evidence_registry or EvidenceRegistry()

    async def ingest(self, source: str, owner_id: str = "user_legacy_local") -> IngestedPaper:
        """Ingest one source under the configured process-local concurrency bound."""

        async with self._concurrency_gate:
            return await self._ingest(source, owner_id)

    async def _ingest(self, source: str, owner_id: str) -> IngestedPaper:
        identifier = normalize_arxiv_input(source)
        paper_id = _paper_id(identifier.source_identity, owner_id)
        logger.info(json.dumps({"event": "paper_ingestion_started", "component": "ingestion", "paper_id": paper_id}, separators=(",", ":")))

        existing = self.database.get_by_source_identity(identifier.source_identity, owner_id)
        if existing is not None:
            if self.database.get_document(existing.id, owner_id) is None:
                parsed_paper = ParsedPaper.from_legacy_sections(existing.sections, parser_name="legacy")
                document = self.normalizer.normalize(
                    parsed_paper,
                    paper_id=existing.id,
                    metadata=existing.metadata,
                )
                self.database.replace_document(document, self.evidence_registry.build_for_document(document), owner_id)
            return existing

        self.database.create_placeholder(
            paper_id=paper_id,
            source_identity=identifier.source_identity,
            arxiv_id=identifier.canonical_id,
            owner_id=owner_id,
        )
        self.database.update_status(paper_id, "FETCHING_METADATA", owner_id=owner_id)

        local_pdf_path: Path | None = None
        try:
            metadata = await self.arxiv_client.fetch_metadata(identifier)
            self.database.save_metadata(paper_id, metadata, status="DOWNLOADING", owner_id=owner_id)
            pdf_content = await self.arxiv_client.download_pdf(metadata, max_bytes=self.max_pdf_size)
            try:
                local_pdf_path = self.storage.save_pdf(paper_id, pdf_content)
            except OSError as exc:
                raise PdfDownloadError("Unable to store the paper PDF.") from exc

            self.database.update_status(paper_id, "PARSING", owner_id=owner_id)
            logger.info(json.dumps({"event": "pdf_parse_started", "component": "ingestion", "paper_id": paper_id, "byte_size": len(pdf_content)}, separators=(",", ":")))
            parse_started = time.perf_counter()
            parsed_paper = await self.pdf_parser.parse_document(local_pdf_path)
            sections = [
                ParsedSection(
                    title=section.title,
                    order=section.order,
                    text="\n".join(paragraph.text for paragraph in section.paragraphs),
                )
                for section in parsed_paper.sections
                if section.paragraphs
            ]
            if not sections or not parsed_paper.sections:
                raise PaperParseError("The paper was retrieved, but its structure could not be extracted reliably.")
            source_hash = hashlib.sha256(pdf_content).hexdigest()
            parsed_paper.source_hash = source_hash
            document = self.normalizer.normalize(
                parsed_paper,
                paper_id=paper_id,
                metadata=metadata,
                source_hash=source_hash,
            )
            evidence = self.evidence_registry.build_for_document(document)
            # Keep a parsed paper invisible to normal readers until the
            # normalized document and evidence transaction has succeeded.
            self.database.save_parsed(paper_id, metadata, sections, local_pdf_path, owner_id, status="PARSED")
            self.database.replace_document(document, evidence, owner_id)
            self.database.update_status(paper_id, "COMPLETED", owner_id=owner_id)
            completed = self.database.get_by_id(paper_id, owner_id)
            if completed is None:
                raise IngestionError("The paper could not be ingested.")
            logger.info(json.dumps({"event": "pdf_parse_completed", "component": "ingestion", "paper_id": paper_id, "page_count": parsed_paper.page_count, "text_chars": sum(len(paragraph.text) for section in parsed_paper.sections for paragraph in section.paragraphs), "duration_ms": round((time.perf_counter() - parse_started) * 1000, 2), "parser_version": parsed_paper.parser_version}, separators=(",", ":")))
            logger.info(json.dumps({"event": "paper_ingestion_completed", "component": "ingestion", "paper_id": paper_id}, separators=(",", ":")))
            return completed
        except IngestionError as exc:
            if self.database.get_by_id(paper_id, owner_id) is None:
                if local_pdf_path is not None:
                    _discard_source(self.storage, local_pdf_path)
                self.database.update_status(paper_id, "FAILED", error_message=str(exc), owner_id=owner_id)
            code = getattr(exc, "code", type(exc).__name__)
            event = {"PDF_PARSE_TIMEOUT": "pdf_parse_timeout", "PDF_PARSE_FAILED": "pdf_parse_process_failed"}.get(code, "pdf_parse_rejected")
            logger.warning(json.dumps({"event": event, "component": "ingestion", "paper_id": paper_id, "error_code": code}, separators=(",", ":")))
            raise
        except asyncio.CancelledError:
            if self.database.get_by_id(paper_id, owner_id) is None:
                if local_pdf_path is not None:
                    _discard_source(self.storage, local_pdf_path)
                self.database.update_status(paper_id, "FAILED", error_message="The paper ingestion was cancelled.", owner_id=owner_id)
            logger.warning(json.dumps({"event": "pdf_parse_rejected", "component": "ingestion", "paper_id": paper_id, "error_code": "PDF_PARSE_CANCELLED"}, separators=(",", ":")))
            raise
        except Exception as exc:
            if self.database.get_by_id(paper_id, owner_id) is None:
                if local_pdf_path is not None:
                    _discard_source(self.storage, local_pdf_path)
                self.database.update_status(
                    paper_id,
                    "FAILED",
                    error_message="The paper could not be ingested.",
                    owner_id=owner_id,
                )
            logger.warning(json.dumps({"event": "paper_ingestion_failed", "component": "ingestion", "paper_id": paper_id, "error_code": type(exc).__name__}, separators=(",", ":")))
            raise PaperParseError("The paper could not be ingested.") from exc


def _paper_id(source_identity: str, owner_id: str = "user_legacy_local") -> str:
    digest = hashlib.sha256(f"{owner_id}:{source_identity}".encode("utf-8")).hexdigest()[:16]
    return f"paper_{digest}"


def _default_parser() -> PaperParser:
    from .parser import PyMuPDFPaperParser

    return PyMuPDFPaperParser()


def _discard_source(storage: PaperStorage, path: Path) -> None:
    """Best-effort cleanup for a failed parse; never mask the safe error."""

    try:
        storage.delete(path)
    except OSError:
        logger.warning(json.dumps({"event": "pdf_source_cleanup_failed", "component": "ingestion"}, separators=(",", ":")))
