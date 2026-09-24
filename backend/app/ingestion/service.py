"""Orchestration for the Phase 2 arXiv ingestion pipeline."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from ..core.config import Settings
from ..db.database import SQLDatabase
from ..document.normalizer import DocumentNormalizer
from ..evidence.registry import EvidenceRegistry
from ..models.paper import IngestedPaper, ParsedSection
from .raw import ParsedPaper
from .arxiv.client import ArxivClient
from .arxiv.parser import normalize_arxiv_input
from .resolver import PaperInputType, ResolverError, ResolvedPaper, classify_paper_input, resolve_paper_input
from .errors import IngestionError, PaperParseError, PdfDownloadError, PdfTooLargeError
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

    async def resolve(self, source: str) -> ResolvedPaper:
        """Classify and resolve a scholarly identifier without storing a paper."""

        # Test doubles and alternative clients do not necessarily expose the
        # ``httpx.Timeout`` object used by the built-in arXiv client.  Keep the
        # resolver boundary client-agnostic and use the configured timeout only
        # when it is available.
        timeout = 12.0
        client_timeout = getattr(self.arxiv_client, "timeout", None)
        read_timeout = getattr(client_timeout, "read", None)
        if isinstance(read_timeout, (int, float)) and read_timeout > 0:
            timeout = float(read_timeout)
        return await resolve_paper_input(source, arxiv_client=self.arxiv_client, timeout=timeout)

    async def ingest_input(self, source: str, owner_id: str = "user_legacy_local") -> IngestedPaper:
        """Ingest any supported scholarly input that has a retrievable PDF."""

        classification = classify_paper_input(source)
        if classification.input_type == PaperInputType.ARXIV_ID:
            return await self.ingest(classification.normalized, owner_id)
        resolved = await self.resolve(source)
        if not resolved.open_access_pdf_url:
            status_code = 422 if resolved.source_type == PaperInputType.SCHOLARLY_URL else 409
            raise ResolverError("Paper identified. Upload the PDF to continue full-paper analysis.", status_code=status_code)
        return await self._ingest_resolved(resolved, owner_id)

    async def ingest_upload(self, content: bytes, filename: str, owner_id: str = "user_legacy_local") -> IngestedPaper:
        """Parse a user-provided PDF through the same isolated Phase 14 parser."""

        if not content.startswith(b"%PDF-"):
            raise PaperParseError("The uploaded file is not a usable PDF.")
        if len(content) > self.max_pdf_size:
            raise PdfTooLargeError("The uploaded PDF exceeds the configured size limit.")
        safe_name = Path(filename or "paper.pdf").name
        title = Path(safe_name).stem.replace("_", " ").replace("-", " ").strip() or "Uploaded research paper"
        digest = hashlib.sha256(content).hexdigest()
        resolved = ResolvedPaper(
            canonical_id=f"upload:{digest}", source_type=PaperInputType.PDF_UPLOAD, title=title,
            publisher_url=None, open_access_pdf_url=None, user_uploaded_pdf=True,
            resolver_provenance={"resolver": "pdf_upload", "filename": safe_name}, candidate_confidence=1.0,
            metadata_raw_hash=digest,
        )
        return await self._ingest_pdf_bytes(resolved, content, owner_id)

    async def _ingest_resolved(self, resolved: ResolvedPaper, owner_id: str) -> IngestedPaper:
        pdf_url = resolved.open_access_pdf_url or ""
        if not _safe_document_url(pdf_url):
            raise PdfDownloadError("The resolved paper PDF URL is not safe to retrieve.")
        try:
            async with self.arxiv_client._client() as client:
                response = await client.get(pdf_url)
                response.raise_for_status()
                if not _safe_document_url(str(response.url)):
                    raise PdfDownloadError("The paper PDF redirected to an untrusted host.")
                content = response.content
        except (httpx.HTTPError, ValueError) as exc:
            raise PdfDownloadError("Unable to retrieve the resolved paper PDF.") from exc
        return await self._ingest_pdf_bytes(resolved, content, owner_id)

    async def _ingest_pdf_bytes(self, resolved: ResolvedPaper, content: bytes, owner_id: str) -> IngestedPaper:
        if len(content) > self.max_pdf_size:
            raise PdfTooLargeError("The paper PDF exceeds the configured size limit.")
        if not content.startswith(b"%PDF-"):
            raise PaperParseError("The paper was resolved, but the retrieved file is not a usable PDF.")
        source_identity = resolved.canonical_id
        paper_id = _paper_id(source_identity, owner_id)
        existing = self.database.get_by_source_identity(source_identity, owner_id)
        if existing is not None:
            return existing
        self.database.create_placeholder(paper_id=paper_id, source_identity=source_identity, arxiv_id=resolved.arxiv_id or "", owner_id=owner_id, source_type=resolved.source_type.value)
        metadata = resolved.to_metadata()
        self.database.save_metadata(paper_id, metadata, status="PARSING", owner_id=owner_id)
        local_pdf_path: Path | None = None
        try:
            local_pdf_path = self.storage.save_pdf(paper_id, content)
            parsed_paper = await self.pdf_parser.parse_document(local_pdf_path)
            sections = [ParsedSection(title=section.title, order=section.order, text="\n".join(paragraph.text for paragraph in section.paragraphs)) for section in parsed_paper.sections if section.paragraphs]
            if not sections:
                raise PaperParseError("The paper was retrieved, but its structure could not be extracted reliably.")
            source_hash = hashlib.sha256(content).hexdigest()
            parsed_paper.source_hash = source_hash
            document = self.normalizer.normalize(parsed_paper, paper_id=paper_id, metadata=metadata, source_hash=source_hash)
            evidence = self.evidence_registry.build_for_document(document)
            self.database.save_parsed(paper_id, metadata, sections, local_pdf_path, owner_id, status="PARSED")
            self.database.replace_document(document, evidence, owner_id)
            self.database.update_status(paper_id, "COMPLETED", owner_id=owner_id)
            completed = self.database.get_by_id(paper_id, owner_id)
            if completed is None:
                raise IngestionError("The paper could not be ingested.")
            return completed
        except Exception:
            if local_pdf_path is not None:
                _discard_source(self.storage, local_pdf_path)
            self.database.update_status(paper_id, "FAILED", error_message="The paper could not be ingested.", owner_id=owner_id)
            raise

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


def _safe_document_url(value: str) -> bool:
    """Allow public HTTP(S) document retrieval while blocking local SSRF targets."""

    parsed = urlparse(value)
    host = (parsed.hostname or "").strip().lower()
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        return False
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast)
