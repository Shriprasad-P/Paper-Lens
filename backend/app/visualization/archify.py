"""Evidence-safe adapter and renderer bridge for pinned Archify v2.16.0."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..models.interactive_paper import VisualDiagram

ARCHIFY_VERSION = "2.16.0"
# v2.16.0 is an annotated tag; this is the commit the tag resolves to.
ARCHIFY_COMMIT = "c826e6c3a7abad19c0f3cd1ca57207d54b1ad8de"
ARCHIFY_LICENSE = "MIT"


class PaperVisualGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    title: str
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    source_document_id: str
    evidence_ids: list[str] = Field(default_factory=list)


class ArchifyAdapterError(ValueError):
    """Evidence graph or pinned renderer cannot produce a safe diagram."""


def paper_visual_graph(diagram: VisualDiagram, *, document_id: str) -> PaperVisualGraph:
    graph = PaperVisualGraph(
        id=f"paper_graph_{diagram.title.lower().replace(' ', '_')[:48]}", type=diagram.type.value,
        title=diagram.title, source_document_id=document_id,
        nodes=[node.model_dump(mode="json") for node in diagram.nodes],
        edges=[edge.model_dump(mode="json") for edge in diagram.edges],
        evidence_ids=sorted({eid for node in diagram.nodes for eid in node.evidence_ids} | {eid for edge in diagram.edges for eid in edge.evidence_ids}),
    )
    validate_paper_visual_graph(graph)
    return graph


def to_archify_ir(graph: PaperVisualGraph) -> dict[str, Any]:
    """Return the actual Archify schema plus a PaperLens provenance envelope.

    Archify's v2.16.0 schemas reject unknown fields, so evidence bindings are
    kept in a sibling envelope and never sent to the renderer as fake source
    ranges.  The nested ``diagram`` is directly consumable by Archify CLI.
    """

    validate_paper_visual_graph(graph)
    return {
        "diagram": _archify_diagram(graph),
        "paperlens": {"source_document_id": graph.source_document_id, "evidence_ids": graph.evidence_ids, "graph": graph.model_dump(mode="json")},
        "archify": {"version": ARCHIFY_VERSION, "commit": ARCHIFY_COMMIT, "license": ARCHIFY_LICENSE},
    }


def _archify_diagram(graph: PaperVisualGraph) -> dict[str, Any]:
    if graph.type in {"PIPELINE", "pipeline"}:
        return _workflow_ir(graph)
    if graph.type in {"DATA_FLOW", "data_flow"}:
        return _dataflow_ir(graph)
    return _architecture_ir(graph)


def _architecture_ir(graph: PaperVisualGraph) -> dict[str, Any]:
    """Map a validated paper graph to Archify's deterministic architecture renderer."""

    components: list[dict[str, Any]] = []
    for index, node in enumerate(graph.nodes):
        role = str(node.get("role") or "").lower()
        component_type = "database" if any(term in role for term in ("store", "database", "cache")) else "external" if node.get("inferred") else "backend"
        components.append({
            "id": str(node["id"]), "type": component_type, "label": str(node["label"]),
            **({"sublabel": str(node["description"])[:140]} if node.get("description") else {}),
            "row": index // 4, "col": index % 4, "size": [180, 84],
        })
    connections = [
        {"id": str(edge["id"]), "from": str(edge["source"]), "to": str(edge["target"]),
         **({"label": str(edge["label"])} if edge.get("label") else {}),
         **({"variant": "dashed"} if edge.get("inferred") else {})}
        for edge in graph.edges
    ]
    return {
        "schema_version": 1, "diagram_type": "architecture",
        "meta": {"title": graph.title, "quality_profile": "showcase"},
        "layout": {"mode": "grid", "origin": [40, 80], "cols": 4, "gapX": 70, "gapY": 60, "cellW": 180, "cellH": 84},
        "components": components, "connections": connections,
    }


def _workflow_ir(graph: PaperVisualGraph) -> dict[str, Any]:
    lane_id = "paper_method"
    return {
        "schema_version": 2,
        "diagram_type": "workflow",
        "meta": {"title": graph.title, "quality_profile": "showcase"},
        "lanes": [{"id": lane_id, "label": "Paper method"}],
        "nodes": [{"id": str(node["id"]), "lane": lane_id, "col": min(index, 5), "type": "backend", "label": str(node["label"]), **({"sublabel": str(node["description"])[:140]} if node.get("description") else {}), "width": 180, "height": 84} for index, node in enumerate(graph.nodes)],
        "edges": [{"id": str(edge["id"]), "from": str(edge["source"]), "to": str(edge["target"]), **({"label": str(edge["label"])} if edge.get("label") else {}), **({"variant": "dashed"} if edge.get("inferred") else {})} for edge in graph.edges],
    }


def _dataflow_ir(graph: PaperVisualGraph) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "diagram_type": "dataflow",
        "meta": {"title": graph.title, "quality_profile": "showcase"},
        "stages": [{"label": "Input"}, {"label": "Output"}],
        "nodes": [{"id": str(node["id"]), "type": "backend", "label": str(node["label"]), "stage": min(index, 1), "row": 0, **({"sublabel": str(node["description"])[:140]} if node.get("description") else {})} for index, node in enumerate(graph.nodes)],
        "flows": [{"from": str(edge["source"]), "to": str(edge["target"]), **({"label": str(edge["label"])} if edge.get("label") else {}), **({"variant": "dashed"} if edge.get("inferred") else {})} for edge in graph.edges],
    }


