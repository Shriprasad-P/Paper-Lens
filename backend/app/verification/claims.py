"""Stable, focused claim views used by the verification boundary."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..models.document import PaperIR, StatementOrigin


class VerifiableClaim(BaseModel):
    """A claim plus only the context needed to verify that claim."""

    model_config = ConfigDict(extra="forbid")

    paper_id: str
    document_id: str
    document_hash: str | None = None
    claim_id: str
    kind: str
    statement: str = Field(min_length=1)
    origin: StatementOrigin
    evidence_ids: list[str] = Field(default_factory=list)
    structured: dict[str, Any] = Field(default_factory=dict)


def collect_verifiable_claims(analysis: PaperIR) -> list[VerifiableClaim]:
    """Collect semantic claims without changing the persisted PaperIR."""

    claims: list[VerifiableClaim] = []

    def add(
        *,
        claim_id: str,
        kind: str,
        statement: str,
        origin: StatementOrigin,
        evidence_ids: list[str],
        structured: dict[str, Any] | None = None,
    ) -> None:
        if statement.strip() and evidence_ids:
            claims.append(
                VerifiableClaim(
                    paper_id=analysis.paper_id,
                    document_id=analysis.document_id,
                    document_hash=analysis.document_hash,
                    claim_id=claim_id,
                    kind=kind,
                    statement=statement.strip(),
                    origin=origin,
                    evidence_ids=list(evidence_ids),
                    structured=structured or {},
                )
            )

    if analysis.problem:
        add(
            claim_id=analysis.problem.id,
            kind="problem",
            statement=analysis.problem.statement,
            origin=analysis.problem.origin,
            evidence_ids=analysis.problem.evidence_ids,
            structured={"context": analysis.problem.context} if analysis.problem.context else {},
        )
    if analysis.motivation:
        add(
            claim_id=analysis.motivation.id,
            kind="motivation",
            statement=analysis.motivation.statement,
            origin=analysis.motivation.origin,
            evidence_ids=analysis.motivation.evidence_ids,
        )
    for kind, items in (
        ("research_gap", analysis.research_gap),
        ("contribution", analysis.contributions),
        ("limitation", analysis.limitations),
        ("future_work", analysis.future_work),
    ):
        for item in items:
            add(
                claim_id=item.id,
                kind=kind,
                statement=item.statement,
                origin=item.origin,
                evidence_ids=item.evidence_ids,
            )

    if analysis.method:
        add(
            claim_id="method_001",
            kind="method_summary",
            statement=analysis.method.summary,
            origin=analysis.method.origin,
            evidence_ids=analysis.method.evidence_ids,
        )
        for step in analysis.method.steps:
            add(
                claim_id=step.id,
                kind="method_step",
                statement=f"{step.label}: {step.description}",
                origin=step.origin,
                evidence_ids=step.evidence_ids,
                structured={"label": step.label, "order": step.order},
            )

    for equation in analysis.equations:
        interpretation = equation.explanation or equation.interpretation or equation.role
        if interpretation or any(variable.meaning for variable in equation.variables):
            details = [f"Expression: {equation.expression}"]
            if interpretation:
                details.append(f"Interpretation: {interpretation}")
            meanings = [
                f"{variable.symbol}: {variable.meaning}"
                for variable in equation.variables
                if variable.meaning
            ]
            if meanings:
                details.append("Variables: " + "; ".join(meanings))
            add(
                claim_id=equation.id,
                kind="equation_interpretation",
                statement=" ".join(details),
                origin=equation.origin,
                evidence_ids=equation.evidence_ids,
            )

    for experiment in analysis.experiments:
        fields = [
            f"Datasets: {', '.join(experiment.datasets)}" if experiment.datasets else None,
            f"Models: {', '.join(experiment.models)}" if experiment.models else None,
            f"Baselines: {', '.join(experiment.baselines)}" if experiment.baselines else None,
            f"Metrics: {', '.join(experiment.metrics)}" if experiment.metrics else None,
            f"Setup: {experiment.setup}" if experiment.setup else None,
        ]
        if any(fields):
            add(
                claim_id=experiment.id,
                kind="experiment",
                statement="; ".join(item for item in fields if item),
                origin=experiment.origin,
                evidence_ids=experiment.evidence_ids,
            )

    for result in analysis.results:
        add(
            claim_id=result.id,
            kind="result",
            statement=result.statement,
            origin=result.origin,
            evidence_ids=result.evidence_ids,
            structured={
                "metric": result.metric,
                "value": result.value,
                "unit": result.unit,
                "comparison_target": result.comparison_target,
            },
        )

    return claims
