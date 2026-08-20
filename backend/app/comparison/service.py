"""Align persisted PaperIR fields without merging papers or inventing claims."""

from __future__ import annotations

from ..db.database import SQLDatabase
from ..models.document import PaperIR
from ..models.research import Comparability, ComparisonDimension, ComparisonEntry, PaperComparisonIR


class ComparisonError(Exception):
    pass


class PaperComparisonService:
    DIMENSIONS = ("Problem", "Research Gap", "Contributions", "Method", "Datasets", "Baselines", "Metrics", "Results", "Limitations", "Future Work")

    def __init__(self, database: SQLDatabase) -> None:
        self.database = database

    def compare(self, paper_ids: list[str]) -> PaperComparisonIR:
        ids = list(dict.fromkeys(paper_ids))
        if len(ids) < 2 or len(ids) > 5:
            raise ComparisonError("Select between two and five papers.")
        analyses: dict[str, PaperIR] = {}
        for paper_id in ids:
            analysis = self.database.get_analysis_record(paper_id)
            if analysis is None:
                raise ComparisonError(f"Paper {paper_id} has no persisted analysis.")
            analyses[paper_id] = analysis[0]
        dimensions = [self._dimension(name, analyses) for name in self.DIMENSIONS]
        return PaperComparisonIR(paper_ids=ids, dimensions=dimensions)

    def _dimension(self, name: str, analyses: dict[str, PaperIR]) -> ComparisonDimension:
        entries = [self._entry(name, analysis) for analysis in analyses.values()]
        comparability = None
        note = None
        if name in {"Datasets", "Metrics", "Results"}:
            comparability, note = self._comparability(name, entries)
        return ComparisonDimension(name=name, entries=entries, comparability=comparability, note=note)

    def _entry(self, name: str, analysis: PaperIR) -> ComparisonEntry:
        if name == "Problem":
            return _claim_entry(analysis.paper_id, analysis.document_id, analysis.problem)
        if name == "Research Gap":
            return _claims_entry(analysis.paper_id, analysis.document_id, analysis.research_gap)
        if name == "Contributions":
            return _claims_entry(analysis.paper_id, analysis.document_id, analysis.contributions)
        if name == "Method":
            if analysis.method is None:
                return ComparisonEntry(paper_id=analysis.paper_id, document_id=analysis.document_id)
            return ComparisonEntry(paper_id=analysis.paper_id, document_id=analysis.document_id, statement=analysis.method.summary, evidence_ids=analysis.method.evidence_ids)
        if name == "Datasets":
            return ComparisonEntry(paper_id=analysis.paper_id, document_id=analysis.document_id, values=_experiment_values(analysis, "datasets"), evidence_ids=_experiment_evidence(analysis))
        if name == "Baselines":
            return ComparisonEntry(paper_id=analysis.paper_id, document_id=analysis.document_id, values=_experiment_values(analysis, "baselines"), evidence_ids=_experiment_evidence(analysis))
        if name == "Metrics":
            return ComparisonEntry(paper_id=analysis.paper_id, document_id=analysis.document_id, values=_experiment_values(analysis, "metrics"), evidence_ids=_experiment_evidence(analysis))
        if name == "Results":
            return ComparisonEntry(paper_id=analysis.paper_id, document_id=analysis.document_id, values=[item.statement for item in analysis.results], evidence_ids=_unique(item.evidence_ids for item in analysis.results))
        if name == "Limitations":
            return _claims_entry(analysis.paper_id, analysis.document_id, analysis.limitations)
        if name == "Future Work":
            return _claims_entry(analysis.paper_id, analysis.document_id, analysis.future_work)
        return ComparisonEntry(paper_id=analysis.paper_id, document_id=analysis.document_id)

    @staticmethod
    def _comparability(name: str, entries: list[ComparisonEntry]) -> tuple[Comparability, str]:
        value_sets = [set(entry.values) for entry in entries if entry.values]
        if len(value_sets) < 2:
            return Comparability.PARTIALLY_COMPARABLE, f"{name} context is incomplete for at least one paper; no ranking is produced."
        if name == "Results":
            return Comparability.PARTIALLY_COMPARABLE, "Results retain paper-specific context; numerical ranking is disabled unless metric and dataset semantics match."
        if len(set(map(tuple, value_sets))) == 1:
            return Comparability.COMPARABLE, "The structured values match across selected papers."
        return Comparability.NOT_COMPARABLE, "Different structured values do not establish that one paper is better."


def _claim_entry(paper_id: str, document_id: str, claim: object | None) -> ComparisonEntry:
    if claim is None:
        return ComparisonEntry(paper_id=paper_id, document_id=document_id)
    return ComparisonEntry(paper_id=paper_id, document_id=document_id, statement=claim.statement, evidence_ids=list(claim.evidence_ids))


def _claims_entry(paper_id: str, document_id: str, claims: list[object]) -> ComparisonEntry:
    statements = [claim.statement for claim in claims]
    return ComparisonEntry(paper_id=paper_id, document_id=document_id, values=statements, evidence_ids=_unique(claim.evidence_ids for claim in claims))


def _experiment_values(analysis: PaperIR, field: str) -> list[str]:
    return _unique(getattr(experiment, field) for experiment in analysis.experiments)


def _experiment_evidence(analysis: PaperIR) -> list[str]:
    return _unique(experiment.evidence_ids for experiment in analysis.experiments)


def _unique(groups: object) -> list[str]:
    values: list[str] = []
    for group in groups:
        if isinstance(group, str):
            items = [group]
        else:
            items = list(group)
        for item in items:
            if item and item not in values:
                values.append(item)
    return values
