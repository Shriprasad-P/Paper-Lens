"""Semantic retrieval and reciprocal-rank-fusion hybrid retrieval."""

from __future__ import annotations

import hashlib

from ..core.config import Settings
from ..db.database import SQLDatabase
from ..models.chat import RetrievedEvidence
from ..models.document import Evidence
from .embeddings import EmbeddingProvider, cosine_similarity
from .retrieval_adapter import lexical_retrieve

RRF_K = 60
SEMANTIC_RETRIEVER_VERSION = "semantic-v1"
HYBRID_RETRIEVER_VERSION = "hybrid-rrf-v1"


class SemanticEvidenceRetriever:
    def __init__(self, database: SQLDatabase, provider: EmbeddingProvider, *, top_k: int = 8) -> None:
        self.database = database
        self.provider = provider
        self.top_k = max(1, min(top_k, 20))

    async def retrieve_async(self, paper_id: str, query: str, limit: int = 8) -> list[RetrievedEvidence]:
        document = self.database.get_document(paper_id)
        if document is None:
            return []
        evidence = [item for item in self.database.get_evidence_for_document(paper_id, document.id) if item.source_text.strip()]
        if not evidence:
            return []
        query_vector = await self.provider.embed_query(query)
        cached = self.database.get_embeddings(paper_id, document.id, self.provider.model, self.provider.version)
        missing = [item for item in evidence if item.id not in cached or cached[item.id][1] != _evidence_hash(item)]
        if missing:
            vectors = await self.provider.embed_texts([item.source_text for item in missing])
            self.database.save_embeddings(
                paper_id,
                document.id,
                self.provider,
                [(item, vector) for item, vector in zip(missing, vectors)],
            )
            cached = self.database.get_embeddings(paper_id, document.id, self.provider.model, self.provider.version)
        scored = [(cosine_similarity(query_vector, vector), item) for item in evidence if (vector := cached.get(item.id, ([], ""))[0])]
        scored.sort(key=lambda pair: (-pair[0], pair[1].id))
        return [
            RetrievedEvidence(
                evidence_id=item.id,
                paper_id=item.paper_id,
                document_id=item.document_id,
                score=round(max(score, 0.0), 6),
                evidence_type=item.evidence_type.value,
                section_id=item.section_id,
                page=item.page,
                source_text=item.source_text,
                retrieval_method=SEMANTIC_RETRIEVER_VERSION,
                rank=index,
            )
            for index, (score, item) in enumerate(scored[: max(1, min(limit, self.top_k))], start=1)
            if score > 0
        ]


class HybridEvidenceRetriever:
    def __init__(self, database: SQLDatabase, semantic: SemanticEvidenceRetriever, *, lexical: object | None = None) -> None:
        self.database = database
        self.semantic = semantic
        self.lexical = lexical or lexical_retrieve(database)
        self.version = HYBRID_RETRIEVER_VERSION

    async def retrieve_async(self, paper_id: str, query: str, limit: int = 8, section_hint: str | None = None) -> list[RetrievedEvidence]:
        lexical_items = self.lexical.retrieve(paper_id, query, limit=limit, section_hint=section_hint)
        semantic_items = await self.semantic.retrieve_async(paper_id, query, limit=limit)
        by_id = {item.evidence_id: item for item in [*lexical_items, *semantic_items]}
        ranks: dict[str, float] = {}
        for items in (lexical_items, semantic_items):
            for item in items:
                ranks[item.evidence_id] = ranks.get(item.evidence_id, 0.0) + 1.0 / (RRF_K + item.rank)
        ordered = sorted(ranks, key=lambda evidence_id: (-ranks[evidence_id], evidence_id))
        return [
            by_id[evidence_id].model_copy(update={"score": round(ranks[evidence_id], 8), "rank": index, "retrieval_method": self.version})
            for index, evidence_id in enumerate(ordered[: max(1, min(limit, 20))], start=1)
        ]


def _evidence_hash(evidence: Evidence) -> str:
    return hashlib.sha256(evidence.source_text.encode("utf-8")).hexdigest()
