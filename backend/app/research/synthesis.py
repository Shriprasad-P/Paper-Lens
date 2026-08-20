"""Deterministic, source-only cross-paper report construction and validation."""

from __future__ import annotations

import re
from itertools import combinations
from typing import Iterable

from ..db.database import SQLDatabase
from ..models.document import PaperIR, ResearchClaim
from ..models.research import (
    ResearchClaimOrigin,
    ResearchContradiction,
    ResearchCoverage,
    ResearchEvidenceRef,
    ResearchGap,
    ResearchMethodSummary,
    ResearchPaperSummary,
    ResearchReportClaim,
    ResearchReportIR,
    ResearchTheme,
)
from .retrieval import CrossPaperEvidenceRetriever


class ResearchSynthesisError(Exception):
    """Expected failure while constructing a grounded report."""


class ResearchSynthesizer:
    def __init__(self, database: SQLDatabase, retriever: CrossPaperEvidenceRetriever) -> None:
        self.database = database
        self.retriever = retriever

    async def synthesize(
        self,
        question: str,
        paper_ids: list[str],
        *,
        queries: list[str] | None = None,
        coverage: ResearchCoverage | None = None,
        selected_candidates: list[object] | None = None,
    ) -> ResearchReportIR:
        allowed = list(dict.fromkeys(paper_ids))
        analyses: list[PaperIR] = []
        for paper_id in allowed:
            stored = self.database.get_analysis_record(paper_id)
            if stored is not None:
                analyses.append(stored[0])

        retrieved = await self.retriever.retrieve_async(question, allowed, limit=12) if allowed else []
        refs_by_paper: dict[str, list[ResearchEvidenceRef]] = {}
        for item in retrieved:
            if item.paper_id and item.document_id:
                refs_by_paper.setdefault(item.paper_id, []).append(
                    ResearchEvidenceRef(paper_id=item.paper_id, document_id=item.document_id, evidence_id=item.evidence_id)
                )

        executive: list[ResearchReportClaim] = []
        methods: list[ResearchMethodSummary] = []
        themes: list[ResearchTheme] = []
        limitations: list[ResearchReportClaim] = []
        future: list[ResearchReportClaim] = []
        all_results: list[tuple[PaperIR, object]] = []
        for paper in analyses:
            paper_refs = refs_by_paper.get(paper.paper_id, [])
            if paper.problem:
                claim = self._claim_from_local(paper, paper.problem, "problem")
                if claim:
                    executive.append(claim)
            for contribution in paper.contributions[:2]:
                claim = self._claim_from_local(paper, contribution, "contribution")
                if claim:
                    executive.append(claim)
            if paper.method:
                refs = self._refs(paper.paper_id, paper.document_id, paper.method.evidence_ids)
                if refs:
                    methods.append(ResearchMethodSummary(paper_id=paper.paper_id, method=paper.method.summary, evidence_refs=refs))
            for result in paper.results:
                all_results.append((paper, result))
            for item in paper.limitations[:3]:
                claim = self._claim_from_local(paper, item, "limitation")
                if claim:
                    limitations.append(claim)
            for item in paper.future_work[:3]:
                claim = self._claim_from_local(paper, item, "future")
                if claim:
                    future.append(claim)
            if paper_refs:
                themes.append(ResearchTheme(name=_theme_name(paper), summary=f"Evidence from {paper.metadata.title}.", claims=[*executive[-1:]]))

        agreements = self._agreements(all_results)
        contradictions = self._contradictions(all_results)
        gaps = self._gaps(analyses, limitations)
        report_coverage = coverage or ResearchCoverage(
            sufficient=bool(analyses and retrieved),
            relevant_paper_ids=[paper.paper_id for paper in analyses],
            evidence_count=len(retrieved),
            summary="Coverage is based on persisted analyses and registry evidence.",
        )
        summaries = [self._paper_summary(paper, selected_candidates or []) for paper in analyses]
        analyzed_ids = {paper.paper_id for paper in analyses}
        for paper_id in allowed:
            if paper_id in analyzed_ids:
                continue
            ingested = self.database.get_by_id(paper_id)
            if ingested is not None:
                summaries.append(ResearchPaperSummary(
                    paper_id=ingested.id,
                    title=ingested.metadata.title,
                    authors=ingested.metadata.authors,
                    year=ingested.metadata.published_at.year if ingested.metadata.published_at else None,
                    why_selected="Selected by the bounded relevance and diversity ranker.",
                    ingestion_status=ingested.status,
                    analysis_status="UNAVAILABLE",
                    verification_status="UNVERIFIED",
                ))
        return ResearchReportIR(
            research_question=question,
            executive_summary=executive[:12],
            themes=themes[:12],
            methods=methods[:12],
            agreements=agreements[:12],
            contradictions=contradictions[:12],
            research_gaps=gaps[:12],
            limitations=limitations[:12],
            future_directions=future[:12],
            papers=summaries,
            coverage=report_coverage,
            discovery_queries=list(dict.fromkeys(queries or []))[:8],
            candidate_count=len(selected_candidates or []),
            selected_count=len(allowed),
        )

    def _claim_from_local(self, paper: PaperIR, item: ResearchClaim, label: str) -> ResearchReportClaim | None:
        refs = self._refs(paper.paper_id, paper.document_id, item.evidence_ids)
        if not refs:
            return None
        return ResearchReportClaim(
            claim_id=f"{paper.paper_id}:{label}:{item.id}",
            statement=item.statement,
            source_papers=[paper.paper_id],
            evidence_refs=refs,
            origin=ResearchClaimOrigin.AUTHOR_EXPLICIT,
        )

    def _refs(self, paper_id: str, document_id: str, evidence_ids: Iterable[str]) -> list[ResearchEvidenceRef]:
        ids = list(dict.fromkeys(evidence_ids))
        existing = self.database.get_evidence_many(paper_id, ids)
        return [ResearchEvidenceRef(paper_id=paper_id, document_id=document_id, evidence_id=evidence_id) for evidence_id in ids if evidence_id in existing]

    def _agreements(self, results: list[tuple[PaperIR, object]]) -> list[ResearchReportClaim]:
        groups: dict[str, list[tuple[PaperIR, object]]] = {}
        for paper, result in results:
            metric = str(getattr(result, "metric", "") or "").strip().lower()
            if metric and getattr(result, "value", None) is not None:
                groups.setdefault(metric, []).append((paper, result))
        output: list[ResearchReportClaim] = []
        for metric, items in groups.items():
            values = {str(getattr(item, "value", "")) for _, item in items}
            if len(items) >= 2 and len(values) == 1:
                refs = [ref for paper, item in items for ref in self._refs(paper.paper_id, paper.document_id, getattr(item, "evidence_ids", []))]
                if refs:
                    output.append(ResearchReportClaim(
                        claim_id=f"agreement:{metric}",
                        statement=f"Across the selected papers, the reported {metric} value is {next(iter(values))}.",
                        source_papers=list(dict.fromkeys(paper.paper_id for paper, _ in items)),
                        evidence_refs=refs,
                        origin=ResearchClaimOrigin.CROSS_PAPER_INFERRED,
                    ))
        return output

    def _contradictions(self, results: list[tuple[PaperIR, object]]) -> list[ResearchContradiction]:
        output: list[ResearchContradiction] = []
        for (paper_a, result_a), (paper_b, result_b) in combinations(results, 2):
            metric_a = str(getattr(result_a, "metric", "") or "").strip().lower()
            metric_b = str(getattr(result_b, "metric", "") or "").strip().lower()
            if not metric_a or metric_a != metric_b or paper_a.paper_id == paper_b.paper_id:
                continue
            if not _comparable_context(paper_a, paper_b):
                continue
            direction_a = _direction(getattr(result_a, "statement", ""))
            direction_b = _direction(getattr(result_b, "statement", ""))
            if not direction_a or not direction_b or direction_a == direction_b:
                continue
            refs_a = self._refs(paper_a.paper_id, paper_a.document_id, getattr(result_a, "evidence_ids", []))
            refs_b = self._refs(paper_b.paper_id, paper_b.document_id, getattr(result_b, "evidence_ids", []))
            if refs_a and refs_b:
                output.append(ResearchContradiction(
                    id=f"contradiction:{paper_a.paper_id}:{paper_b.paper_id}:{metric_a}",
                    topic=metric_a,
                    claim_a=getattr(result_a, "statement", ""),
                    evidence_a=refs_a,
                    claim_b=getattr(result_b, "statement", ""),
                    evidence_b=refs_b,
                    contradiction_type="RESULT_DIVERGENCE",
                    explanation="The selected papers report opposite directions for the same metric in comparable context; this is unverified.",
                ))
        return output

    def _gaps(self, analyses: list[PaperIR], limitations: list[ResearchReportClaim]) -> list[ResearchGap]:
        if len(analyses) < 2 or not limitations:
            return []
        refs = [ref for claim in limitations[:4] for ref in claim.evidence_refs]
        return [ResearchGap(
            id="gap:selected-literature-limitations",
            statement="Selected literature provides limited evidence for the limitations identified by the included authors; this is not evidence that no work exists.",
            evidence_refs=refs,
            origin=ResearchClaimOrigin.CROSS_PAPER_INFERRED,
        )]

    def _paper_summary(self, paper: PaperIR, candidates: list[object]) -> ResearchPaperSummary:
        candidate = next((item for item in candidates if getattr(item, "paper_id", None) == paper.paper_id), None)
        analysis_status = "COMPLETED" if paper.extraction and any(getattr(state, "status", "") == "COMPLETED" for state in paper.extraction.values()) else "PARTIAL"
        return ResearchPaperSummary(
            paper_id=paper.paper_id,
            title=paper.metadata.title,
            authors=paper.metadata.authors,
            year=paper.metadata.published_at.year if paper.metadata.published_at else None,
            why_selected="Ranked as relevant to the research question." if candidate is None else "Selected by the bounded relevance and diversity ranker.",
            ingestion_status="COMPLETED",
            analysis_status=analysis_status,
            verification_status="UNVERIFIED",
        )


