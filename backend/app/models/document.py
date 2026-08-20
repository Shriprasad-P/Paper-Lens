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
    number: str | None = None
    caption: str | None = None
    page: int | None = None
    source_region: SourceRegion | None = None
    image_reference: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class PaperTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str | None = None
    number: str | None = None
    caption: str | None = None
    page: int | None = None
    raw_text: str | None = None
    source_region: SourceRegion | None = None
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class PaperEquation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    raw_text: str
    label: str | None = None
    page: int | None = None
    source_region: SourceRegion | None = None
    explanation: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class PaperReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    order: int = Field(ge=0)
    raw_text: str
    title: str | None = None
    authors: list[str] | None = None
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    url: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


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
    FIGURE_CAPTION = "FIGURE_CAPTION"
    TABLE_CAPTION = "TABLE_CAPTION"
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
    NO_EVIDENCE = "NO_EVIDENCE"


class StatementOrigin(str, Enum):
    AUTHOR_EXPLICIT = "AUTHOR_EXPLICIT"
    MODEL_INFERRED = "MODEL_INFERRED"


class ExtractionState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ExtractionStatus = ExtractionStatus.NOT_STARTED
    error: str | None = None
    cache_key: str | None = None
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    schema_version: str | None = None


class ResearchClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    statement: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    origin: StatementOrigin
    confidence: float | None = Field(default=None, ge=0, le=1)


# Compatibility name retained for callers that imported the Phase 3 shell.
ClaimIR = ResearchClaim


class ProblemIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    statement: str = Field(min_length=1)
    context: str | None = None
    evidence_ids: list[str] = Field(min_length=1)
    origin: StatementOrigin
    confidence: float | None = Field(default=None, ge=0, le=1)


class MotivationIR(ResearchClaim):
    pass


class ResearchGapIR(ResearchClaim):
    pass


class ContributionIR(ResearchClaim):
    pass


class MethodStepIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    order: int = Field(ge=0)
    evidence_ids: list[str] = Field(min_length=1)
    origin: StatementOrigin


class MethodRelationIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_step_id: str = Field(min_length=1)
    target_step_id: str = Field(min_length=1)
    relationship: str = Field(min_length=1)


class MethodIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    origin: StatementOrigin
    steps: list[MethodStepIR] = Field(default_factory=list)
    relations: list[MethodRelationIR] = Field(default_factory=list)


class EquationVariableIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1)
    meaning: str | None = None


class EquationIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    equation_id: str | None = None
    expression: str = Field(min_length=1)
    explanation: str | None = None
    # Kept as a compatibility alias for the Phase 3 typed model.
    interpretation: str | None = None
    role: str | None = None
    variables: list[EquationVariableIR] = Field(default_factory=list)
    evidence_ids: list[str] = Field(min_length=1)
    origin: StatementOrigin


class ExperimentIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str | None = None
    datasets: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    baselines: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    setup: str | None = None
    evidence_ids: list[str] = Field(min_length=1)
    origin: StatementOrigin


class ResultIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    statement: str = Field(min_length=1)
    metric: str | None = None
    value: float | str | None = None
    unit: str | None = None
    comparison_target: str | None = None
    evidence_ids: list[str] = Field(min_length=1)
    origin: StatementOrigin


class LimitationIR(ResearchClaim):
    pass


class FutureWorkIR(ResearchClaim):
    pass


class PaperIR(BaseModel):
    """Evidence-grounded semantic representation produced by Phase 4."""

    model_config = ConfigDict(extra="forbid")

    paper_id: str
    document_id: str
    metadata: PaperMetadata
    problem: ProblemIR | None = None
    motivation: MotivationIR | None = None
    research_gap: list[ResearchGapIR] = Field(default_factory=list)
    contributions: list[ContributionIR] = Field(default_factory=list)
    method: MethodIR | None = None
    equations: list[EquationIR] = Field(default_factory=list)
    experiments: list[ExperimentIR] = Field(default_factory=list)
    results: list[ResultIR] = Field(default_factory=list)
    limitations: list[LimitationIR] = Field(default_factory=list)
    future_work: list[FutureWorkIR] = Field(default_factory=list)
    section_classifications: list[dict[str, object]] = Field(default_factory=list)
    extraction: dict[str, ExtractionState] = Field(default_factory=dict)
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    schema_version: str | None = None
    document_hash: str | None = None
