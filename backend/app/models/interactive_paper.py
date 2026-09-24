"""Typed InteractivePaper schema: mixed-content blocks with evidence-bound visuals."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


INTERACTIVE_SCHEMA_VERSION = "interactive-paper-v1.1"
INTERACTIVE_PROMPT_VERSION = "v1"


class BlockType(str, Enum):
    OVERVIEW = "overview"
    PROBLEM = "problem"
    MOTIVATION = "motivation"
    BACKGROUND = "background"
    METHOD = "method"
    ARCHITECTURE = "architecture"
    WORKFLOW = "workflow"
    ALGORITHM = "algorithm"
    EQUATION_EXPLANATION = "equation_explanation"
    EXPERIMENT = "experiment"
    RESULT = "result"
    COMPARISON = "comparison"
    LIMITATION = "limitation"
    CONCLUSION = "conclusion"
    FIGURE_EXPLANATION = "figure_explanation"
    TABLE_EXPLANATION = "table_explanation"
    DATASET = "dataset"
    IMPLEMENTATION_DETAIL = "implementation_detail"


class BlockStatus(str, Enum):
    PLANNED = "PLANNED"
    GENERATING = "GENERATING"
    READY = "READY"
    FAILED = "FAILED"


class DiagramType(str, Enum):
    FLOW = "flow"
    ARCHITECTURE = "architecture"
    PIPELINE = "pipeline"
    HIERARCHY = "hierarchy"
    SEQUENCE = "sequence"
    DATA_FLOW = "data_flow"
    COMPARISON = "comparison"


class ProvenanceKind(str, Enum):
    ORIGINAL = "ORIGINAL"
    SIMPLIFIED = "SIMPLIFIED"
    RECONSTRUCTED = "RECONSTRUCTED"
    INFERRED = "INFERRED"


class GenerationMode(str, Enum):
    ASSEMBLER = "assembler"
    SIMPLIFIED = "simplified"


class ValidatorStatus(str, Enum):
    PASSED = "PASSED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"


class VisualNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    description: str | None = None
    role: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    inferred: bool = False
    related_equation_ids: list[str] = Field(default_factory=list)
    related_figure_ids: list[str] = Field(default_factory=list)


class VisualEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    label: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    inferred: bool = False


class VisualDiagram(BaseModel):
    """Renderer-neutral visualization IR. Never contains HTML, SVG, or script."""

    model_config = ConfigDict(extra="forbid")

    type: DiagramType
    title: str = Field(min_length=1)
    nodes: list[VisualNode] = Field(default_factory=list)
    edges: list[VisualEdge] = Field(default_factory=list)
    reconstructed: bool = True


class EquationTerm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1)
    meaning: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)


class EquationExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    equation_id: str | None = None
    original_expression: str = Field(min_length=1)
    latex: str | None = None
    explanation: str | None = None
    purpose: str | None = None
    terms: list[EquationTerm] = Field(default_factory=list)
    evidence_ids: list[str] = Field(min_length=1)
    page: int | None = None
    section_id: str | None = None
    related_node_ids: list[str] = Field(default_factory=list)
    origin: ProvenanceKind = ProvenanceKind.SIMPLIFIED


class FigureBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    figure_id: str = Field(min_length=1)
    simplified_explanation: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    reconstructed: bool = False


class TableHighlight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row: int = Field(ge=0)
    column: int | None = Field(default=None, ge=0)
    note: str = Field(min_length=1)


class TableBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table_id: str = Field(min_length=1)
    simplified_explanation: str | None = None
    important_cells: list[TableHighlight] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class OutlineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: str
    title: str
    type: BlockType


class ConceptRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    evidence_ids: list[str] = Field(default_factory=list)


class InteractivePaperBlock(BaseModel):
    """A mixed-content unit: prose, visual IR, equations, figures, and tables together."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    type: BlockType
    title: str = Field(min_length=1)
    simplified_explanation: str | None = None
    visual: VisualDiagram | None = None
    archify_ir: dict[str, object] | None = None
    equations: list[EquationExplanation] = Field(default_factory=list)
    figures: list[FigureBinding] = Field(default_factory=list)
    tables: list[TableBinding] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    status: BlockStatus = BlockStatus.PLANNED
    inferred: bool = False
    validator_status: ValidatorStatus | None = None
    error: str | None = None

    @field_validator("simplified_explanation", "title")
    @classmethod
    def reject_markup(cls, value: str | None) -> str | None:
        if value is None:
            return value
        lowered = value.lower()
        if "<script" in lowered or "</html>" in lowered or "javascript:" in lowered:
            raise ValueError("Generated text must not contain markup or script.")
        return value


class InteractivePaper(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = INTERACTIVE_SCHEMA_VERSION
    paper_id: str
    document_id: str
    source_hash: str | None = None
    document_hash: str | None = None
    analysis_fingerprint: str | None = None
    generation_mode: GenerationMode = GenerationMode.ASSEMBLER
    generation_config: dict[str, str | None] = Field(default_factory=dict)
    cache_key: str
    provider: str | None = None
    model: str | None = None
    prompt_version: str = INTERACTIVE_PROMPT_VERSION
    status: BlockStatus = BlockStatus.PLANNED
    overview: str | None = None
    blocks: list[InteractivePaperBlock] = Field(default_factory=list)
    outline: list[OutlineItem] = Field(default_factory=list)
    concepts: list[ConceptRef] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def outline_matches_blocks(self) -> "InteractivePaper":
        if not self.outline and self.blocks:
            self.outline = [
                OutlineItem(block_id=block.id, title=block.title, type=block.type)
                for block in self.blocks
                if block.status != BlockStatus.FAILED
            ]
        return self


class BlockSimplification(BaseModel):
    """Bounded per-block LLM output. Never rendered as HTML."""

    model_config = ConfigDict(extra="forbid")

    simplified_explanation: str = Field(min_length=1)
    key_points: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    inferred: bool = False

    @field_validator("simplified_explanation")
    @classmethod
    def reject_markup(cls, value: str) -> str:
        lowered = value.lower()
        if "<script" in lowered or "<html" in lowered or "javascript:" in lowered:
            raise ValueError("Generated text must not contain markup or script.")
        return value
