"""Bounded retrieval over the Evidence Registry for several papers."""

from __future__ import annotations

import math

from ..core.config import Settings
from ..db.database import SQLDatabase
from ..models.chat import RetrievedEvidence
from ..retrieval.embeddings import create_embedding_provider
from ..retrieval.hybrid import HybridEvidenceRetriever, SemanticEvidenceRetriever
from ..chat.retrieval import BM25EvidenceRetriever


class CrossPaperEvidenceRetriever:
    """Compose the existing retrievers while retaining paper/document identity."""

    def __init__(self, database: SQLDatabase, *, settings: Settings | None = None, top_k: int = 8, lexical: object | None = None, semantic: SemanticEvidenceRetriever | None = None, hybrid: HybridEvidenceRetriever | None = None) -> None:
        self.database = database
        self.settings = settings or Settings.from_env()
        self.top_k = max(1, min(top_k, 20))
        self.lexical = lexical or BM25EvidenceRetriever(database)
        self.semantic = semantic or SemanticEvidenceRetriever(
            database,
            create_embedding_provider(self.settings),
            top_k=self.top_k,
        )
        self.hybrid = hybrid or HybridEvidenceRetriever(database, self.semantic, lexical=self.lexical)

    async def retrieve_async(
        self,
        query: str,
        paper_ids: list[str],
        *,
        limit: int = 12,
        mode: str | None = None,
        owner_id: str = "user_legacy_local",
    ) -> list[RetrievedEvidence]:
        allowed = list(dict.fromkeys(paper_ids))
        if not allowed or not query.strip():
            return []
        bounded = max(1, min(limit, 40))
        per_paper = max(1, min(self.top_k, math.ceil(bounded / len(allowed)) + 2))
        selected_mode = (mode or self.settings.retrieval_mode or "LEXICAL").upper()
        lists: dict[str, list[RetrievedEvidence]] = {}
        for paper_id in allowed:
            try:
                if selected_mode == "SEMANTIC":
                    items = await self.semantic.retrieve_async(paper_id, query, limit=per_paper, owner_id=owner_id)
                elif selected_mode == "HYBRID" or self.settings.hybrid_retrieval_enabled:
                    items = await self.hybrid.retrieve_async(paper_id, query, limit=per_paper, owner_id=owner_id)
                else:
                    items = self.lexical.retrieve(paper_id, query, limit=per_paper, owner_id=owner_id)
            except Exception:
                # One unavailable embedding provider must not hide lexical evidence from other papers.
                items = self.lexical.retrieve(paper_id, query, limit=per_paper, owner_id=owner_id)
            lists[paper_id] = [
                item.model_copy(update={"paper_id": item.paper_id or paper_id})
                for item in items
                if (item.paper_id or paper_id) == paper_id and item.document_id and item.evidence_id
            ]

        # Round-robin first provides per-paper representation; the final ordering is score-based.
        balanced: list[RetrievedEvidence] = []
        for index in range(per_paper):
            for paper_id in allowed:
                items = lists.get(paper_id, [])
                if index < len(items):
                    balanced.append(items[index])
        balanced.sort(key=lambda item: (-item.score, item.paper_id or "", item.evidence_id))
        return [item.model_copy(update={"rank": index}) for index, item in enumerate(balanced[:bounded], start=1)]
