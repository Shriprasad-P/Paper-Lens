"""Versioned benchmark datasets, annotations, predictions, and results."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvaluationStatus(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    VALIDATED = "VALIDATED"


class AnnotationStatus(str, Enum):
    DRAFT = "DRAFT"
    REVIEWED = "REVIEWED"
    ADJUDICATED = "ADJUDICATED"


class EvaluationRunMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    benchmark_version: str = "v1"
    dataset_version: str = "v1"
    annotation_version: str = "v1"
    metric_version: str = "v1"
    git_commit: str | None = None
    retrieval_mode: str | None = None
    ai_provider: str | None = None
    ai_model: str | None = None
    embedding_provider: str | None = None
    embedding_model: str | None = None
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    schema_versions: dict[str, str] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    random_seed: int | None = 0
    live: bool = False


class BenchmarkPaper(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str
    source_type: str = "ARXIV"
    source_identifier: str
    domain: str
    tags: list[str] = Field(default_factory=list)
    acquisition_url: str | None = None


class BenchmarkManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    benchmark_version: str
    dataset_version: str
    status: EvaluationStatus = EvaluationStatus.PRELIMINARY
    acquisition: str
    papers: list[BenchmarkPaper] = Field(min_length=1)


class SectionAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    label: str
    order: int = Field(ge=0)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)


class ClaimAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1)
    evidence_texts: list[str] = Field(default_factory=list)
    page_numbers: list[int] = Field(default_factory=list, min_length=0)
    section_titles: list[str] = Field(default_factory=list)


class MethodAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    description: str
    order: int = Field(ge=0)
    evidence_texts: list[str] = Field(default_factory=list)


class ExperimentAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    datasets: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    evidence_texts: list[str] = Field(default_factory=list)


class ResultAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str
    metric: str | None = None
    value: float | str | None = None
    unit: str | None = None
    comparison_target: str | None = None
    evidence_texts: list[str] = Field(default_factory=list)


class BenchmarkPaperAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str
    annotation_status: AnnotationStatus = AnnotationStatus.DRAFT
    annotator_ids: list[str] = Field(default_factory=list)
    sections: list[SectionAnnotation] = Field(default_factory=list)
    research_problem: list[ClaimAnnotation] = Field(default_factory=list)
    motivation: list[ClaimAnnotation] = Field(default_factory=list)
    contributions: list[ClaimAnnotation] = Field(default_factory=list)
    research_gaps: list[ClaimAnnotation] = Field(default_factory=list)
    method_steps: list[MethodAnnotation] = Field(default_factory=list)
    experiments: list[ExperimentAnnotation] = Field(default_factory=list)
    results: list[ResultAnnotation] = Field(default_factory=list)
    limitations: list[ClaimAnnotation] = Field(default_factory=list)
    future_work: list[ClaimAnnotation] = Field(default_factory=list)


class RetrievalBenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    paper_id: str
    query: str
    category: str
    relevant_evidence_ids: list[str] = Field(min_length=1)
    difficulty: str = "fixture"
    predictions: dict[str, list[str]] = Field(default_factory=dict)


class VerificationStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTORY = "CONTRADICTORY"
    UNVERIFIED = "UNVERIFIED"


class VerificationBenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    claim: str
    evidence: list[str]
    origin: str = "AUTHOR_EXPLICIT"
    gold_status: VerificationStatus
    prediction: VerificationStatus | None = None


class ChatBenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    paper_id: str
    question: str
    expected_answer_points: list[str] = Field(default_factory=list)
    relevant_evidence_ids: list[str] = Field(default_factory=list)
    answerable: bool
    category: str
    prediction: dict[str, Any] | None = None


class DiscoveryBenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    research_question: str
    relevant_paper_ids: list[str] = Field(min_length=1)
    candidate_paper_ids: list[str] = Field(default_factory=list)
    difficulty: str = "fixture"


class SynthesisBenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    kind: str
    input_claims: list[str]
    expected: str
    expected_origin: str = "CROSS_PAPER_INFERRED"
    evidence_refs_valid: bool = True


class HumanEvaluationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str
    evaluator_id: str
    item_id: str
    correctness: int = Field(ge=0, le=2)
    faithfulness: int = Field(ge=0, le=2)
    usefulness: int = Field(ge=0, le=2)
    clarity: int = Field(ge=0, le=2)
    citation_quality: int = Field(ge=0, le=2)
    rationale: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EvaluationMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: float | None = None
    count: int = Field(default=0, ge=0)
    status: EvaluationStatus = EvaluationStatus.PRELIMINARY
    methodology: str | None = None

    @field_validator("value")
    @classmethod
    def finite_value(cls, value: float | None) -> float | None:
        if value is not None and (value != value or value in {float("inf"), float("-inf")}):
            raise ValueError("Metric value must be finite.")
        return value


class EvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component: str
    metadata: EvaluationRunMetadata
    metrics: list[EvaluationMetric] = Field(default_factory=list)
    confusion_matrix: dict[str, dict[str, int]] | None = None
    failure_counts: dict[str, int] = Field(default_factory=dict)
    examples: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    notes: list[str] = Field(default_factory=list)


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = "PaperLens Evaluation Report"
    status: EvaluationStatus = EvaluationStatus.PRELIMINARY
    metadata: EvaluationRunMetadata
    results: list[EvaluationResult] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
