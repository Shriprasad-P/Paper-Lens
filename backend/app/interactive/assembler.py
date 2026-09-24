"""Deterministic InteractivePaper assembly from StructuredDocument + PaperIR."""

from __future__ import annotations

import hashlib
import re

from ..models.document import PaperIR, PaperTable, StatementOrigin, StructuredDocument
from ..models.interactive_paper import (
    BlockStatus,
    BlockType,
    DiagramType,
    EquationExplanation,
    EquationTerm,
    FigureBinding,
    GenerationMode,
    InteractivePaper,
    InteractivePaperBlock,
    INTERACTIVE_PROMPT_VERSION,
    INTERACTIVE_SCHEMA_VERSION,
    OutlineItem,
    ProvenanceKind,
    TableBinding,
    ValidatorStatus,
    VisualDiagram,
    VisualEdge,
    VisualNode,
)
from .validator import validate_paper
from ..visualization.archify import ARCHIFY_COMMIT, ARCHIFY_VERSION, ArchifyAdapterError, paper_visual_graph, to_archify_ir

_IMPORTANT_TABLE = re.compile(
    r"ablat|baseline|dataset|compar|result|accuracy|f1|bleu|auc|performance|benchmark",
    re.I,
)


def analysis_fingerprint(analysis: PaperIR | None) -> str:
    if analysis is None:
        return "none"
    payload = analysis.model_dump_json(exclude={"extraction"})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def interactive_cache_key(
    *,
    owner_id: str,
    paper_id: str,
    document_hash: str | None,
    source_hash: str | None,
    analysis_fingerprint_value: str,
    schema_version: str,
    prompt_version: str,
    provider: str | None,
    model: str | None,
    generation_mode: GenerationMode,
    embedding_model: str | None = None,
    visual_adapter_version: str = f"archify-{ARCHIFY_VERSION}@{ARCHIFY_COMMIT}",
) -> str:
    parts = [
        owner_id,
        paper_id,
        document_hash or "",
        source_hash or "",
        analysis_fingerprint_value,
        schema_version,
        prompt_version,
        provider or "",
        model or "",
        embedding_model or "",
        visual_adapter_version,
        generation_mode.value,
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def assemble_interactive_paper(
    document: StructuredDocument,
    analysis: PaperIR | None,
    *,
    available_ids: set[str],
    cache_key: str,
    provider: str | None,
    model: str | None,
    generation_mode: GenerationMode = GenerationMode.ASSEMBLER,
) -> InteractivePaper:
    blocks: list[InteractivePaperBlock] = []
    blocks.extend(_overview_blocks(document, analysis))
    if analysis and analysis.problem:
        blocks.append(
            _claim_block(
                "block_problem",
                BlockType.PROBLEM,
                "Problem",
                analysis.problem.statement,
                analysis.problem.evidence_ids,
                inferred=analysis.problem.origin == StatementOrigin.MODEL_INFERRED,
                extra=analysis.problem.context,
            )
        )
    if analysis and analysis.motivation:
        blocks.append(
            _claim_block(
                "block_motivation",
                BlockType.MOTIVATION,
                "Why this problem matters",
                analysis.motivation.statement,
                analysis.motivation.evidence_ids,
                inferred=analysis.motivation.origin == StatementOrigin.MODEL_INFERRED,
            )
        )
    if analysis and analysis.research_gap:
        statement = " ".join(item.statement for item in analysis.research_gap)
        evidence = _unique(eid for item in analysis.research_gap for eid in item.evidence_ids)
        blocks.append(
            _claim_block(
                "block_gap",
                BlockType.MOTIVATION,
                "Why existing approaches struggle",
                statement,
                evidence,
                inferred=any(item.origin == StatementOrigin.MODEL_INFERRED for item in analysis.research_gap),
            )
        )
    if analysis and analysis.method:
        blocks.append(_method_block(analysis, document))
    if analysis and analysis.equations:
        method_ids = {eq.id for eq in (blocks[-1].equations if blocks and blocks[-1].type == BlockType.METHOD else [])}
        leftover = [item for item in analysis.equations if item.id not in method_ids]
        if leftover:
            blocks.append(_equation_block(leftover, document))
    elif document.equations and not (analysis and analysis.equations):
        blocks.append(_source_equation_block(document))
    if analysis and analysis.experiments:
        blocks.append(_experiment_block(analysis, document))
    if analysis and analysis.results:
        blocks.append(_result_block(analysis, document))
    important_tables = _important_tables(document)
    used_table_ids = {binding.table_id for block in blocks for binding in block.tables}
    leftover_tables = [table for table in important_tables if table.id not in used_table_ids]
    if leftover_tables:
        blocks.append(_table_block(leftover_tables))
    used_figure_ids = {binding.figure_id for block in blocks for binding in block.figures}
    leftover_figures = [
        figure
        for figure in document.figures
        if figure.id not in used_figure_ids and (figure.caption or figure.image_reference)
    ][:4]
    if leftover_figures:
        blocks.append(
            InteractivePaperBlock(
                id="block_figures",
                type=BlockType.FIGURE_EXPLANATION,
                title="Figures from the paper",
                simplified_explanation="Original figures retained from the source PDF.",
                figures=[
                    FigureBinding(
                        figure_id=figure.id,
                        simplified_explanation=figure.caption,
                        evidence_ids=figure.evidence_ids,
                    )
                    for figure in leftover_figures
                ],
                evidence_ids=_unique(eid for figure in leftover_figures for eid in figure.evidence_ids),
                status=BlockStatus.READY,
                validator_status=ValidatorStatus.PASSED,
            )
        )
    if analysis and analysis.limitations:
        statement = " ".join(item.statement for item in analysis.limitations)
        evidence = _unique(eid for item in analysis.limitations for eid in item.evidence_ids)
        blocks.append(
            _claim_block(
                "block_limitations",
                BlockType.LIMITATION,
                "Limitations",
                statement,
                evidence,
                inferred=any(item.origin == StatementOrigin.MODEL_INFERRED for item in analysis.limitations),
            )
        )
    if analysis and analysis.future_work:
        statement = " ".join(item.statement for item in analysis.future_work)
        evidence = _unique(eid for item in analysis.future_work for eid in item.evidence_ids)
        blocks.append(
            _claim_block(
                "block_takeaways",
                BlockType.CONCLUSION,
                "Key takeaway",
                statement,
                evidence,
                inferred=any(item.origin == StatementOrigin.MODEL_INFERRED for item in analysis.future_work),
            )
        )
    paper = InteractivePaper(
        paper_id=document.paper_id,
        document_id=document.id,
        source_hash=document.source_hash,
        document_hash=document.document_hash,
        analysis_fingerprint=analysis_fingerprint(analysis),
        generation_mode=generation_mode,
        generation_config={
            "schema_version": INTERACTIVE_SCHEMA_VERSION,
            "prompt_version": INTERACTIVE_PROMPT_VERSION,
            "provider": provider,
            "model": model,
        },
        cache_key=cache_key,
        provider=provider,
        model=model,
        status=BlockStatus.READY,
        overview=next((block.simplified_explanation for block in blocks if block.type == BlockType.OVERVIEW), None),
        blocks=blocks,
        outline=[OutlineItem(block_id=block.id, title=block.title, type=block.type) for block in blocks],
        concepts=_concepts(analysis),
    )
    return validate_paper(
        paper,
        available_ids=available_ids,
        figure_ids={figure.id for figure in document.figures},
        table_ids={table.id for table in document.tables},
    )


def _overview_blocks(document: StructuredDocument, analysis: PaperIR | None) -> list[InteractivePaperBlock]:
    abstract = document.metadata.abstract
    evidence: list[str] = []
    if document.sections:
        evidence = _unique(
            paragraph.evidence_id
            for paragraph in document.sections[0].paragraphs
            if paragraph.evidence_id
        )
    contributions = ""
    if analysis and analysis.contributions:
        contributions = " ".join(item.statement for item in analysis.contributions)
        evidence = _unique([*evidence, *(eid for item in analysis.contributions for eid in item.evidence_ids)])
    text_parts = [part for part in (abstract, contributions) if part]
    if not text_parts:
        return []
    return [
        InteractivePaperBlock(
            id="block_overview",
            type=BlockType.OVERVIEW,
            title="Paper in one minute",
            simplified_explanation=" ".join(text_parts),
            key_points=[item.statement for item in (analysis.contributions if analysis else [])],
            evidence_ids=evidence,
            status=BlockStatus.READY,
            validator_status=ValidatorStatus.PASSED,
            inferred=False,
        )
    ]


def _claim_block(
    block_id: str,
    block_type: BlockType,
    title: str,
    statement: str,
    evidence_ids: list[str],
    *,
    inferred: bool,
    extra: str | None = None,
) -> InteractivePaperBlock:
    explanation = statement if not extra else f"{statement} {extra}".strip()
    return InteractivePaperBlock(
        id=block_id,
        type=block_type,
        title=title,
        simplified_explanation=explanation,
        evidence_ids=_unique(evidence_ids),
        status=BlockStatus.READY,
        inferred=inferred,
        validator_status=ValidatorStatus.PASSED,
    )


def _method_block(analysis: PaperIR, document: StructuredDocument) -> InteractivePaperBlock:
    method = analysis.method
    assert method is not None
    nodes = [
        VisualNode(
            id=step.id,
            label=step.label,
            description=step.description,
            role="method",
            evidence_ids=step.evidence_ids,
            inferred=step.origin == StatementOrigin.MODEL_INFERRED,
            related_equation_ids=_related_equations(step.label, analysis),
        )
        for step in sorted(method.steps, key=lambda item: item.order)
    ]
    if not nodes and method.summary:
        nodes = [
            VisualNode(
                id="method_summary_node",
                label="Proposed method",
                description=method.summary,
                role="method",
                evidence_ids=method.evidence_ids,
                inferred=method.origin == StatementOrigin.MODEL_INFERRED,
            )
        ]
    edges: list[VisualEdge] = []
    if method.relations:
        for index, relation in enumerate(method.relations):
            edges.append(
                VisualEdge(
                    id=f"method_edge_{index:03d}",
                    source=relation.source_step_id,
                    target=relation.target_step_id,
                    label=relation.relationship,
                    evidence_ids=method.evidence_ids,
                    inferred=method.origin == StatementOrigin.MODEL_INFERRED,
                )
            )
    elif len(nodes) > 1:
        for index in range(len(nodes) - 1):
            edges.append(
                VisualEdge(
                    id=f"method_seq_{index:03d}",
                    source=nodes[index].id,
                    target=nodes[index + 1].id,
                    label="next",
                    evidence_ids=[],
                    inferred=True,
                )
            )
    visual = VisualDiagram(type=DiagramType.PIPELINE, title="How the proposed method works", nodes=nodes, edges=edges)
    equations = [_equation_explanation(item, document, [node.id for node in nodes]) for item in analysis.equations[:4]]
    figures = [
        FigureBinding(figure_id=figure.id, simplified_explanation=figure.caption, evidence_ids=figure.evidence_ids)
        for figure in document.figures[:2]
        if figure.caption or figure.image_reference
    ]
    return InteractivePaperBlock(
        id="block_method",
        type=BlockType.METHOD,
        title="How it works",
        simplified_explanation=method.summary,
        visual=visual,
        archify_ir=_archify_payload(visual, document.id),
        equations=equations,
        figures=figures,
        evidence_ids=_unique([*method.evidence_ids, *(eid for node in nodes for eid in node.evidence_ids)]),
        status=BlockStatus.READY,
        inferred=method.origin == StatementOrigin.MODEL_INFERRED,
        validator_status=ValidatorStatus.PASSED,
    )


def _experiment_block(analysis: PaperIR, document: StructuredDocument) -> InteractivePaperBlock:
    experiment = analysis.experiments[0]
    stages: list[tuple[str, str, list[str]]] = []
    if experiment.datasets:
        stages.append(("dataset", "Dataset", experiment.evidence_ids))
    stages.append(("setup", experiment.setup or experiment.name or "Experiment", experiment.evidence_ids))
    if experiment.metrics:
        stages.append(("evaluation", "Evaluation", experiment.evidence_ids))
    if analysis.results:
        stages.append(("result", "Result", analysis.results[0].evidence_ids))
    nodes = [
        VisualNode(id=f"exp_{key}", label=label, role=key, evidence_ids=evidence, inferred=experiment.origin == StatementOrigin.MODEL_INFERRED)
        for key, label, evidence in stages
    ]
    edges = [
        VisualEdge(
            id=f"exp_edge_{index:03d}",
            source=nodes[index].id,
            target=nodes[index + 1].id,
            label="next",
            evidence_ids=[],
            inferred=True,
        )
        for index in range(len(nodes) - 1)
    ]
    visual = VisualDiagram(type=DiagramType.PIPELINE, title="Experiment flow", nodes=nodes, edges=edges) if len(nodes) > 1 else None
    tables = [
        TableBinding(table_id=table.id, simplified_explanation=table.caption, evidence_ids=table.evidence_ids)
        for table in _important_tables(document)[:2]
    ]
    datasets = ", ".join(experiment.datasets) if experiment.datasets else "the reported data"
    metrics = ", ".join(experiment.metrics) if experiment.metrics else "the reported metrics"
    baselines = ", ".join(experiment.baselines) if experiment.baselines else "the paper's baselines"
    explanation = (
        f"{experiment.name or 'The experiment'} measures {metrics} on {datasets}. "
        f"Baselines: {baselines}."
    )
    if experiment.setup:
        explanation = f"{explanation} {experiment.setup}"
    return InteractivePaperBlock(
        id="block_experiments",
        type=BlockType.EXPERIMENT,
        title="Experiments",
        simplified_explanation=explanation,
        visual=visual,
        archify_ir=_archify_payload(visual, document.id) if visual else None,
        tables=tables,
        evidence_ids=experiment.evidence_ids,
        status=BlockStatus.READY,
        inferred=experiment.origin == StatementOrigin.MODEL_INFERRED,
        validator_status=ValidatorStatus.PASSED,
    )


def _result_block(analysis: PaperIR, document: StructuredDocument) -> InteractivePaperBlock:
    statements = []
    evidence: list[str] = []
    for result in analysis.results:
        amount = f"{result.value}{(' ' + result.unit) if result.unit else ''}" if result.value is not None else ""
        baseline = f" compared with {result.comparison_target}" if result.comparison_target else ""
        measured = result.metric or "the reported metric"
        statements.append(f"{result.statement} Measured: {measured}{(' = ' + amount) if amount else ''}{baseline}.")
        evidence.extend(result.evidence_ids)
    tables = [
        TableBinding(table_id=table.id, simplified_explanation=table.caption, evidence_ids=table.evidence_ids)
        for table in _important_tables(document)[:1]
    ]
    return InteractivePaperBlock(
        id="block_results",
        type=BlockType.RESULT,
        title="Results",
        simplified_explanation=" ".join(statements),
        tables=tables,
        key_points=[item.statement for item in analysis.results[:5]],
        evidence_ids=_unique(evidence),
        status=BlockStatus.READY,
        inferred=any(item.origin == StatementOrigin.MODEL_INFERRED for item in analysis.results),
        validator_status=ValidatorStatus.PASSED,
    )


def _equation_block(equations, document: StructuredDocument) -> InteractivePaperBlock:
    explained = [_equation_explanation(item, document, []) for item in equations]
    return InteractivePaperBlock(
        id="block_equations",
        type=BlockType.EQUATION_EXPLANATION,
        title="Mathematical formulation",
        simplified_explanation="Important equations from the paper, with source-linked explanations.",
        equations=explained,
        evidence_ids=_unique(eid for item in explained for eid in item.evidence_ids),
        status=BlockStatus.READY,
        validator_status=ValidatorStatus.PASSED,
    )


def _source_equation_block(document: StructuredDocument) -> InteractivePaperBlock:
    explained = [
        EquationExplanation(
            id=f"src_{equation.id}",
            equation_id=equation.id,
            original_expression=equation.raw_text,
            latex=equation.raw_text,
            explanation=equation.explanation,
            purpose=None,
            evidence_ids=equation.evidence_ids,
            page=equation.page,
            origin=ProvenanceKind.ORIGINAL,
        )
        for equation in document.equations[:6]
        if equation.evidence_ids
    ]
    if not explained:
        return InteractivePaperBlock(
            id="block_equations",
            type=BlockType.EQUATION_EXPLANATION,
            title="Mathematical formulation",
            status=BlockStatus.FAILED,
            error="Equations lacked evidence bindings.",
            validator_status=ValidatorStatus.REJECTED,
        )
    return InteractivePaperBlock(
        id="block_equations",
        type=BlockType.EQUATION_EXPLANATION,
        title="Mathematical formulation",
        equations=explained,
        evidence_ids=_unique(eid for item in explained for eid in item.evidence_ids),
        status=BlockStatus.READY,
        validator_status=ValidatorStatus.PASSED,
    )


def _table_block(tables: list[PaperTable]) -> InteractivePaperBlock:
    return InteractivePaperBlock(
        id="block_tables",
        type=BlockType.TABLE_EXPLANATION,
        title="Important tables",
        simplified_explanation="Benchmark, ablation, or dataset tables retained from the paper.",
        tables=[
            TableBinding(table_id=table.id, simplified_explanation=table.caption, evidence_ids=table.evidence_ids)
            for table in tables
        ],
        evidence_ids=_unique(eid for table in tables for eid in table.evidence_ids),
        status=BlockStatus.READY,
        validator_status=ValidatorStatus.PASSED,
    )


def _equation_explanation(item, document: StructuredDocument, node_ids: list[str]) -> EquationExplanation:
    source = next((equation for equation in document.equations if equation.id == item.equation_id), None)
    terms = [
        EquationTerm(symbol=variable.symbol, meaning=variable.meaning or "Not explicitly defined in the paper.", evidence_ids=item.evidence_ids)
        for variable in item.variables
    ]
    related = [
        node_id
        for node_id in node_ids
        if item.role and node_id.split("_")[-1].lower() in (item.role or "").lower()
    ]
    return EquationExplanation(
        id=item.id,
        equation_id=item.equation_id or (source.id if source else None),
        original_expression=item.expression,
        latex=item.expression,
        explanation=item.explanation or item.interpretation,
        purpose=item.role,
        terms=terms,
        evidence_ids=item.evidence_ids,
        page=source.page if source else None,
        related_node_ids=related,
        origin=ProvenanceKind.SIMPLIFIED if item.explanation else ProvenanceKind.ORIGINAL,
    )


def _related_equations(label: str, analysis: PaperIR) -> list[str]:
    needle = label.lower()
    return [item.id for item in analysis.equations if needle in (item.role or "").lower() or needle in (item.explanation or "").lower()]


def _important_tables(document: StructuredDocument) -> list[PaperTable]:
    scored = []
    for table in document.tables:
        caption = table.caption or ""
        blob = " ".join([caption, " ".join(table.headers), table.raw_text or ""])
        if table.headers and table.rows and _IMPORTANT_TABLE.search(blob):
            scored.append(table)
        elif table.headers and table.rows and len(scored) < 2:
            scored.append(table)
    return scored[:4]


def _concepts(analysis: PaperIR | None):
    from ..models.interactive_paper import ConceptRef

    if analysis is None or analysis.method is None:
        return []
    return [
        ConceptRef(id=step.id, label=step.label, evidence_ids=step.evidence_ids)
        for step in analysis.method.steps[:12]
    ]


def _unique(values) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen


def _archify_payload(visual: VisualDiagram, document_id: str) -> dict[str, object] | None:
    # Archify workflow has six columns; additional steps would overlap.
    if visual.type == DiagramType.PIPELINE and len(visual.nodes) > 6:
        return None
    try:
        return to_archify_ir(paper_visual_graph(visual, document_id=document_id))
    except ArchifyAdapterError:
        # The text/evidence block remains useful when an optional diagram is
        # rejected by the stricter Archify contract.
        return None
