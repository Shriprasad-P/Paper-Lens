"""Deterministic scholarly-input classification and bounded metadata resolution."""

from __future__ import annotations

import re
import hashlib
import json
from enum import Enum
from urllib.parse import quote, urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field

from ..models.paper import PaperMetadata
from .arxiv.client import ArxivClient
from .arxiv.parser import normalize_arxiv_input


class PaperInputType(str, Enum):
    ARXIV_ID = "ARXIV_ID"
    DOI = "DOI"
    PMID = "PMID"
    PMCID = "PMCID"
    SCHOLARLY_URL = "SCHOLARLY_URL"
    CITATION_TEXT = "CITATION_TEXT"
    BIBTEX = "BIBTEX"
    RIS = "RIS"
    PDF_UPLOAD = "PDF_UPLOAD"


class ResolvedPaper(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_id: str
    source_type: PaperInputType
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    publisher_url: str | None = None
    open_access_pdf_url: str | None = None
    user_uploaded_pdf: bool = False
    resolver_provenance: dict[str, object] = Field(default_factory=dict)
    metadata_raw_hash: str | None = None
    candidate_confidence: float | None = Field(default=None, ge=0, le=1)
    candidates: list[dict[str, object]] = Field(default_factory=list)

    def to_metadata(self) -> PaperMetadata:
        return PaperMetadata(
            title=self.title, arxiv_id=self.arxiv_id or "", authors=self.authors,
            published_at=None, updated_at=None, categories=[],
            source_url=self.publisher_url or self.open_access_pdf_url or "",
            pdf_url=self.open_access_pdf_url or "", source_type=self.source_type.value,
            canonical_id=self.canonical_id, doi=self.doi, pmid=self.pmid, pmcid=self.pmcid,
            venue=self.venue, publisher_url=self.publisher_url, open_access_pdf_url=self.open_access_pdf_url,
            resolver_provenance=self.resolver_provenance, metadata_raw_hash=self.metadata_raw_hash,
        )


class PaperInputClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_type: PaperInputType
    normalized: str


class ResolverError(ValueError):
    """Expected resolver failure that is safe to show to a user.

    ``status_code`` lets the HTTP boundary distinguish malformed/ambiguous
    input (422) from a valid paper that still needs a PDF or provider
    confirmation (409), without coupling the resolver to FastAPI.
    """

    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


_DOI_RE = re.compile(r"(?:https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.I)
_ARXIV_RE = re.compile(r"^(?:arxiv:)?\d{4}\.\d{4,5}(?:v\d+)?$", re.I)
_PMID_RE = re.compile(r"^(?:pmid:)?(\d{5,9})$", re.I)
_PMCID_RE = re.compile(r"^(pmc\d+)$", re.I)


def classify_paper_input(value: str) -> PaperInputClassification:
    text = value.strip()
    if not text:
        raise ResolverError("A paper identifier, citation, URL, or BibTeX/RIS record is required.")
    if text.startswith("@") and re.search(r"@(?:article|inproceedings|book|misc)\s*\{", text, re.I):
        return PaperInputClassification(input_type=PaperInputType.BIBTEX, normalized=text)
    if re.search(r"(?:^|\n)TY\s*-\s*\w+", text, re.I) and re.search(r"(?:^|\n)ER\s*-", text, re.I):
        return PaperInputClassification(input_type=PaperInputType.RIS, normalized=text)
    if _ARXIV_RE.fullmatch(text):
        bare = re.sub(r"^arxiv:", "", text, flags=re.I)
        return PaperInputClassification(input_type=PaperInputType.ARXIV_ID, normalized=normalize_arxiv_input(bare).canonical_id)
    doi = _DOI_RE.search(text)
    if doi and (text.lower().startswith("10.") or "doi.org" in text.lower()):
        return PaperInputClassification(input_type=PaperInputType.DOI, normalized=doi.group(1).rstrip(".,") )
    pmcid = _PMCID_RE.fullmatch(text)
    if pmcid:
        return PaperInputClassification(input_type=PaperInputType.PMCID, normalized=pmcid.group(1).upper())
    pmid = _PMID_RE.fullmatch(text)
    if pmid:
        return PaperInputClassification(input_type=PaperInputType.PMID, normalized=pmid.group(1))
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"}:
        if parsed.hostname and "doi.org" in parsed.hostname:
            match = _DOI_RE.search(parsed.path)
            if match:
                return PaperInputClassification(input_type=PaperInputType.DOI, normalized=match.group(1).rstrip(".,"))
        if parsed.hostname and "arxiv.org" in parsed.hostname:
            try:
                return PaperInputClassification(input_type=PaperInputType.ARXIV_ID, normalized=normalize_arxiv_input(text).canonical_id)
            except ValueError:
                pass
        if parsed.hostname and "pubmed.ncbi.nlm.nih.gov" in parsed.hostname:
            match = re.search(r"/(\d{5,9})/?", parsed.path)
            if match:
                return PaperInputClassification(input_type=PaperInputType.PMID, normalized=match.group(1))
        if parsed.hostname and "ncbi.nlm.nih.gov" in parsed.hostname and "/articles/" in parsed.path:
            match = re.search(r"/(PMC\d+)", parsed.path, re.I)
            if match:
                return PaperInputClassification(input_type=PaperInputType.PMCID, normalized=match.group(1).upper())
        return PaperInputClassification(input_type=PaperInputType.SCHOLARLY_URL, normalized=text)
    return PaperInputClassification(input_type=PaperInputType.CITATION_TEXT, normalized=text)


def parse_structured_citation(text: str, input_type: PaperInputType) -> dict[str, object]:
    """Parse only deterministic fields; unresolved citations remain candidates."""

    result: dict[str, object] = {}
    doi = _DOI_RE.search(text)
    if doi:
        result["doi"] = doi.group(1).rstrip(".,")
    year = re.search(r"\b(19|20)\d{2}\b", text)
    if year:
        result["year"] = int(year.group(0))
    if input_type == PaperInputType.BIBTEX:
        for key in ("title", "author", "journal", "booktitle"):
            match = re.search(rf"\b{key}\s*=\s*[{{\"]([^}}\"]+)", text, re.I)
            if match:
                result[key] = re.sub(r"\s+", " ", match.group(1)).strip()
        result["authors"] = [part.strip() for part in str(result.get("author", "")).replace(" and ", "|").split("|") if part.strip()]
    elif input_type == PaperInputType.RIS:
        fields: dict[str, str] = {}
        for line in text.splitlines():
            match = re.match(r"^([A-Z0-9]{2})\s*-\s*(.*)$", line.strip())
            if match:
                fields.setdefault(match.group(1), match.group(2).strip())
        result.update({"title": fields.get("TI"), "venue": fields.get("JO") or fields.get("T2"), "authors": [line.split("  - ", 1)[1].strip() for line in text.splitlines() if line.startswith("AU  - ")], "year": int(fields["PY"][:4]) if fields.get("PY", "")[:4].isdigit() else result.get("year")})
    elif input_type == PaperInputType.CITATION_TEXT:
        # APA places the title after the year; IEEE commonly quotes it.  This
        # is intentionally conservative and leaves confidence low until a
        # metadata service confirms the candidate.
        quoted = re.search(r"[\"“](.+?)[\"”]", text)
        title_match = re.search(r"\)\.\s+(.+?)(?:\.\s|$)", text)
        title = quoted.group(1) if quoted else (title_match.group(1) if title_match else "")
        if not title:
            fragments = [fragment.strip(" .") for fragment in re.split(r"\.{2,}|\n", text) if fragment.strip()]
            if len(fragments) >= 2:
                title = fragments[1]
        if title:
            result["title"] = re.sub(r"\s+", " ", title).strip(" .")
        author_prefix = re.split(r"\(?(?:19|20)\d{2}\)?", text, maxsplit=1)[0].strip(" .")
        if author_prefix and not author_prefix.startswith("["):
            result["authors"] = [author_prefix]
    return {key: value for key, value in result.items() if value not in (None, "", [])}


async def resolve_paper_input(value: str, *, arxiv_client: ArxivClient | None = None, timeout: float = 12.0) -> ResolvedPaper:
    classification = classify_paper_input(value)
    if classification.input_type == PaperInputType.ARXIV_ID:
        identifier = normalize_arxiv_input(classification.normalized)
        metadata = await (arxiv_client or ArxivClient(timeout=timeout)).fetch_metadata(identifier)
        raw_hash = hashlib.sha256(json.dumps(metadata.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
        return ResolvedPaper(canonical_id=identifier.source_identity, source_type=classification.input_type, title=metadata.title, authors=metadata.authors, year=metadata.published_at.year if metadata.published_at else None, arxiv_id=metadata.arxiv_id, publisher_url=metadata.source_url, open_access_pdf_url=metadata.pdf_url, resolver_provenance={"resolver": "arxiv_atom"}, candidate_confidence=1.0, metadata_raw_hash=raw_hash)
    structured = parse_structured_citation(classification.normalized, classification.input_type)
    if classification.input_type == PaperInputType.DOI or structured.get("doi"):
        doi = str(structured.get("doi") or classification.normalized)
        return await _resolve_crossref(doi, classification.input_type, timeout=timeout, structured=structured)
    if classification.input_type in {PaperInputType.PMID, PaperInputType.PMCID}:
        return await _resolve_ncbi(classification.normalized, classification.input_type, timeout=timeout)
    if classification.input_type in {PaperInputType.BIBTEX, PaperInputType.RIS, PaperInputType.CITATION_TEXT}:
        title = str(structured.get("title") or "").strip()
        authors = [str(item) for item in structured.get("authors", [])] if isinstance(structured.get("authors"), list) else []
        if not title:
            raise ResolverError("The citation needs a DOI or a recognizable title before it can be resolved safely.")
        if classification.input_type == PaperInputType.CITATION_TEXT:
            return await _resolve_citation_text(classification.normalized, title, authors, structured, timeout=timeout)
        return ResolvedPaper(canonical_id=f"citation:{hashlib.sha256(classification.normalized.encode()).hexdigest()[:20]}", source_type=classification.input_type, title=title, authors=authors, year=structured.get("year") if isinstance(structured.get("year"), int) else None, venue=str(structured.get("journal") or structured.get("venue") or "") or None, doi=str(structured.get("doi") or "") or None, publisher_url=None, resolver_provenance={"resolver": "deterministic_citation_parser", "needs_candidate_confirmation": True}, candidate_confidence=0.55, candidates=[], metadata_raw_hash=hashlib.sha256(classification.normalized.encode()).hexdigest())
    return ResolvedPaper(canonical_id=classification.normalized, source_type=classification.input_type, title=classification.normalized, publisher_url=classification.normalized, resolver_provenance={"resolver": "url_only", "requires_pdf_upload": True}, candidate_confidence=0.2)


async def _resolve_crossref(doi: str, input_type: PaperInputType, *, timeout: float, structured: dict[str, object]) -> ResolvedPaper:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout), follow_redirects=False, headers={"Accept": "application/json", "User-Agent": "PaperLens/0.1"}) as client:
            response = await client.get(f"https://api.crossref.org/works/{quote(doi, safe='/')}")
            response.raise_for_status()
            message = response.json().get("message", {})
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise ResolverError("The DOI could not be resolved from scholarly metadata.") from exc
    links = message.get("link", []) if isinstance(message, dict) else []
    pdf = next((str(item.get("URL")) for item in links if isinstance(item, dict) and "pdf" in str(item.get("content-type", "")).lower()), None)
    authors = [" ".join(filter(None, [str(item.get("given", "")), str(item.get("family", ""))])).strip() for item in message.get("author", []) if isinstance(item, dict)]
    title = (message.get("title") or [""])[0]
    raw_hash = hashlib.sha256(json.dumps(message, sort_keys=True, default=str).encode()).hexdigest()
    return ResolvedPaper(canonical_id=f"doi:{doi}", source_type=input_type, title=str(title).strip() or doi, authors=[item for item in authors if item], year=_crossref_year(message) or (structured.get("year") if isinstance(structured.get("year"), int) else None), venue=str((message.get("container-title") or [""])[0]) or None, doi=doi, publisher_url=str(message.get("URL")) if message.get("URL") else f"https://doi.org/{doi}", open_access_pdf_url=pdf, resolver_provenance={"resolver": "crossref", "doi": doi}, candidate_confidence=0.98, metadata_raw_hash=raw_hash)


async def _resolve_citation_text(text: str, title: str, authors: list[str], structured: dict[str, object], *, timeout: float) -> ResolvedPaper:
    """Search Crossref for a citation, but retain ambiguity when ranking is weak."""

    candidates: list[dict[str, object]] = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout), follow_redirects=False, headers={"Accept": "application/json", "User-Agent": "PaperLens/0.1"}) as client:
            response = await client.get("https://api.crossref.org/works", params={"query.bibliographic": text[:1_000], "rows": 5})
            response.raise_for_status()
            items = response.json().get("message", {}).get("items", [])
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            item_title = str((item.get("title") or [""])[0]).strip()
            if not item_title:
                continue
            item_doi = str(item.get("DOI") or "") or None
            candidates.append({"title": item_title, "doi": item_doi, "year": _crossref_year(item), "venue": str((item.get("container-title") or [""])[0]) or None, "publisher_url": str(item.get("URL") or "") or (f"https://doi.org/{item_doi}" if item_doi else None)})
    except (httpx.HTTPError, ValueError, TypeError):
        candidates = []
    best = candidates[0] if candidates else {}
    confidence = 0.55
    if best.get("title") and _title_similarity(title, str(best["title"])) >= 0.8:
        confidence = 0.82
    return ResolvedPaper(
        canonical_id=f"citation:{hashlib.sha256(text.encode()).hexdigest()[:20]}", source_type=PaperInputType.CITATION_TEXT,
        title=str(best.get("title") or title), authors=authors, year=best.get("year") if isinstance(best.get("year"), int) else (structured.get("year") if isinstance(structured.get("year"), int) else None),
        venue=str(best.get("venue") or "") or None, doi=str(best.get("doi") or "") or None, publisher_url=str(best.get("publisher_url") or "") or None,
        resolver_provenance={"resolver": "crossref_bibliographic", "needs_candidate_confirmation": confidence < 0.9}, candidate_confidence=confidence, candidates=candidates,
        metadata_raw_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def _crossref_year(item: dict[str, object]) -> int | None:
    published = item.get("published")
    if isinstance(published, dict):
        parts = published.get("date-parts")
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0] and isinstance(parts[0][0], int):
            return parts[0][0]
    return None


