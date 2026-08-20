"""Build a bounded citation graph from references already extracted in documents."""

from __future__ import annotations

import re

from ..db.database import SQLDatabase
from ..models.research import CitationEdge, CitationGraph, CitationNode


def build_citation_graph(database: SQLDatabase, paper_id: str) -> CitationGraph:
    paper = database.get_by_id(paper_id)
    document = database.get_document(paper_id)
    if paper is None or document is None:
        raise ValueError("Paper or structured document not found.")
    papers = database.list_papers()
    by_arxiv = {item.metadata.arxiv_id.lower(): item for item in papers}
    by_title = {_normalize_title(item.metadata.title): item for item in papers if item.metadata.title}
    nodes = [CitationNode(id=f"paper:{paper.id}", type="PAPER", title=paper.metadata.title, paper_id=paper.id, authors=paper.metadata.authors)]
    edges: list[CitationEdge] = []
    for reference in document.references:
        matched = by_arxiv.get((reference.arxiv_id or "").lower()) if reference.arxiv_id else None
        if matched is None and reference.title:
            matched = by_title.get(_normalize_title(reference.title))
        if matched is None and reference.raw_text:
            raw_title = _normalize_title(reference.raw_text)
            matched = next((candidate for title, candidate in by_title.items() if title and title in raw_title), None)
        if matched is not None:
            target_id = f"paper:{matched.id}"
            if not any(node.id == target_id for node in nodes):
                nodes.append(CitationNode(id=target_id, type="PAPER", title=matched.metadata.title, paper_id=matched.id, authors=matched.metadata.authors))
        else:
            target_id = f"reference:{paper.id}:{reference.id}"
            nodes.append(CitationNode(id=target_id, type="REFERENCE", title=reference.title or reference.raw_text[:160], reference_id=reference.id, authors=reference.authors or [], year=reference.year, raw_text=reference.raw_text))
        edges.append(CitationEdge(source_paper_id=paper.id, reference_id=reference.id, target_node_id=target_id))
    return CitationGraph(paper_id=paper_id, nodes=nodes, edges=edges)


def _normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
