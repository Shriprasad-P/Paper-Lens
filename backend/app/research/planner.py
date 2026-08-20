"""Research question planning with a deterministic no-credential fallback."""

from __future__ import annotations

import re

from pydantic import ValidationError

from ..ai.provider import AIProvider, AIProviderError
from ..core.config import Settings
from ..models.research import ResearchPlan


class ResearchPlanner:
    PROMPT_VERSION = "v1"
    SCHEMA_VERSION = "v1"

    def __init__(self, provider: AIProvider | None = None, *, settings: Settings | None = None) -> None:
        self.provider = provider
        self.settings = settings or Settings.from_env()

    async def plan(self, question: str, *, desired_paper_count: int = 5) -> ResearchPlan:
        original = question.strip()
        if not original:
            raise ValueError("A research question is required.")
        if self.provider is not None:
            try:
                prompt = (
                    "Create a bounded research plan. Preserve the exact research question. "
                    "Return only the requested schema; do not answer the question or invent papers.\n"
                    f"Research question: {original}\n"
                    f"Maximum search queries: {self.settings.research_max_search_queries}\n"
                    f"Desired paper count: {desired_paper_count}"
                )
                planned = await self.provider.generate_structured(prompt, ResearchPlan)
                return _bound_plan(planned, original, self.settings.research_max_search_queries, desired_paper_count)
            except (AIProviderError, ValidationError, ValueError, TypeError):
                pass
        return deterministic_plan(original, self.settings.research_max_search_queries, desired_paper_count)


def deterministic_plan(question: str, max_queries: int = 6, desired_paper_count: int = 5) -> ResearchPlan:
    tokens = [token for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", question.lower()) if token not in _STOPWORDS]
    concepts = list(dict.fromkeys(tokens))[:12]
    phrase = " ".join(concepts[:6]) or question.strip()
    query_candidates = [
        question.strip(),
        f"{phrase} methods",
        f"{phrase} survey",
        f"{phrase} evaluation",
        f"{phrase} benchmark",
        f"{phrase} detection approaches",
    ]
    queries = list(dict.fromkeys(item.strip() for item in query_candidates if item.strip()))[: max(3, min(max_queries, 8))]
    return ResearchPlan(
        research_question=question,
        search_queries=queries,
        concepts=concepts,
        inclusion_criteria=["Directly addresses at least one concept in the research question.", "Has a retrievable arXiv source when selected."],
        exclusion_criteria=["Duplicate versions of an already selected paper.", "Search metadata without a validated source paper."],
        desired_paper_count=max(1, min(desired_paper_count, 8)),
        rationale_summary="Queries cover the original question, methods, evaluation, and adjacent terminology without generating research conclusions.",
    )


def _bound_plan(plan: ResearchPlan, question: str, max_queries: int, desired_paper_count: int) -> ResearchPlan:
    queries = list(dict.fromkeys(item.strip() for item in plan.search_queries if item.strip()))[: max(3, min(max_queries, 8))]
    if len(queries) < 3:
        fallback = deterministic_plan(question, max_queries, desired_paper_count)
        queries = list(dict.fromkeys([*queries, *fallback.search_queries]))[: max(3, min(max_queries, 8))]
    return plan.model_copy(update={"research_question": question, "search_queries": queries, "desired_paper_count": max(1, min(plan.desired_paper_count, desired_paper_count, 8))})


_STOPWORDS = {
    "a", "an", "and", "are", "be", "does", "for", "how", "in", "is", "of", "on", "or", "the", "to", "what", "with",
}
