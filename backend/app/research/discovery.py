"""Provider-neutral literature discovery, starting with official arXiv Atom."""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from datetime import datetime

import httpx

from ..models.research import PaperCandidate

_ATOM = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
_ARXIV_RE = re.compile(r"(?<!\d)(\d{4}\.\d{4,5})(?:v(\d+))?\b", re.IGNORECASE)
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)


class LiteratureDiscoveryError(Exception):
    """Safe provider boundary failure."""


class LiteratureDiscoveryProvider(ABC):
    name = "unknown"

    @abstractmethod
    async def search(self, query: str, limit: int) -> list[PaperCandidate]:
        """Return discovery metadata, never authoritative evidence."""


class ArxivDiscoveryProvider(LiteratureDiscoveryProvider):
    name = "arxiv"
    endpoint = "https://export.arxiv.org/api/query"

    def __init__(self, *, timeout: float = 30.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.timeout = httpx.Timeout(timeout)
        self.transport = transport

    async def search(self, query: str, limit: int) -> list[PaperCandidate]:
        bounded = max(1, min(limit, 30))
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport, follow_redirects=True, headers={"User-Agent": "PaperLens/0.1"}) as client:
                response = await client.get(self.endpoint, params={"search_query": f"all:{query}", "start": 0, "max_results": bounded, "sortBy": "relevance", "sortOrder": "descending"})
                response.raise_for_status()
        except (httpx.HTTPError, ValueError) as exc:
            raise LiteratureDiscoveryError("The arXiv discovery provider is unavailable.") from exc
        try:
            root = ET.fromstring(response.text)
        except ET.ParseError as exc:
            raise LiteratureDiscoveryError("The arXiv discovery response was invalid.") from exc
        candidates: list[PaperCandidate] = []
        for rank, entry in enumerate(root.findall("atom:entry", _ATOM), start=1):
            title = _clean(entry.findtext("atom:title", default="", namespaces=_ATOM))
            if not title:
                continue
            identifier = _arxiv_from_entry(entry)
            published = _parse_datetime(entry.findtext("atom:published", default=None, namespaces=_ATOM))
            authors = [_clean(item.findtext("atom:name", default="", namespaces=_ATOM)) for item in entry.findall("atom:author", _ATOM) if _clean(item.findtext("atom:name", default="", namespaces=_ATOM))]
            candidates.append(PaperCandidate(
                candidate_id=_candidate_id(identifier, None, title),
                title=title,
                authors=authors,
                abstract=_clean(entry.findtext("atom:summary", default="", namespaces=_ATOM)) or None,
                year=published.year if published else None,
                published_at=published,
                arxiv_id=identifier,
                canonical_url=f"https://arxiv.org/abs/{identifier}" if identifier else None,
                pdf_url=f"https://arxiv.org/pdf/{identifier}.pdf" if identifier else None,
                discovery_provider=self.name,
                discovery_query=query,
                discovery_rank=rank,
            ))
        return candidates


def normalize_candidate(candidate: PaperCandidate) -> PaperCandidate:
    arxiv = normalize_arxiv_id(candidate.arxiv_id)
    doi = normalize_doi(candidate.doi)
    title = _clean(candidate.title)
    return candidate.model_copy(update={
        "title": title,
        "authors": [_clean(item) for item in candidate.authors if _clean(item)],
        "arxiv_id": arxiv,
        "doi": doi,
        "canonical_url": candidate.canonical_url.strip() if candidate.canonical_url else None,
        "pdf_url": candidate.pdf_url.strip() if candidate.pdf_url else None,
        "candidate_id": _candidate_id(arxiv, doi, title),
    })


def normalize_arxiv_id(value: str | None) -> str | None:
    if not value:
        return None
    match = _ARXIV_RE.search(value.strip())
    return match.group(1) if match else None


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    match = _DOI_RE.search(value.strip())
    return match.group(0).rstrip(".,)").lower() if match else None


def _arxiv_from_entry(entry: ET.Element) -> str | None:
    raw = entry.findtext("atom:id", default="", namespaces=_ATOM)
    match = _ARXIV_RE.search(raw)
    return match.group(1) if match else None


def _candidate_id(arxiv: str | None, doi: str | None, title: str) -> str:
    identity = f"arxiv:{arxiv}" if arxiv else f"doi:{doi}" if doi else f"title:{normalize_title(title)}"
    return "candidate_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
