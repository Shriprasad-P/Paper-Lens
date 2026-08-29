"""Provider-neutral deterministic retrieval over the Evidence Registry."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Protocol

from ..db.database import SQLDatabase
from ..models.chat import RetrievedEvidence
from ..models.document import Evidence

RETRIEVER_VERSION = "bm25-v1"
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[-_/+.][A-Za-z0-9]+)*|±|%")
_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "in", "is", "it",
    "of", "on", "or", "that", "the", "their", "this", "to", "was", "what", "which", "with", "why",
}
_SECTION_HINTS: dict[str, tuple[str, ...]] = {
    "limitation": ("limitation", "discussion", "conclusion"),
    "limitations": ("limitation", "discussion", "conclusion"),
    "dataset": ("experiment", "evaluation", "method"),
    "datasets": ("experiment", "evaluation", "method"),
    "result": ("result", "experiment", "evaluation", "conclusion"),
    "results": ("result", "experiment", "evaluation", "conclusion"),
    "contribution": ("abstract", "introduction", "contribution", "conclusion"),
    "contributions": ("abstract", "introduction", "contribution", "conclusion"),
    "problem": ("abstract", "introduction", "motivation"),
    "method": ("method", "approach", "model", "architecture"),
    "architecture": ("method", "approach", "model", "architecture"),
}
_HEADING_NOISE_RE = re.compile(r"^\d+(?:\.\d+)*\s+\S")


class EvidenceRetriever(Protocol):
    def retrieve(
        self,
        paper_id: str,
        query: str,
        limit: int = 8,
        section_hint: str | None = None,
        owner_id: str = "user_legacy_local",
    ) -> list[RetrievedEvidence]:
        """Return bounded, ranked evidence without leaking persistence objects."""


def normalize_query(query: str) -> str:
    """Normalize punctuation and whitespace while preserving scientific tokens."""

    return " ".join(token.lower() for token in _TOKEN_RE.findall(query) if token.lower() not in _STOP_WORDS)


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text)]


class BM25EvidenceRetriever:
    """Small in-process BM25 index suitable for the current ~538 paragraph corpus."""

    def __init__(self, database: SQLDatabase, *, version: str = RETRIEVER_VERSION) -> None:
        self.database = database
        self.version = version
        self._cache: dict[tuple[str, str, str, str, int, str | None, str], list[RetrievedEvidence]] = {}

    def retrieve(
        self,
        paper_id: str,
        query: str,
        limit: int = 8,
        section_hint: str | None = None,
        owner_id: str = "user_legacy_local",
    ) -> list[RetrievedEvidence]:
        normalized = normalize_query(query)
        bounded_limit = max(1, min(limit, 20))
        if not normalized:
            return []

        document = self.database.get_document(paper_id, owner_id)
        if document is None:
            return []
        cache_key = (
            paper_id,
            document.document_hash or document.id,
            self.version,
            normalized,
            bounded_limit,
            section_hint.lower() if section_hint else None,
            owner_id,
        )
        if cache_key in self._cache:
            return [item.model_copy() for item in self._cache[cache_key]]
        evidence = self.database.get_evidence_for_document(paper_id, document.id, owner_id)
        # Keep the Evidence Registry authoritative, but avoid indexing parser noise such as
        # one-character figure labels and page-number paragraphs as primary chat context.
        paragraphs = [
            item
            for item in evidence
            if item.source_text.strip()
            and (len(item.source_text.strip()) >= 24 or len(tokenize(item.source_text)) >= 5)
            and not (_HEADING_NOISE_RE.match(item.source_text.strip()) and len(tokenize(item.source_text)) <= 8)
        ]
        if not paragraphs:
            return []
        titles = {section.id: section.title for section in document.sections}
        query_tokens = tokenize(normalized)
        documents = [tokenize(item.source_text) + tokenize(titles.get(item.section_id or "", "")) for item in paragraphs]
        document_frequency = Counter(token for tokens in documents for token in set(tokens))
        average_length = sum(len(tokens) for tokens in documents) / max(len(documents), 1)
        scored: list[tuple[float, Evidence]] = []
        hints = self._section_hints(normalized, section_hint)
        for item, tokens in zip(paragraphs, documents):
            score = _bm25_score(query_tokens, tokens, document_frequency, len(documents), average_length)
            title = titles.get(item.section_id or "", "").lower()
            if score > 0 and hints and any(hint in title for hint in hints):
                score += 0.35
            if any(term in title for term in ("reference", "bibliography")) and "reference" not in query_tokens:
                score *= 0.03
            if re.match(r"^(table|figure)\b", item.source_text.strip(), flags=re.IGNORECASE) and not any(
                token in {"table", "figure"} for token in query_tokens
            ):
                score *= 0.3
            if score > 0:
                scored.append((score, item))
        scored.sort(key=lambda pair: (-pair[0], pair[1].id))
        results = [
            RetrievedEvidence(
                evidence_id=item.id,
                paper_id=item.paper_id,
                document_id=item.document_id,
                score=round(score, 6),
                evidence_type=item.evidence_type.value,
                section_id=item.section_id,
                page=item.page,
                source_text=item.source_text,
                retrieval_method=self.version,
                rank=index,
            )
            for index, (score, item) in enumerate(scored[:bounded_limit], start=1)
        ]
        self._cache[cache_key] = results
        return [item.model_copy() for item in results]

    @staticmethod
    def _section_hints(normalized_query: str, section_hint: str | None) -> tuple[str, ...]:
        if section_hint:
            return (section_hint.lower(),)
        hints: list[str] = []
        for term, values in _SECTION_HINTS.items():
            if term in normalized_query.split():
                hints.extend(values)
        return tuple(dict.fromkeys(hints))


def _bm25_score(
    query_tokens: list[str],
    document_tokens: list[str],
    document_frequency: Counter[str],
    document_count: int,
    average_length: float,
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    if not document_tokens or not query_tokens:
        return 0.0
    frequencies = Counter(document_tokens)
    length = len(document_tokens)
    score = 0.0
    for token in query_tokens:
        if token not in frequencies:
            continue
        df = document_frequency[token]
        idf = math.log(1 + (document_count - df + 0.5) / (df + 0.5))
        tf = frequencies[token]
        denominator = tf + k1 * (1 - b + b * length / max(average_length, 1))
        score += idf * ((tf * (k1 + 1)) / denominator)
    return score
