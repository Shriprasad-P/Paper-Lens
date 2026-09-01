"""Fail-closed validation for InteractivePaper evidence and visualization IR."""

from __future__ import annotations

from ..models.interactive_paper import (
    BlockStatus,
    EquationExplanation,
    InteractivePaper,
    InteractivePaperBlock,
    ValidatorStatus,
    VisualDiagram,
    VisualEdge,
    VisualNode,
)


class InteractiveValidationError(ValueError):
    """Malformed or ungrounded interactive output."""


def sanitize_diagram(diagram: VisualDiagram, available_ids: set[str]) -> VisualDiagram | None:
    """Drop unsupported nodes/edges. Inferred items may omit evidence."""

    nodes: list[VisualNode] = []
    for node in diagram.nodes:
        evidence = [item for item in node.evidence_ids if item in available_ids]
        if not evidence and not node.inferred:
            continue
        nodes.append(node.model_copy(update={"evidence_ids": evidence}))
    node_ids = {node.id for node in nodes}
    edges: list[VisualEdge] = []
    for index, edge in enumerate(diagram.edges):
        if edge.source not in node_ids or edge.target not in node_ids:
            continue
        evidence = [item for item in edge.evidence_ids if item in available_ids]
        if not evidence and not edge.inferred:
            continue
        edges.append(
            edge.model_copy(
                update={
                    "id": edge.id or f"edge_{index:03d}",
                    "evidence_ids": evidence,
                }
            )
        )
    if not nodes:
        return None
    return diagram.model_copy(update={"nodes": nodes, "edges": edges})


def sanitize_equation(equation: EquationExplanation, available_ids: set[str]) -> EquationExplanation | None:
    evidence = [item for item in equation.evidence_ids if item in available_ids]
    if not evidence:
        return None
    terms = []
    for term in equation.terms:
        term_evidence = [item for item in term.evidence_ids if item in available_ids]
        terms.append(term.model_copy(update={"evidence_ids": term_evidence}))
    return equation.model_copy(update={"evidence_ids": evidence, "terms": terms})


def sanitize_block(
    block: InteractivePaperBlock,
    *,
    available_ids: set[str],
    figure_ids: set[str],
    table_ids: set[str],
) -> InteractivePaperBlock:
    evidence = [item for item in block.evidence_ids if item in available_ids]
    visual = sanitize_diagram(block.visual, available_ids) if block.visual else None
    equations = [
        sanitized
        for item in block.equations
        if (sanitized := sanitize_equation(item, available_ids)) is not None
    ]
    figures = [
        item.model_copy(update={"evidence_ids": [eid for eid in item.evidence_ids if eid in available_ids]})
        for item in block.figures
        if item.figure_id in figure_ids
    ]
    tables = [
        item.model_copy(update={"evidence_ids": [eid for eid in item.evidence_ids if eid in available_ids]})
        for item in block.tables
        if item.table_id in table_ids
    ]
    has_content = bool(
        (block.simplified_explanation and block.simplified_explanation.strip())
        or visual
        or equations
        or figures
        or tables
        or block.key_points
    )
    if not has_content:
        return block.model_copy(
            update={
                "status": BlockStatus.FAILED,
                "validator_status": ValidatorStatus.REJECTED,
                "visual": None,
                "equations": [],
                "figures": [],
                "tables": [],
                "evidence_ids": evidence,
                "error": "Block had no grounded content after validation.",
            }
        )
    visual_failed = block.visual is not None and visual is None
    status = BlockStatus.READY if block.status != BlockStatus.FAILED else BlockStatus.FAILED
    validator = ValidatorStatus.PARTIAL if visual_failed or (block.evidence_ids and not evidence and not block.inferred) else ValidatorStatus.PASSED
    return block.model_copy(
        update={
            "evidence_ids": evidence,
            "visual": visual,
            "equations": equations,
            "figures": figures,
            "tables": tables,
            "status": status,
            "validator_status": validator,
            "error": "Visualization dropped; text kept." if visual_failed else block.error,
        }
    )


def validate_paper(
    paper: InteractivePaper,
    *,
    available_ids: set[str],
    figure_ids: set[str],
    table_ids: set[str],
) -> InteractivePaper:
    blocks = [
        sanitize_block(block, available_ids=available_ids, figure_ids=figure_ids, table_ids=table_ids)
        for block in paper.blocks
    ]
    ready = [block for block in blocks if block.status == BlockStatus.READY]
    status = BlockStatus.READY if ready else BlockStatus.FAILED if blocks else BlockStatus.PLANNED
    outline = [
        item
        for item in paper.outline
        if any(block.id == item.block_id and block.status == BlockStatus.READY for block in blocks)
    ]
    if not outline:
        from ..models.interactive_paper import OutlineItem

        outline = [
            OutlineItem(block_id=block.id, title=block.title, type=block.type)
            for block in ready
        ]
    return paper.model_copy(update={"blocks": blocks, "outline": outline, "status": status})