def validate_research_report(report: ResearchReportIR, database: SQLDatabase, allowed_paper_ids: set[str]) -> None:
    """Reject citations that do not resolve to the exact persisted evidence tuple."""

    claims = [*report.executive_summary, *report.agreements, *report.limitations, *report.future_directions]
    claims.extend(theme_claim for theme in report.themes for theme_claim in theme.claims)
    claims.extend(ResearchReportClaim(
        claim_id=f"method:{item.paper_id}", statement=item.method, source_papers=[item.paper_id], evidence_refs=item.evidence_refs, origin=ResearchClaimOrigin.AUTHOR_EXPLICIT
    ) for item in report.methods)
    for contradiction in report.contradictions:
        claims.extend([
            ResearchReportClaim(claim_id=contradiction.id + ":a", statement=contradiction.claim_a, evidence_refs=contradiction.evidence_a, source_papers=[ref.paper_id for ref in contradiction.evidence_a], origin=ResearchClaimOrigin.AUTHOR_EXPLICIT),
            ResearchReportClaim(claim_id=contradiction.id + ":b", statement=contradiction.claim_b, evidence_refs=contradiction.evidence_b, source_papers=[ref.paper_id for ref in contradiction.evidence_b], origin=ResearchClaimOrigin.AUTHOR_EXPLICIT),
        ])
    claims.extend(ResearchReportClaim(claim_id=gap.id, statement=gap.statement, evidence_refs=gap.evidence_refs, source_papers=[ref.paper_id for ref in gap.evidence_refs], origin=gap.origin) for gap in report.research_gaps)
    for claim in claims:
        if any(paper_id not in allowed_paper_ids for paper_id in claim.source_papers):
            raise ResearchSynthesisError("Research report names a paper outside the selected set.")
        for ref in claim.evidence_refs:
            if ref.paper_id not in allowed_paper_ids:
                raise ResearchSynthesisError("Research report cites a paper outside the selected set.")
            document = database.get_document(ref.paper_id)
            if document is None or document.id != ref.document_id:
                raise ResearchSynthesisError("Research report cites a mismatched document.")
            evidence = database.get_evidence(ref.paper_id, ref.evidence_id)
            if evidence is None or evidence.document_id != ref.document_id or evidence.paper_id != ref.paper_id:
                raise ResearchSynthesisError("Research report cites missing or mismatched evidence.")
            if _numeric_tokens(claim.statement) and not any(token in _numeric_tokens(evidence.source_text) for token in _numeric_tokens(claim.statement)):
                raise ResearchSynthesisError("Research report contains a numeric claim not present in its source evidence.")
    if any(item.paper_id not in allowed_paper_ids for item in report.papers):
        raise ResearchSynthesisError("Research report contains an unselected paper summary.")


