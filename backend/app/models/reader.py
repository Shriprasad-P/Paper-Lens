"""Typed API models for the deterministic visual reader boundary."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from .document import PaperIR, PaperMetadata
from .verification import PaperVerificationResponse


class VisualizationType(str, Enum):
    BAR_CHART = "BAR_CHART"
    LINE_CHART = "LINE_CHART"
    TABLE = "TABLE"
    METRIC = "METRIC"
    METHOD_FLOW = "METHOD_FLOW"
    COMPARISON = "COMPARISON"


class VisualizationSpec(BaseModel):
    """A validated, renderer-neutral visualization description."""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: VisualizationType
    title: str
    data: dict[str, object] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)


class ReaderPaperView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    status: str
    metadata: PaperMetadata


class ReaderSectionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    order: int
    page_start: int | None = None
    page_end: int | None = None
    paragraph_count: int = Field(ge=0)


class ReaderReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    order: int
    raw_text: str
    title: str | None = None
    authors: list[str] | None = None
    year: int | None = None


class ReaderDocumentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    paper_id: str
    page_count: int | None = None
    parser_name: str
    parser_version: str | None = None
    document_hash: str | None = None
    sections: list[ReaderSectionSummary] = Field(default_factory=list)
    references: list[ReaderReference] = Field(default_factory=list)
    section_count: int = Field(ge=0)
    paragraph_count: int = Field(ge=0)
    figure_count: int = Field(ge=0)
    table_count: int = Field(ge=0)
    equation_count: int = Field(ge=0)
    reference_count: int = Field(ge=0)


class ReaderSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    endpoint: str | None = None
    page_count: int | None = None


class ReaderResponse(BaseModel):
    """Small reader payload; evidence bodies remain lazy via evidence APIs."""

    model_config = ConfigDict(extra="forbid")

    paper: ReaderPaperView
    document: ReaderDocumentSummary
    analysis: PaperIR | None = None
    visualizations: list[VisualizationSpec] = Field(default_factory=list)
    source: ReaderSource
    verification: PaperVerificationResponse | None = None
