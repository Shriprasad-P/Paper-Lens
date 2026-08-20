"""Deterministic retrieval evaluation metrics for fixture and live smoke sets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class RetrievalCase:
    question: str
    relevant_evidence_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class RetrievalMetrics:
    recall_at_k: float
    mrr: float
    hit_at_k: float


def evaluate_retriever(cases: list[RetrievalCase], retrieve: Callable[[str, int], list[str]], *, k: int = 5) -> RetrievalMetrics:
    if not cases:
        return RetrievalMetrics(0.0, 0.0, 0.0)
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    hits: list[float] = []
    for case in cases:
        ranked = retrieve(case.question, k)[:k]
        relevant = case.relevant_evidence_ids
        recalls.append(len(set(ranked) & relevant) / max(len(relevant), 1))
        first = next((index for index, evidence_id in enumerate(ranked, start=1) if evidence_id in relevant), None)
        reciprocal_ranks.append(1.0 / first if first else 0.0)
        hits.append(1.0 if first else 0.0)
    return RetrievalMetrics(sum(recalls) / len(recalls), sum(reciprocal_ranks) / len(reciprocal_ranks), sum(hits) / len(hits))