def validate_paper_visual_graph(graph: PaperVisualGraph) -> None:
    node_ids = {str(node.get("id")) for node in graph.nodes}
    if not node_ids:
        raise ArchifyAdapterError("A PaperLens visual graph needs at least one node.")
    for node in graph.nodes:
        if not node.get("label"):
            raise ArchifyAdapterError("Visual nodes must have labels.")
        if not node.get("evidence_ids") and not node.get("inferred"):
            raise ArchifyAdapterError("Factual visual nodes require evidence or explicit inferred=true.")
    for edge in graph.edges:
        if edge.get("source") not in node_ids or edge.get("target") not in node_ids:
            raise ArchifyAdapterError("Visual relationships must reference existing nodes.")
        if not edge.get("evidence_ids") and not edge.get("inferred"):
            raise ArchifyAdapterError("Factual visual relationships require evidence or explicit inferred=true.")


def validate_archify_ir(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the pinned Archify validator and return its structured receipt."""

    diagram = payload.get("diagram") if isinstance(payload, dict) else None
    if not isinstance(diagram, dict):
        raise ArchifyAdapterError("Archify payload is missing its typed diagram document.")
    graph_type = str(diagram.get("diagram_type") or "architecture")
    root = _archify_root()
    if not (root / "bin" / "archify.mjs").is_file():
        raise ArchifyAdapterError("The pinned Archify runtime is not installed.")
    with tempfile.TemporaryDirectory(prefix="paperlens-archify-") as temp_dir:
        input_path = Path(temp_dir) / "diagram.json"
        input_path.write_text(json.dumps(diagram, sort_keys=True), encoding="utf-8")
        result = subprocess.run(["node", str(root / "bin" / "archify.mjs"), "validate", graph_type, str(input_path), "--json", "--quality", "showcase"], cwd=root, capture_output=True, text=True, timeout=15, check=False)
    receipt = _parse_archify_receipt(result.stdout)
    if result.returncode != 0 or not receipt.get("ok"):
        raise ArchifyAdapterError("The pinned Archify schema rejected the diagram.")
    return receipt


def render_archify_ir(payload: dict[str, Any]) -> str:
    """Render a validated Archify document to a self-contained HTML artifact."""

    diagram = payload.get("diagram") if isinstance(payload, dict) else None
    if not isinstance(diagram, dict):
        raise ArchifyAdapterError("Archify payload is missing its typed diagram document.")
    validate_archify_ir(payload)
    root = _archify_root()
    graph_type = str(diagram.get("diagram_type") or "architecture")
    with tempfile.TemporaryDirectory(prefix="paperlens-archify-") as temp_dir:
        input_path = Path(temp_dir) / "diagram.json"
        output_path = Path(temp_dir) / "diagram.html"
        input_path.write_text(json.dumps(diagram, sort_keys=True), encoding="utf-8")
        result = subprocess.run(["node", str(root / "bin" / "archify.mjs"), "render", graph_type, str(input_path), str(output_path), "--quality", "showcase"], cwd=root, capture_output=True, text=True, timeout=20, check=False)
        if result.returncode != 0 or not output_path.exists():
            raise ArchifyAdapterError("The pinned Archify renderer failed to produce an artifact.")
        return _inject_parent_bridge(output_path.read_text(encoding="utf-8"))


async def render_archify_ir_async(payload: dict[str, Any]) -> str:
    return await asyncio.to_thread(render_archify_ir, payload)


def _archify_root() -> Path:
    configured = os.getenv("PAPERLENS_ARCHIFY_ROOT")
    return Path(configured).expanduser().resolve() if configured else Path(__file__).resolve().parents[3] / "vendor" / "archify"


def _parse_archify_receipt(stdout: str) -> dict[str, Any]:
    try:
        value = json.loads(stdout.strip() or "{}")
    except json.JSONDecodeError as exc:
        raise ArchifyAdapterError("Archify did not return a structured validation receipt.") from exc
    return value if isinstance(value, dict) else {}


def _inject_parent_bridge(html: str) -> str:
    """Forward Archify semantic node/edge selections to the PaperLens reader."""

    bridge = """<script>(function(){var svg=document.querySelector('svg');if(!svg||!window.parent||window.parent===window)return;svg.addEventListener('click',function(event){var node=event.target.closest('[data-node-id]');if(node){window.parent.postMessage({source:'paperlens-archify',nodeId:node.getAttribute('data-node-id')},'*');return;}var edge=event.target.closest('[data-edge-id],[data-edge-from][data-edge-to]');if(edge){window.parent.postMessage({source:'paperlens-archify',edgeId:edge.getAttribute('data-edge-id')||edge.getAttribute('data-edge-key')||'',sourceId:edge.getAttribute('data-edge-from')||'',targetId:edge.getAttribute('data-edge-to')||''},'*');}});})();</script>"""
    return html.replace("</body>", f"{bridge}</body>", 1)
