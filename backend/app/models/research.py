"""Typed workspace, comparison, and citation-graph models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Workspace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str = Field(min_length=1, max_length=120)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)


class WorkspacePaper(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    paper_id: str
    added_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkspacePaperView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str
    title: str
    arxiv_id: str
    analyzed: bool
    added_at: datetime


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: Workspace
    papers: list[WorkspacePaperView] = Field(default_factory=list)


class ComparisonEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str
    document_id: str | None = None
    statement: str | None = None
    values: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class Comparability(str, Enum):
    COMPARABLE = "COMPARABLE"
    PARTIALLY_COMPARABLE = "PARTIALLY_COMPARABLE"
    NOT_COMPARABLE = "NOT_COMPARABLE"


class ComparisonDimension(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    entries: list[ComparisonEntry] = Field(default_factory=list)
    comparability: Comparability | None = None
    note: str | None = None


class PaperComparisonIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_ids: list[str] = Field(min_length=2, max_length=5)
    dimensions: list[ComparisonDimension] = Field(default_factory=list)


class ComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_ids: list[str] = Field(min_length=2, max_length=5)


class CitationNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    title: str
    paper_id: str | None = None
    reference_id: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    raw_text: str | None = None


class CitationEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_paper_id: str
    reference_id: str
    target_node_id: str
    relationship: str = "CITES"


class CitationGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str
    nodes: list[CitationNode] = Field(default_factory=list)
    edges: list[CitationEdge] = Field(default_factory=list)
