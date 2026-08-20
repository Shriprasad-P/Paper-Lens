"""Create renderer-neutral visualization specs without runtime AI calls."""

from __future__ import annotations

from numbers import Number

from ..models.document import PaperIR
from ..models.reader import VisualizationSpec, VisualizationType


def plan_visualizations(analysis: PaperIR | None) -> list[VisualizationSpec]:
    if analysis is None:
        return []

    specs: list[VisualizationSpec] = []
    if analysis.method is not None and analysis.method.steps:
        evidence_ids = sorted(
            {
                evidence_id
                for step in analysis.method.steps
                for evidence_id in step.evidence_ids
            }
            | set(analysis.method.evidence_ids)
        )
        specs.append(
            VisualizationSpec(
                id="method-flow",
                type=VisualizationType.METHOD_FLOW,
                title="Method flow",
                data={
                    "nodes": [
                        {
                            "id": step.id,
                            "label": step.label,
                            "description": step.description,
                            "order": step.order,
                            "evidence_ids": step.evidence_ids,
                            "origin": step.origin.value,
                        }
                        for step in analysis.method.steps
                    ],
                    "edges": [
                        {
                            "source": relation.source_step_id,
                            "target": relation.target_step_id,
                            "relationship": relation.relationship,
                        }
                        for relation in analysis.method.relations
                    ],
                },
                evidence_ids=evidence_ids,
            )
        )

    if not analysis.results:
        return specs

    numeric_results = [
        result
        for result in analysis.results
        if isinstance(result.value, Number) and not isinstance(result.value, bool)
    ]
    if len(numeric_results) >= 2 and all(result.metric for result in numeric_results):
        metric = numeric_results[0].metric
        if all(result.metric == metric for result in numeric_results):
            specs.append(
                VisualizationSpec(
                    id="results-bar-chart",
                    type=VisualizationType.BAR_CHART,
                    title=f"{metric} comparison",
                    data={
                        "metric": metric,
                        "rows": [
                            {
                                "label": result.comparison_target or result.id,
                                "value": result.value,
                                "unit": result.unit,
                            }
                            for result in numeric_results
                        ],
                    },
                    evidence_ids=sorted(
                        {evidence_id for result in numeric_results for evidence_id in result.evidence_ids}
                    ),
                )
            )
            return specs

    if len(numeric_results) == 1 and len(numeric_results) == len(analysis.results):
        result = numeric_results[0]
        specs.append(
            VisualizationSpec(
                id="result-metric",
                type=VisualizationType.METRIC,
                title=result.metric or "Main result",
                data={"value": result.value, "unit": result.unit, "statement": result.statement},
                evidence_ids=list(result.evidence_ids),
            )
        )
        return specs

    specs.append(
        VisualizationSpec(
            id="results-table",
            type=VisualizationType.TABLE,
            title="Reported results",
            data={
                "rows": [
                    {
                        "statement": result.statement,
                        "metric": result.metric,
                        "value": result.value,
                        "unit": result.unit,
                        "comparison_target": result.comparison_target,
                    }
                    for result in analysis.results
                ]
            },
            evidence_ids=sorted(
                {evidence_id for result in analysis.results for evidence_id in result.evidence_ids}
            ),
        )
    )
    return specs
