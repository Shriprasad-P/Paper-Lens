"""Deterministic candidate normalization, deduplication, ranking, and selection."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from ..db.database import SQLDatabase
from ..models.research import PaperCandidate
from .discovery import normalize_candidate, normalize_title


def deduplicate_candidates(candidates: list[PaperCandidate]) -> list[PaperCandidate]:
    result: list[PaperCandidate] = []
    by_arxiv: dict[str, int] = {}
    by_doi: dict[str, int] = {}
    by_title: dict[str, int] = {}
    for raw in candidates:
        candidate = normalize_candidate(raw)
        duplicate_index = None
        if candidate.arxiv_id:
            duplicate_index = by_arxiv.get(candidate.arxiv_id)
        if duplicate_index is None and candidate.doi:
            duplicate_index = by_doi.get(candidate.doi)
        title_key = normalize_title(candidate.title)
        if duplicate_index is None:
            duplicate_index = by_title.get(title_key)
        if duplicate_index is None:
            for index, existing in enumerate(result):
                if SequenceMatcher(None, title_key, normalize_title(existing.title)).ratio() >= 0.96:
                    duplicate_index = index
                    break
        if duplicate_index is None:
            duplicate_index = len(result)
            result.append(candidate)
        else:
            existing = result[duplicate_index]
            if candidate.discovery_rank < existing.discovery_rank:
                result[duplicate_index] = candidate
                candidate = result[duplicate_index]
        if candidate.arxiv_id:
            by_arxiv[candidate.arxiv_id] = duplicate_index
        if candidate.doi:
            by_doi[candidate.doi] = duplicate_index
        by_title[title_key] = duplicate_index
    return result


class CandidateRanker:
    def __init__(self, database: SQLDatabase | None = None) -> None:
        self.database = database

    def rank(self, question: str, candidates: list[PaperCandidate], *, limit: int = 30) -> list[PaperCandidate]:
        question_tokens = _tokens(question)
        ranked: list[PaperCandidate] = []
        existing_arxiv = {paper.metadata.arxiv_id.split("v", 1)[0] for paper in self.database.list_papers()} if self.database else set()
        for candidate in candidates:
            title_tokens = _tokens(candidate.title)
            abstract_tokens = _tokens(candidate.abstract or "")
            overlap = len(question_tokens & title_tokens) / max(len(question_tokens), 1)
            abstract_overlap = len(question_tokens & abstract_tokens) / max(len(question_tokens), 1)
            concept_bonus = 0.15 if any(token in title_tokens for token in question_tokens) else 0.0
            existing_bonus = 0.10 if candidate.arxiv_id in existing_arxiv else 0.0
            score = round(overlap * 0.65 + abstract_overlap * 0.25 + concept_bonus + existing_bonus + 1 / max(candidate.discovery_rank, 1) * 0.05, 6)
            ranked.append(candidate.model_copy(update={"ranking_score": score}))
        ranked.sort(key=lambda item: (-float(item.ranking_score or 0), item.discovery_rank, item.candidate_id))
        return ranked[: max(1, min(limit, 30))]


def select_candidates(ranked: list[PaperCandidate], max_candidates: int, max_ingested: int) -> list[PaperCandidate]:
    selected: list[PaperCandidate] = []
    seen_years: set[int] = set()
    for candidate in ranked[: max(1, min(max_candidates, 30))]:
        if len(selected) >= max_ingested:
            break
        # Prefer a modest amount of year diversity without overriding relevance.
        if candidate.year is not None and candidate.year in seen_years and len(selected) + 1 < max_ingested:
            continue
        selected.append(candidate.model_copy(update={"selected": True, "ingestion_status": "QUEUED"}))
        if candidate.year is not None:
            seen_years.add(candidate.year)
    if len(selected) < min(max_ingested, len(ranked)):
        for candidate in ranked:
            if len(selected) >= max_ingested or any(item.candidate_id == candidate.candidate_id for item in selected):
                continue
            selected.append(candidate.model_copy(update={"selected": True, "ingestion_status": "QUEUED"}))
    return selected


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9][a-z0-9_-]*", value.lower()) if token not in {"the", "and", "for", "with", "from", "how", "what", "are"}}
