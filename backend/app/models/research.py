"""Typed workspace, comparison, and citation-graph models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Workspace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str = Field(min_length=1, max_length=120)
    owner_id: str = "user_legacy_local"
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


class ResearchRunStatus(str, Enum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    DISCOVERING = "DISCOVERING"
    SELECTING = "SELECTING"
    INGESTING = "INGESTING"
    ANALYZING = "ANALYZING"
    SYNTHESIZING = "SYNTHESIZING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"


class ResearchExecutionState(str, Enum):
    """Durable execution lifecycle, independent from visible stage status."""

    IDLE = "IDLE"
    QUEUED = "QUEUED"
    CLAIMED = "CLAIMED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"


class ResearchAttemptStatus(str, Enum):
    CLAIMED = "CLAIMED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    LOST = "LOST"


@dataclass(frozen=True, slots=True)
class ExecutionClaim:
    """Opaque in-memory claim credential; its raw token is never persisted."""

    run_id: str
    attempt_id: str
    worker_id: str
    token: str
    attempt_number: int
    lease_expires_at: datetime

    @property
    def claim_token(self) -> str:
        """Readable alias used by worker integrations without exposing it in responses."""

        return self.token


class ResearchDepth(str, Enum):
    QUICK = "QUICK"
    STANDARD = "STANDARD"
    DEEP = "DEEP"


class ResearchRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str | None = None
    research_question: str = Field(min_length=1, max_length=4_000)
    status: ResearchRunStatus = ResearchRunStatus.CREATED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    max_iterations: int = Field(ge=1, le=3)
    max_candidates: int = Field(ge=1, le=30)
    max_ingested_papers: int = Field(ge=1, le=8)
    planner_provider: str | None = None
    planner_model: str | None = None
    prompt_version: str = "v1"
    schema_version: str = "v1"
    execution_state: ResearchExecutionState = ResearchExecutionState.IDLE
    active_attempt_id: str | None = None
    attempt_count: int = Field(default=0, ge=0)
    cancel_requested_at: datetime | None = None
    next_attempt_at: datetime | None = None


class ResearchRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4_000)
    depth: ResearchDepth = ResearchDepth.STANDARD
    workspace_id: str | None = None


class ResearchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_question: str = Field(min_length=1, max_length=4_000)
    search_queries: list[str] = Field(min_length=1, max_length=8)
    concepts: list[str] = Field(default_factory=list, max_length=32)
    inclusion_criteria: list[str] = Field(default_factory=list, max_length=12)
    exclusion_criteria: list[str] = Field(default_factory=list, max_length=12)
    desired_paper_count: int = Field(ge=1, le=8)
    rationale_summary: str | None = Field(default=None, max_length=600)


class PaperCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    title: str = Field(min_length=1)
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    year: int | None = None
    published_at: datetime | None = None
    arxiv_id: str | None = None
    doi: str | None = None
    canonical_url: str | None = None
    pdf_url: str | None = None
    discovery_provider: str
    discovery_query: str
    discovery_rank: int = Field(ge=1)
    ranking_score: float | None = None
    selected: bool = False
    ingestion_status: str = "NOT_STARTED"
    paper_id: str | None = None
    error: str | None = None


class ResearchRunEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    research_run_id: str
    event_type: str
    message: str
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    attempt_id: str | None = None
    sequence: int | None = None


class ResearchAttemptSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: str
    research_run_id: str
    worker_id: str
    attempt_number: int
    status: ResearchAttemptStatus
    claimed_at: datetime
    lease_expires_at: datetime
    heartbeat_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    next_retry_at: datetime | None = None
    retryable: bool | None = None
    error_class: str | None = None
    error_message: str | None = None


class ResearchCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sufficient: bool = False
    covered_concepts: list[str] = Field(default_factory=list)
    missing_concepts: list[str] = Field(default_factory=list)
    relevant_paper_ids: list[str] = Field(default_factory=list)
    evidence_count: int = Field(ge=0)
    summary: str = ""


class ResearchClaimOrigin(str, Enum):
    AUTHOR_EXPLICIT = "AUTHOR_EXPLICIT"
    CROSS_PAPER_INFERRED = "CROSS_PAPER_INFERRED"
    MODEL_INFERRED = "MODEL_INFERRED"


class ResearchEvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str
    document_id: str
    evidence_id: str


class ResearchReportClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    statement: str = Field(min_length=1)
    source_papers: list[str] = Field(default_factory=list)
    evidence_refs: list[ResearchEvidenceRef] = Field(default_factory=list)
    origin: ResearchClaimOrigin
    verification_status: str = "UNVERIFIED"


class ResearchTheme(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    summary: str
    claims: list[ResearchReportClaim] = Field(default_factory=list)


class ResearchMethodSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str
    method: str
    evidence_refs: list[ResearchEvidenceRef] = Field(default_factory=list)


class ResearchContradiction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    topic: str
    claim_a: str
    evidence_a: list[ResearchEvidenceRef] = Field(default_factory=list)
    claim_b: str
    evidence_b: list[ResearchEvidenceRef] = Field(default_factory=list)
    contradiction_type: str
    explanation: str
    verification_status: str = "UNVERIFIED"


class ResearchGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    statement: str
    evidence_refs: list[ResearchEvidenceRef] = Field(default_factory=list)
    origin: ResearchClaimOrigin = ResearchClaimOrigin.CROSS_PAPER_INFERRED
    verification_status: str = "UNVERIFIED"


class ResearchPaperSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    why_selected: str
    ingestion_status: str
    analysis_status: str
    verification_status: str


class ResearchReportIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_question: str
    executive_summary: list[ResearchReportClaim] = Field(default_factory=list)
    themes: list[ResearchTheme] = Field(default_factory=list)
    methods: list[ResearchMethodSummary] = Field(default_factory=list)
    agreements: list[ResearchReportClaim] = Field(default_factory=list)
    contradictions: list[ResearchContradiction] = Field(default_factory=list)
    research_gaps: list[ResearchGap] = Field(default_factory=list)
    limitations: list[ResearchReportClaim] = Field(default_factory=list)
    future_directions: list[ResearchReportClaim] = Field(default_factory=list)
    papers: list[ResearchPaperSummary] = Field(default_factory=list)
    coverage: ResearchCoverage
    discovery_queries: list[str] = Field(default_factory=list)
    candidate_count: int = Field(ge=0)
    selected_count: int = Field(ge=0)


class ResearchRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run: ResearchRun
    plan: ResearchPlan | None = None
    queries: list[str] = Field(default_factory=list)
    candidates: list[PaperCandidate] = Field(default_factory=list)
    events: list[ResearchRunEvent] = Field(default_factory=list)
    coverage: ResearchCoverage | None = None
    report: ResearchReportIR | None = None
    attempt: ResearchAttemptSummary | None = None
