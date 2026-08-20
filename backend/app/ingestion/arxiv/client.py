"""Async arXiv metadata and PDF transport client."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any

import httpx

from .parser import ArxivIdentifier
from ..errors import (
    ArxivMetadataError,
    ArxivNotFoundError,
    PdfDownloadError,
    PdfValidationError,
)
from ...models.paper import PaperMetadata

_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
_WHITESPACE_RE = re.compile(r"\s+")


class ArxivClient:
    """Small client constrained to the public arXiv API and PDF endpoints."""

    metadata_endpoint = "https://export.arxiv.org/api/query"

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        user_agent: str = "PaperLens/0.1 (research paper ingestion)",
    ) -> None:
        self.timeout = httpx.Timeout(timeout)
        self.transport = transport
        self.user_agent = user_agent

    async def fetch_metadata(self, identifier: ArxivIdentifier) -> PaperMetadata:
        """Fetch and normalize one arXiv Atom entry."""

        params = {"id_list": identifier.canonical_id, "max_results": "1"}
        try:
            async with self._client() as client:
                response = await client.get(self.metadata_endpoint, params=params)
        except httpx.HTTPError as exc:
            raise ArxivMetadataError("Unable to retrieve metadata from arXiv.") from exc

        if response.status_code == 404:
            raise ArxivNotFoundError("The arXiv paper was not found.")
        if response.status_code >= 400:
            raise ArxivMetadataError("Unable to retrieve metadata from arXiv.")
        if response.url.host and response.url.host.lower() not in {"export.arxiv.org", "arxiv.org"}:
            raise ArxivMetadataError("The arXiv metadata request redirected to an untrusted host.")

        try:
            root = ET.fromstring(response.text)
            entry = root.find("atom:entry", _ATOM_NS)
            if entry is None:
                raise ArxivNotFoundError("The arXiv paper was not found.")
            title = _required_text(entry, "atom:title")
            abstract = _optional_text(entry, "atom:summary")
            authors = [
                _required_text(author, "atom:name")
                for author in entry.findall("atom:author", _ATOM_NS)
            ]
            categories = [
                category.attrib["term"]
                for category in entry.findall("atom:category", _ATOM_NS)
                if category.attrib.get("term")
            ]
            published_at = _parse_datetime(_optional_text(entry, "atom:published"))
            updated_at = _parse_datetime(_optional_text(entry, "atom:updated"))
        except ArxivNotFoundError:
            raise
        except (ET.ParseError, KeyError, ValueError, TypeError) as exc:
            raise ArxivMetadataError("Unable to interpret metadata from arXiv.") from exc

        canonical = identifier.canonical_id
        return PaperMetadata(
            arxiv_id=canonical,
            title=_clean(title),
            authors=[_clean(author) for author in authors],
            abstract=_clean(abstract) if abstract else None,
            published_at=published_at,
            updated_at=updated_at,
            categories=categories,
            source_url=f"https://arxiv.org/abs/{canonical}",
            pdf_url=f"https://arxiv.org/pdf/{canonical}.pdf",
        )

    async def download_pdf(self, metadata: PaperMetadata, *, max_bytes: int) -> bytes:
        """Download a PDF and validate status, size, and file signature."""

        try:
            async with self._client() as client:
                async with client.stream("GET", metadata.pdf_url) as response:
                    if response.status_code >= 400:
                        raise PdfDownloadError("Unable to retrieve the paper PDF.")
                    if response.url.host and response.url.host.lower() not in {"arxiv.org", "export.arxiv.org"}:
                        raise PdfDownloadError("The paper PDF redirected to an untrusted host.")
                    content_length = response.headers.get("content-length")
                    if content_length:
                        try:
                            if int(content_length) > max_bytes:
                                raise PdfValidationError("The paper PDF exceeds the configured size limit.")
                        except ValueError:
                            pass
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise PdfValidationError("The paper PDF exceeds the configured size limit.")
                        chunks.append(chunk)
                    body = b"".join(chunks)
        except httpx.HTTPError as exc:
            raise PdfDownloadError("Unable to retrieve the paper PDF.") from exc
        content_type = response.headers.get("content-type", "").lower()
        if not body or not body.startswith(b"%PDF-"):
            raise PdfValidationError("The downloaded paper is not a usable PDF.")
        if content_type.startswith("text/html"):
            raise PdfValidationError("The downloaded paper is not a usable PDF.")
        return body

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            max_redirects=3,
            headers={"User-Agent": self.user_agent, "Accept": "application/atom+xml, application/pdf"},
            transport=self.transport,
        )


def _required_text(parent: ET.Element, path: str) -> str:
    value = parent.findtext(path, default="", namespaces=_ATOM_NS)
    cleaned = _clean(value)
    if not cleaned:
        raise ValueError(f"Missing required arXiv metadata field: {path}")
    return cleaned


def _optional_text(parent: ET.Element, path: str) -> str | None:
    value = parent.findtext(path, default=None, namespaces=_ATOM_NS)
    cleaned = _clean(value) if value else ""
    return cleaned or None


def _clean(value: str | None) -> str:
    return _WHITESPACE_RE.sub(" ", value or "").strip()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
