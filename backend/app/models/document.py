"""Typed, source-preserving document and provenance models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from .paper import PaperMetadata


class SourceRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int
    x0: float | None = None
    y0: float | None = None
    x1: float | None = None
    y1: float | None = None


class PaperParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    section_id: str
    order: int = Field(ge=0)
    text: str
    page: int | None = None
    source_region: SourceRegion | None = None
    content_hash: str | None = None
    evidence_id: str | None = None


class PaperSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    level: int = Field(ge=1)
    order: int = Field(ge=0)
    parent_id: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    paragraphs: list[PaperParagraph] = Field(default_factory=list)


class PaperFigure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str | None = None
    caption: str | None = None
    page: int | None = None
    source_region: SourceRegion | None = None


class PaperTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str | None = None
    caption: str | None = None
    page: int | None = None
    raw_text: str | None = None
    source_region: SourceRegion | None = None


class PaperEquation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    raw_text: str
    label: str | None = None
    page: int | None = None
    source_region: SourceRegion | None = None


class PaperReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    order: int = Field(ge=0)
    raw_text: str
    title: str | None = None
    authors: list[str] | None = None
    year: int | None = None


class StructuredDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    paper_id: str
    metadata: PaperMetadata
    sections: list[PaperSection] = Field(default_factory=list)
    figures: list[PaperFigure] = Field(default_factory=list)
    tables: list[PaperTable] = Field(default_factory=list)
    equations: list[PaperEquation] = Field(default_factory=list)
    references: list[PaperReference] = Field(default_factory=list)
    page_count: int | None = None
    parser_name: str
    parser_version: str | None = None
    source_hash: str | None = None
    document_hash: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EvidenceType(str, Enum):
    PARAGRAPH = "PARAGRAPH"
    FIGURE = "FIGURE"
    TABLE = "TABLE"
    EQUATION = "EQUATION"
    CAPTION = "CAPTION"
    REFERENCE = "REFERENCE"


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    paper_id: str
    document_id: str
    evidence_type: EvidenceType
    source_text: str
    page: int | None = None
    section_id: str | None = None
    paragraph_id: str | None = None
    figure_id: str | None = None
    table_id: str | None = None
    equation_id: str | None = None
    source_region: SourceRegion | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExtractionStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ExtractionState(BaseModel):
    status: ExtractionStatus = ExtractionStatus.NOT_STARTED
    error: str | None = None


class ClaimIR(BaseModel):
    text: str
    evidence_ids: list[str] = Field(default_factory=list)


class ProblemIR(BaseModel):
    statements: list[ClaimIR] = Field(default_factory=list)


class MethodIR(BaseModel):
    nodes: list[dict[str, object]] = Field(default_factory=list)
    edges: list[dict[str, object]] = Field(default_factory=list)


class EquationIR(BaseModel):
    equation_id: str
    interpretation: str | None = None


class ExperimentIR(BaseModel):
    items: list[dict[str, object]] = Field(default_factory=list)


class ResultIR(BaseModel):
    items: list[dict[str, object]] = Field(default_factory=list)


class PaperIR(BaseModel):
    """Empty semantic shell; Phase 4 owns populating these fields."""

    model_config = ConfigDict(extra="forbid")

    paper_id: str
    document_id: str
    metadata: PaperMetadata
    problem: ProblemIR | None = None
    research_gap: list[ClaimIR] = Field(default_factory=list)
    contributions: list[ClaimIR] = Field(default_factory=list)
    method: MethodIR | None = None
    equations: list[EquationIR] = Field(default_factory=list)
    experiments: list[ExperimentIR] = Field(default_factory=list)
    results: list[ResultIR] = Field(default_factory=list)
    limitations: list[ClaimIR] = Field(default_factory=list)
    future_work: list[ClaimIR] = Field(default_factory=list)
    extraction: dict[str, ExtractionState] = Field(default_factory=dict)