def _title_similarity(left: str, right: str) -> float:
    left_words = set(re.findall(r"[a-z0-9]+", left.lower()))
    right_words = set(re.findall(r"[a-z0-9]+", right.lower()))
    if not left_words or not right_words:
        return 0.0
    return len(left_words & right_words) / max(1, len(left_words | right_words))


async def _resolve_ncbi(identifier: str, input_type: PaperInputType, *, timeout: float) -> ResolvedPaper:
    db = "pmc" if input_type == PaperInputType.PMCID else "pubmed"
    value = identifier.upper() if input_type == PaperInputType.PMCID else identifier
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout), follow_redirects=False) as client:
            response = await client.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi", params={"db": db, "id": value.removeprefix("PMC"), "retmode": "json"})
            response.raise_for_status()
            result = response.json().get("result", {})
            record = result.get(value.removeprefix("PMC"), {})
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise ResolverError("The PubMed record could not be resolved.") from exc
    title = str(record.get("title") or identifier)
    authors = [str(item.get("name")) for item in record.get("authors", []) if isinstance(item, dict) and item.get("name")]
    raw_hash = hashlib.sha256(json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()
    return ResolvedPaper(canonical_id=f"{input_type.value.lower()}:{identifier}", source_type=input_type, title=title, authors=authors, year=int(str(record.get("pubdate", ""))[:4]) if str(record.get("pubdate", ""))[:4].isdigit() else None, pmid=identifier if input_type == PaperInputType.PMID else None, pmcid=identifier if input_type == PaperInputType.PMCID else None, publisher_url=f"https://pubmed.ncbi.nlm.nih.gov/{identifier}/" if input_type == PaperInputType.PMID else f"https://www.ncbi.nlm.nih.gov/pmc/articles/{identifier}/", resolver_provenance={"resolver": "ncbi_esummary"}, candidate_confidence=0.92, metadata_raw_hash=raw_hash)