def _theme_name(paper: PaperIR) -> str:
    return (paper.method.summary[:80] if paper.method else "Evidence-grounded findings").strip() or "Evidence-grounded findings"


def _direction(statement: str) -> str | None:
    text = statement.lower()
    if re.search(r"\b(worse|lower|decreases?|declines?|underperform)\b", text):
        return "negative"
    if re.search(r"\b(better|higher|improves?|increases?|outperform)\b", text):
        return "positive"
    return None


def _comparable_context(left: PaperIR, right: PaperIR) -> bool:
    left_datasets = {dataset.strip().lower() for experiment in left.experiments for dataset in experiment.datasets if dataset.strip()}
    right_datasets = {dataset.strip().lower() for experiment in right.experiments for dataset in experiment.datasets if dataset.strip()}
    if left_datasets and right_datasets and not (left_datasets & right_datasets):
        return False
    left_text = f"{left.metadata.title} {left.metadata.abstract or ''}".lower()
    right_text = f"{right.metadata.title} {right.metadata.abstract or ''}".lower()
    left_tokens = {token for token in re.findall(r"[a-z0-9-]+", left_text) if len(token) >= 5}
    right_tokens = {token for token in re.findall(r"[a-z0-9-]+", right_text) if len(token) >= 5}
    return bool(left_tokens & right_tokens)


def _numeric_tokens(value: str) -> set[str]:
    return set(re.findall(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?%?", value))


# Short compatibility alias for callers that use the generic validator name.
validate_report = validate_research_report
