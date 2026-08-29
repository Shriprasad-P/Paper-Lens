"""SQLAlchemy persistence boundary for normalized papers."""

from __future__ import annotations

import json
import logging
import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, UniqueConstraint, create_engine, event, select, or_
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError, OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload, sessionmaker
from sqlalchemy.pool import StaticPool

from ..ingestion.errors import PaperPersistenceError
from ..models.document import (
    Evidence,
    EvidenceType,
    PaperEquation,
    PaperFigure,
    PaperReference,
    PaperTable,
    PaperParagraph,
    PaperSection,
    SourceRegion,
    StructuredDocument,
)
from ..models.document import PaperIR
from ..models.paper import IngestedPaper, PaperMetadata, ParsedSection
from ..models.verification import VerificationResult
from ..models.chat import ChatMessage, ChatMessageStatus, ChatRole, ChatSession
from ..models.research import (
    PaperCandidate,
    ResearchPlan,
    ResearchReportIR,
    ResearchRun,
    ResearchRunEvent,
    ResearchRunStatus,
    ResearchExecutionState,
    ResearchAttemptStatus,
    ExecutionClaim,
    ResearchAttemptSummary,
    Workspace,
    WorkspacePaper,
    WorkspacePaperView,
)
from ..models.auth import User
from ..retrieval.embeddings import EmbeddingProvider

LEGACY_OWNER_ID = "user_legacy_local"
logger = logging.getLogger("paperlens.auth")


class Database(Protocol):
    def healthcheck(self) -> bool:
        """Return whether the backing store can execute a trivial query."""


class Base(DeclarativeBase):
    pass


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SessionRecord(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLogRecord(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    event_metadata: Mapped[dict[str, object]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class PaperRecord(Base):
    __tablename__ = "papers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(32), default="arxiv")
    source_identity: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True, default=LEGACY_OWNER_ID)
    arxiv_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    authors: Mapped[list[str]] = mapped_column(JSON, default=list)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    arxiv_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    sections: Mapped[list["PaperSectionRecord"]] = relationship(
        back_populates="paper", cascade="all, delete-orphan", order_by="PaperSectionRecord.order"
    )


class PaperSectionRecord(Base):
    __tablename__ = "paper_sections"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text)
    order: Mapped[int] = mapped_column()
    text: Mapped[str] = mapped_column(Text)
    paper: Mapped[PaperRecord] = relationship(back_populates="sections")


class DocumentRecord(Base):
    __tablename__ = "structured_documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), unique=True, index=True)
    page_count: Mapped[int | None] = mapped_column(nullable=True)
    parser_name: Mapped[str] = mapped_column(String(64))
    parser_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    sections: Mapped[list["DocumentSectionRecord"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentSectionRecord.order"
    )
    evidence: Mapped[list["EvidenceRecord"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="EvidenceRecord.id"
    )
    artifacts: Mapped[list["ArtifactRecord"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="ArtifactRecord.id"
    )


class DocumentSectionRecord(Base):
    __tablename__ = "structured_document_sections"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("structured_documents.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text)
    level: Mapped[int] = mapped_column()
    order: Mapped[int] = mapped_column()
    parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    page_start: Mapped[int | None] = mapped_column(nullable=True)
    page_end: Mapped[int | None] = mapped_column(nullable=True)
    document: Mapped[DocumentRecord] = relationship(back_populates="sections")
    paragraphs: Mapped[list["DocumentParagraphRecord"]] = relationship(
        back_populates="section", cascade="all, delete-orphan", order_by="DocumentParagraphRecord.order"
    )


class DocumentParagraphRecord(Base):
    __tablename__ = "structured_document_paragraphs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    section_id: Mapped[str] = mapped_column(ForeignKey("structured_document_sections.id", ondelete="CASCADE"), index=True)
    order: Mapped[int] = mapped_column()
    text: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    region_page: Mapped[int | None] = mapped_column(nullable=True)
    x0: Mapped[float | None] = mapped_column(nullable=True)
    y0: Mapped[float | None] = mapped_column(nullable=True)
    x1: Mapped[float | None] = mapped_column(nullable=True)
    y1: Mapped[float | None] = mapped_column(nullable=True)
    section: Mapped[DocumentSectionRecord] = relationship(back_populates="paragraphs")


class EvidenceRecord(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("structured_documents.id", ondelete="CASCADE"), index=True)
    evidence_type: Mapped[str] = mapped_column(String(32))
    source_text: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(nullable=True)
    section_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    paragraph_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    figure_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    table_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    equation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    region_page: Mapped[int | None] = mapped_column(nullable=True)
    x0: Mapped[float | None] = mapped_column(nullable=True)
    y0: Mapped[float | None] = mapped_column(nullable=True)
    x1: Mapped[float | None] = mapped_column(nullable=True)
    y1: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    document: Mapped[DocumentRecord] = relationship(back_populates="evidence")


class ArtifactRecord(Base):
    __tablename__ = "document_artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("structured_documents.id", ondelete="CASCADE"), index=True)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    document: Mapped[DocumentRecord] = relationship(back_populates="artifacts")


class EvidenceEmbeddingRecord(Base):
    __tablename__ = "evidence_embeddings"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(64), index=True)
    paper_id: Mapped[str] = mapped_column(String(64), index=True)
    document_id: Mapped[str] = mapped_column(String(64), index=True)
    embedding_model: Mapped[str] = mapped_column(String(128))
    embedding_version: Mapped[str] = mapped_column(String(32))
    dimension: Mapped[int] = mapped_column()
    vector: Mapped[list[float]] = mapped_column(JSON)
    evidence_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class WorkspaceRecord(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True, default=LEGACY_OWNER_ID)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    papers: Mapped[list["WorkspacePaperRecord"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan", order_by="WorkspacePaperRecord.added_at"
    )


class WorkspacePaperRecord(Base):
    __tablename__ = "workspace_papers"
    __table_args__ = (UniqueConstraint("workspace_id", "paper_id", name="uq_workspace_paper"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), index=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    workspace: Mapped[WorkspaceRecord] = relationship(back_populates="papers")


class ResearchRunRecord(Base):
    __tablename__ = "research_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True, default=LEGACY_OWNER_ID)
    workspace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    research_question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_iterations: Mapped[int] = mapped_column()
    max_candidates: Mapped[int] = mapped_column()
    max_ingested_papers: Mapped[int] = mapped_column()
    planner_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    planner_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(32))
    schema_version: Mapped[str] = mapped_column(String(32))
    execution_state: Mapped[str] = mapped_column(String(32), default=ResearchExecutionState.IDLE.value, index=True)
    active_attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    attempt_count: Mapped[int] = mapped_column(default=0)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class ResearchExecutionAttemptRecord(Base):
    __tablename__ = "research_execution_attempts"
    __table_args__ = (UniqueConstraint("research_run_id", "attempt_number", name="uq_research_attempt_number"),)

    attempt_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    research_run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    worker_id: Mapped[str] = mapped_column(String(128), index=True)
    claim_token_hash: Mapped[str] = mapped_column(String(64))
    attempt_number: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String(32), index=True)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retryable: Mapped[bool | None] = mapped_column(nullable=True)
    error_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class ResearchRunPlanRecord(Base):
    __tablename__ = "research_run_plans"

    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"), primary_key=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ResearchRunQueryRecord(Base):
    __tablename__ = "research_run_queries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"), index=True)
    query: Mapped[str] = mapped_column(Text)
    iteration: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ResearchRunCandidateRecord(Base):
    __tablename__ = "research_run_candidates"
    __table_args__ = (UniqueConstraint("run_id", "candidate_id", name="uq_research_run_candidate"),)

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    ranking_score: Mapped[float | None] = mapped_column(nullable=True)
    selected: Mapped[bool] = mapped_column(default=False)
    ingestion_status: Mapped[str] = mapped_column(String(32), default="NOT_STARTED")
    paper_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ResearchRunEventRecord(Base):
    __tablename__ = "research_run_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    event_metadata: Mapped[dict[str, object]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    sequence: Mapped[int | None] = mapped_column(nullable=True)


class ResearchRunReportRecord(Base):
    __tablename__ = "research_run_reports"

    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"), primary_key=True)
    coverage: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AnalysisRecord(Base):
    __tablename__ = "paper_analyses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), unique=True, index=True)
    document_id: Mapped[str] = mapped_column(String(64))
    document_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(32))
    schema_version: Mapped[str] = mapped_column(String(32))
    cache_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class VerificationRecord(Base):
    __tablename__ = "claim_verifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), index=True)
    claim_id: Mapped[str] = mapped_column(String(128), index=True)
    document_id: Mapped[str] = mapped_column(String(64))
    document_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claim_hash: Mapped[str] = mapped_column(String(64))
    evidence_hash: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(32))
    schema_version: Mapped[str] = mapped_column(String(32))
    cache_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ChatSessionRecord(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True, default=LEGACY_OWNER_ID)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str] = mapped_column(String(64), index=True)
    document_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ChatMessageRecord(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    citation_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    sufficient_evidence: Mapped[bool | None] = mapped_column(nullable=True)
    document_id: Mapped[str] = mapped_column(String(64))
    retrieval_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    retrieval_scores: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    retriever_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class IdempotencyRecord(Base):
    """Small durable response cache for safe client retries on mutating routes."""

    __tablename__ = "idempotency_records"

    scope_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), index=True)
    response_payload: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class SQLDatabase:
    """Synchronous SQLAlchemy adapter used by the async service boundary."""

    def __init__(
        self,
        database_url: str = "sqlite:///./paperlens.db",
        *,
        engine: Engine | None = None,
        create_schema: bool = True,
        pool_size: int = 5,
        max_overflow: int = 5,
        pool_timeout: float = 30.0,
    ) -> None:
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        engine_kwargs: dict[str, object] = {"future": True, "connect_args": connect_args, "pool_pre_ping": True}
        if database_url.startswith(("postgresql", "postgres:")):
            engine_kwargs.update(pool_size=pool_size, max_overflow=max_overflow, pool_timeout=pool_timeout)
        if database_url in {"sqlite://", "sqlite:///:memory:"}:
            engine_kwargs["poolclass"] = StaticPool
        self.engine = engine or create_engine(database_url, **engine_kwargs)
        if self.engine.dialect.name == "sqlite":
            event.listen(self.engine, "connect", _configure_sqlite_connection)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)
        if create_schema:
            self.create_tables()

    def create_tables(self) -> None:
        Base.metadata.create_all(self.engine)
        self.ensure_local_user(LEGACY_OWNER_ID, "local@paperlens.invalid")

    def healthcheck(self) -> bool:
        try:
            with self.session_factory() as session:
                return session.execute(select(1)).scalar_one() == 1
        except SQLAlchemyError:
            return False

    def ensure_local_user(self, user_id: str, email: str) -> User:
        """Create or return a trusted local principal used by development/desktop mode."""

        try:
            with self.session_factory.begin() as session:
                record = session.get(UserRecord, user_id)
                if record is None:
                    record = UserRecord(id=user_id, email=email, password_hash=None)
                    session.add(record)
                    session.flush()
                return _to_user(record)
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The local account could not be initialized.") from exc

    def create_user(self, user_id: str, email: str, password_hash: str) -> User:
        try:
            with self.session_factory.begin() as session:
                record = UserRecord(id=user_id, email=email, password_hash=password_hash)
                session.add(record)
                session.flush()
                return _to_user(record)
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The account could not be created.") from exc

    def get_user_by_email(self, email: str) -> tuple[User, str] | None:
        with self.session_factory() as session:
            record = session.scalar(select(UserRecord).where(UserRecord.email == email))
            if record is None or record.disabled_at is not None:
                return None
            return _to_user(record), record.password_hash or ""

    def get_user_by_session_hash(self, token_hash: str) -> User | None:
        now = datetime.now(timezone.utc)
        with self.session_factory.begin() as session:
            record = session.scalar(
                select(SessionRecord).where(
                    SessionRecord.token_hash == token_hash,
                    SessionRecord.revoked_at.is_(None),
                    SessionRecord.expires_at > now,
                )
            )
            if record is None:
                return None
            record.last_seen_at = now
            user = session.get(UserRecord, record.user_id)
            if user is None or user.disabled_at is not None:
                return None
            return _to_user(user)

    def create_session(
        self,
        *,
        session_id: str,
        user_id: str,
        token_hash: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        try:
            with self.session_factory.begin() as session:
                if session.get(UserRecord, user_id) is None:
                    raise PaperPersistenceError("The account was not found.")
                session.add(
                    SessionRecord(
                        id=session_id,
                        user_id=user_id,
                        token_hash=token_hash,
                        created_at=created_at,
                        expires_at=expires_at,
                        last_seen_at=created_at,
                    )
                )
        except PaperPersistenceError:
            raise
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The session could not be saved.") from exc

    def revoke_session(self, token_hash: str) -> bool:
        try:
            with self.session_factory.begin() as session:
                record = session.scalar(select(SessionRecord).where(SessionRecord.token_hash == token_hash))
                if record is None or record.revoked_at is not None:
                    return False
                record.revoked_at = datetime.now(timezone.utc)
                return True
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The session could not be revoked.") from exc

    def record_audit_event(self, *, event: str, user_id: str | None, metadata: dict[str, object]) -> None:
        try:
            with self.session_factory.begin() as session:
                session.add(
                    AuditLogRecord(
                        id=f"audit_{uuid4().hex}",
                        event=event,
                        user_id=user_id,
                        event_metadata=dict(metadata),
                        created_at=datetime.now(timezone.utc),
                    )
                )
        except SQLAlchemyError:
            logger.warning(json.dumps({"event": "audit_write_failed", "audit_event": event}, separators=(",", ":")))

    def recover_incomplete_work(self) -> dict[str, int]:
        """Recover expired durable attempts without resurrecting terminal work."""

        interrupted_papers = 0
        interrupted_runs = 0
        active_paper_states = {"PENDING", "FETCHING_METADATA", "DOWNLOADING", "PARSING", "PARSED"}
        active_run_states = {
            ResearchRunStatus.CREATED.value,
            ResearchRunStatus.PLANNING.value,
            ResearchRunStatus.DISCOVERING.value,
            ResearchRunStatus.SELECTING.value,
            ResearchRunStatus.INGESTING.value,
            ResearchRunStatus.ANALYZING.value,
            ResearchRunStatus.SYNTHESIZING.value,
            ResearchRunStatus.VERIFYING.value,
        }
        try:
            with self.session_factory.begin() as session:
                now = datetime.now(timezone.utc)
                expired = session.scalars(
                    select(ResearchExecutionAttemptRecord).where(
                        ResearchExecutionAttemptRecord.status.in_((ResearchAttemptStatus.CLAIMED.value, ResearchAttemptStatus.RUNNING.value)),
                        ResearchExecutionAttemptRecord.lease_expires_at <= now,
                    )
                ).all()
                for attempt in expired:
                    attempt.status = ResearchAttemptStatus.LOST.value
                    attempt.completed_at = now
                    attempt.error_class = "LEASE_EXPIRED"
                    attempt.error_message = "Worker lease expired before the attempt completed."
                    run = session.get(ResearchRunRecord, attempt.research_run_id)
                    if run is None or run.execution_state in {
                        ResearchExecutionState.COMPLETED.value,
                        ResearchExecutionState.CANCELLED.value,
                        ResearchExecutionState.FAILED.value,
                    }:
                        continue
                    run.active_attempt_id = None
                    run.updated_at = now
                    if run.cancel_requested_at is not None:
                        run.execution_state = ResearchExecutionState.CANCELLED.value
                        run.status = ResearchRunStatus.CANCELLED.value
                        run.completed_at = now
                    elif run.attempt_count < 3:
                        run.execution_state = ResearchExecutionState.QUEUED.value
                        run.next_attempt_at = now
                    else:
                        run.execution_state = ResearchExecutionState.FAILED.value
                        run.status = ResearchRunStatus.FAILED.value
                        run.completed_at = now
                    self._add_event_session(
                        session, run.id, "LEASE_EXPIRED", "The worker lease expired; the attempt was fenced.",
                        {"attempt_id": attempt.attempt_id, "attempt_number": attempt.attempt_number, "worker_id": attempt.worker_id},
                        attempt_id=attempt.attempt_id, created_at=now,
                    )
                papers = session.scalars(select(PaperRecord).where(PaperRecord.status.in_(active_paper_states))).all()
                for paper in papers:
                    paper.status = "FAILED"
                    paper.error_message = "Ingestion was interrupted before completion; retry explicitly."
                    interrupted_papers += 1
                runs = session.scalars(select(ResearchRunRecord).where(ResearchRunRecord.status.in_(active_run_states))).all()
                for run in runs:
                    # Legacy stage-only rows have no durable claim and are deliberately
                    # left diagnosable rather than silently resumed.
                    if run.execution_state != ResearchExecutionState.IDLE.value:
                        continue
                    run.status = ResearchRunStatus.INTERRUPTED.value
                    run.updated_at = now
                    run.completed_at = None
                    session.add(
                        ResearchRunEventRecord(
                            id=f"event_{uuid4().hex}",
                            run_id=run.id,
                            event_type="RUN_INTERRUPTED",
                            message="The process restarted before this run completed; resume explicitly.",
                            event_metadata={"recoverable": True},
                            created_at=now,
                            sequence=self._next_event_sequence(session, run.id),
                        )
                    )
                    interrupted_runs += 1
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("Interrupted work could not be recovered safely.") from exc
        return {"papers": interrupted_papers, "research_runs": interrupted_runs}

    def queue_research_run(self, run_id: str, owner_id: str = LEGACY_OWNER_ID) -> ResearchRun | None:
        """Durably enqueue a run. Repeated requests are idempotent."""

        try:
            with self.session_factory.begin() as session:
                if self.engine.dialect.name == "sqlite":
                    self._begin_claim_transaction(session)
                run = session.scalar(
                    select(ResearchRunRecord).where(ResearchRunRecord.id == run_id, ResearchRunRecord.owner_id == owner_id).with_for_update()
                )
                if run is None:
                    return None
                if run.execution_state in {
                    ResearchExecutionState.COMPLETED.value,
                    ResearchExecutionState.FAILED.value,
                    ResearchExecutionState.CANCELLED.value,
                } or run.cancel_requested_at is not None:
                    return _to_research_run(run)
                if run.execution_state in {ResearchExecutionState.CLAIMED.value, ResearchExecutionState.RUNNING.value}:
                    active = session.get(ResearchExecutionAttemptRecord, run.active_attempt_id) if run.active_attempt_id else None
                    if active and _as_utc(active.lease_expires_at) > datetime.now(timezone.utc):
                        return _to_research_run(run)
                if run.execution_state == ResearchExecutionState.QUEUED.value:
                    return _to_research_run(run)
                now = datetime.now(timezone.utc)
                run.execution_state = ResearchExecutionState.QUEUED.value
                run.next_attempt_at = now
                run.updated_at = now
                self._add_event_session(session, run.id, "QUEUED", "Research run queued for durable execution.", {}, created_at=now)
                return _to_research_run(run)
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The research run could not be queued.") from exc

    def claim_research_run(
        self,
        run_id: str,
        worker_id: str,
        *,
        lease_seconds: int = 60,
        owner_id: str | None = None,
    ) -> ExecutionClaim | None:
        """Atomically claim one queued run, fencing any expired owner."""

        try:
            with self.session_factory.begin() as session:
                self._begin_claim_transaction(session)
                query = select(ResearchRunRecord).where(ResearchRunRecord.id == run_id)
                if owner_id is not None:
                    query = query.where(ResearchRunRecord.owner_id == owner_id)
                run = session.scalar(query.with_for_update())
                if run is None:
                    return None
                now = datetime.now(timezone.utc)
                self._recover_expired_attempts_session(session, now, 3)
                session.expire(run)
                run = session.scalar(query.with_for_update())
                if run.cancel_requested_at is not None or run.execution_state in {
                    ResearchExecutionState.COMPLETED.value,
                    ResearchExecutionState.FAILED.value,
                    ResearchExecutionState.CANCELLED.value,
                }:
                    return None
                if run.execution_state in {ResearchExecutionState.CLAIMED.value, ResearchExecutionState.RUNNING.value}:
                    active = session.get(ResearchExecutionAttemptRecord, run.active_attempt_id) if run.active_attempt_id else None
                    if active and _as_utc(active.lease_expires_at) > now:
                        return None
                    if active:
                        active.status = ResearchAttemptStatus.LOST.value
                        active.completed_at = now
                        active.error_class = "LEASE_EXPIRED"
                        active.error_message = "Worker lease expired before the attempt completed."
                        self._add_event_session(session, run.id, "LEASE_EXPIRED", "The expired worker claim was fenced.", {}, attempt_id=active.attempt_id, created_at=now)
                    run.active_attempt_id = None
                if run.execution_state not in {ResearchExecutionState.QUEUED.value, ResearchExecutionState.IDLE.value}:
                    return None
                if run.next_attempt_at is not None and _as_utc(run.next_attempt_at) > now:
                    return None
                token = secrets.token_urlsafe(32)
                attempt_number = int(run.attempt_count or 0) + 1
                attempt_id = f"attempt_{uuid4().hex}"
                expires = now + timedelta(seconds=max(5, int(lease_seconds)))
                attempt = ResearchExecutionAttemptRecord(
                    attempt_id=attempt_id,
                    research_run_id=run.id,
                    owner_id=run.owner_id,
                    worker_id=worker_id[:128],
                    claim_token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
                    attempt_number=attempt_number,
                    status=ResearchAttemptStatus.CLAIMED.value,
                    claimed_at=now,
                    lease_expires_at=expires,
                    heartbeat_at=now,
                )
                session.add(attempt)
                run.active_attempt_id = attempt_id
                run.attempt_count = attempt_number
                run.execution_state = ResearchExecutionState.CLAIMED.value
                run.updated_at = now
                run.next_attempt_at = None
                self._add_event_session(session, run.id, "CLAIMED", "A worker claimed the research run.", {"attempt_number": attempt_number, "worker_id": worker_id[:128]}, attempt_id=attempt_id, created_at=now)
                return ExecutionClaim(run.id, attempt_id, worker_id[:128], token, attempt_number, expires)
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The research run could not be claimed.") from exc

    def claim_next_research_run(self, worker_id: str, *, lease_seconds: int = 60, max_attempts: int = 3) -> ExecutionClaim | None:
        """Claim the oldest eligible work item with a database transaction."""

        # SQLite serializes the writer transaction; PostgreSQL uses SKIP LOCKED
        # so independent workers never wait behind an already claimed row.
        try:
            with self.session_factory.begin() as session:
                self._begin_claim_transaction(session)
                now = datetime.now(timezone.utc)
                self._recover_expired_attempts_session(session, now, max_attempts)
                query = (
                    select(ResearchRunRecord)
                    .where(
                        ResearchRunRecord.execution_state == ResearchExecutionState.QUEUED.value,
                        ResearchRunRecord.cancel_requested_at.is_(None),
                        ResearchRunRecord.attempt_count < max(1, int(max_attempts)),
                        or_(ResearchRunRecord.next_attempt_at.is_(None), ResearchRunRecord.next_attempt_at <= now),
                    )
                    .order_by(ResearchRunRecord.created_at, ResearchRunRecord.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                run = session.scalar(query)
                if run is None:
                    return None
                token = secrets.token_urlsafe(32)
                attempt_number = int(run.attempt_count or 0) + 1
                attempt_id = f"attempt_{uuid4().hex}"
                expires = now + timedelta(seconds=max(5, int(lease_seconds)))
                session.add(ResearchExecutionAttemptRecord(
                    attempt_id=attempt_id, research_run_id=run.id, owner_id=run.owner_id,
                    worker_id=worker_id[:128], claim_token_hash=hashlib.sha256(token.encode()).hexdigest(),
                    attempt_number=attempt_number, status=ResearchAttemptStatus.CLAIMED.value,
                    claimed_at=now, lease_expires_at=expires, heartbeat_at=now,
                ))
                run.active_attempt_id = attempt_id
                run.attempt_count = attempt_number
                run.execution_state = ResearchExecutionState.CLAIMED.value
                run.updated_at = now
                run.next_attempt_at = None
                self._add_event_session(session, run.id, "CLAIMED", "A worker claimed the research run.", {"attempt_number": attempt_number, "worker_id": worker_id[:128]}, attempt_id=attempt_id, created_at=now)
                return ExecutionClaim(run.id, attempt_id, worker_id[:128], token, attempt_number, expires)
        except OperationalError:
            # SQLite has one writer; another polling worker simply retries on
            # its next poll instead of surfacing a transient lock as a failure.
            return None
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The next research run could not be claimed.") from exc

    def _claim_record(self, session: object, claim: ExecutionClaim, *, now: datetime | None = None) -> tuple[ResearchRunRecord, ResearchExecutionAttemptRecord] | None:
        now = now or datetime.now(timezone.utc)
        attempt = session.scalar(select(ResearchExecutionAttemptRecord).where(ResearchExecutionAttemptRecord.attempt_id == claim.attempt_id))
        run = session.scalar(select(ResearchRunRecord).where(ResearchRunRecord.id == claim.run_id))
        if attempt is None or run is None or run.active_attempt_id != claim.attempt_id or attempt.research_run_id != claim.run_id:
            return None
        if attempt.claim_token_hash != hashlib.sha256(claim.token.encode()).hexdigest() or _as_utc(attempt.lease_expires_at) <= now:
            return None
        if attempt.status not in {ResearchAttemptStatus.CLAIMED.value, ResearchAttemptStatus.RUNNING.value}:
            return None
        if run.execution_state not in {ResearchExecutionState.CLAIMED.value, ResearchExecutionState.RUNNING.value, ResearchExecutionState.CANCEL_REQUESTED.value}:
            return None
        return run, attempt

    def _recover_expired_attempts_session(self, session: object, now: datetime, max_attempts: int) -> int:
        recovered = 0
        expired = session.scalars(select(ResearchExecutionAttemptRecord).where(ResearchExecutionAttemptRecord.status.in_((ResearchAttemptStatus.CLAIMED.value, ResearchAttemptStatus.RUNNING.value)), ResearchExecutionAttemptRecord.lease_expires_at <= now)).all()
        for attempt in expired:
            run = session.get(ResearchRunRecord, attempt.research_run_id)
            attempt.status = ResearchAttemptStatus.LOST.value
            attempt.completed_at = now
            attempt.error_class = "LEASE_EXPIRED"
            attempt.error_message = "Worker lease expired before the attempt completed."
            if run is None or run.active_attempt_id != attempt.attempt_id:
                continue
            run.active_attempt_id = None
            run.updated_at = now
            if run.cancel_requested_at is not None:
                run.execution_state = ResearchExecutionState.CANCELLED.value
                run.status = ResearchRunStatus.CANCELLED.value
                run.completed_at = now
            elif attempt.attempt_number < max(1, int(max_attempts)):
                run.execution_state = ResearchExecutionState.QUEUED.value
                run.next_attempt_at = now
            else:
                run.execution_state = ResearchExecutionState.FAILED.value
                run.status = ResearchRunStatus.FAILED.value
                run.completed_at = now
            self._add_event_session(session, run.id, "LEASE_EXPIRED", "The worker lease expired; work is eligible for recovery.", {"attempt_id": attempt.attempt_id, "worker_id": attempt.worker_id}, attempt_id=attempt.attempt_id, created_at=now)
            recovered += 1
        return recovered

    def _begin_claim_transaction(self, session: object) -> None:
        """Take SQLite's single writer lock before selecting an eligible run."""

        if self.engine.dialect.name == "sqlite":
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")

    def execution_claim_valid(self, claim: ExecutionClaim) -> bool:
        with self.session_factory() as session:
            return self._claim_record(session, claim) is not None

    def mark_attempt_running(self, claim: ExecutionClaim) -> bool:
        try:
            with self.session_factory.begin() as session:
                pair = self._claim_record(session, claim)
                if pair is None:
                    return False
                run, attempt = pair
                now = datetime.now(timezone.utc)
                attempt.status = ResearchAttemptStatus.RUNNING.value
                attempt.started_at = attempt.started_at or now
                attempt.heartbeat_at = now
                run.execution_state = ResearchExecutionState.RUNNING.value
                run.updated_at = now
                self._add_event_session(session, run.id, "ATTEMPT_STARTED", "The worker started the research attempt.", {"attempt_number": attempt.attempt_number, "worker_id": attempt.worker_id}, attempt_id=attempt.attempt_id, created_at=now)
                return True
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The research attempt could not be started.") from exc

    def renew_execution_lease(self, claim: ExecutionClaim, *, lease_seconds: int = 60) -> bool:
        try:
            with self.session_factory.begin() as session:
                pair = self._claim_record(session, claim)
                if pair is None:
                    return False
                run, attempt = pair
                now = datetime.now(timezone.utc)
                attempt.heartbeat_at = now
                attempt.lease_expires_at = now + timedelta(seconds=max(5, int(lease_seconds)))
                run.updated_at = now
                self._add_event_session(session, run.id, "LEASE_RENEWED", "The worker heartbeat renewed its lease.", {"worker_id": attempt.worker_id}, attempt_id=attempt.attempt_id, created_at=now)
                return True
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The research lease could not be renewed.") from exc

    def request_research_cancellation(self, run_id: str, owner_id: str = LEGACY_OWNER_ID) -> ResearchRun | None:
        try:
            with self.session_factory.begin() as session:
                run = session.scalar(select(ResearchRunRecord).where(ResearchRunRecord.id == run_id, ResearchRunRecord.owner_id == owner_id).with_for_update())
                if run is None:
                    return None
                if run.execution_state in {ResearchExecutionState.COMPLETED.value, ResearchExecutionState.FAILED.value, ResearchExecutionState.CANCELLED.value}:
                    return _to_research_run(run)
                now = datetime.now(timezone.utc)
                run.cancel_requested_at = run.cancel_requested_at or now
                run.updated_at = now
                if run.active_attempt_id is None or run.execution_state == ResearchExecutionState.QUEUED.value:
                    run.execution_state = ResearchExecutionState.CANCELLED.value
                    run.status = ResearchRunStatus.CANCELLED.value
                    run.completed_at = now
                else:
                    run.execution_state = ResearchExecutionState.CANCEL_REQUESTED.value
                self._add_event_session(session, run.id, "CANCELLATION_REQUESTED", "Cancellation was durably requested.", {}, attempt_id=run.active_attempt_id, created_at=now)
                return _to_research_run(run)
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The research run could not be cancelled.") from exc

    def complete_execution(self, claim: ExecutionClaim, *, status: ResearchRunStatus = ResearchRunStatus.COMPLETED) -> bool:
        try:
            with self.session_factory.begin() as session:
                pair = self._claim_record(session, claim)
                if pair is None:
                    return False
                run, attempt = pair
                now = datetime.now(timezone.utc)
                if run.cancel_requested_at is not None or run.execution_state == ResearchExecutionState.CANCEL_REQUESTED.value:
                    attempt.status = ResearchAttemptStatus.CANCELLED.value
                    run.execution_state = ResearchExecutionState.CANCELLED.value
                    run.status = ResearchRunStatus.CANCELLED.value
                    self._add_event_session(session, run.id, "CANCELLED", "The attempt stopped at a cancellation boundary.", {}, attempt_id=attempt.attempt_id, created_at=now)
                else:
                    attempt.status = ResearchAttemptStatus.SUCCEEDED.value
                    run.execution_state = ResearchExecutionState.COMPLETED.value
                    run.status = status.value
                    self._add_event_session(session, run.id, "COMPLETED", "The research attempt completed.", {}, attempt_id=attempt.attempt_id, created_at=now)
                attempt.completed_at = now
                run.active_attempt_id = None
                run.completed_at = now
                run.updated_at = now
                return True
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The research execution could not be completed.") from exc

    def fail_execution(self, claim: ExecutionClaim, *, error_class: str, error_message: str, retryable: bool, max_attempts: int = 3) -> bool:
        try:
            with self.session_factory.begin() as session:
                pair = self._claim_record(session, claim)
                if pair is None:
                    return False
                run, attempt = pair
                now = datetime.now(timezone.utc)
                attempt.status = ResearchAttemptStatus.FAILED.value
                attempt.completed_at = now
                attempt.retryable = bool(retryable)
                attempt.error_class = error_class[:64]
                attempt.error_message = error_message[:500]
                run.active_attempt_id = None
                run.updated_at = now
                self._add_event_session(session, run.id, "ATTEMPT_FAILED", "The worker attempt failed.", {"error_class": error_class[:64], "retryable": bool(retryable), "attempt_number": attempt.attempt_number}, attempt_id=attempt.attempt_id, created_at=now)
                if run.cancel_requested_at is not None:
                    run.execution_state = ResearchExecutionState.CANCELLED.value
                    run.status = ResearchRunStatus.CANCELLED.value
                    run.completed_at = now
                elif retryable and attempt.attempt_number < max(1, int(max_attempts)):
                    delay = min(300, 2 ** max(0, attempt.attempt_number - 1))
                    run.execution_state = ResearchExecutionState.QUEUED.value
                    run.next_attempt_at = now + timedelta(seconds=delay)
                    self._add_event_session(session, run.id, "RETRY_SCHEDULED", "A retry was scheduled after a retryable failure.", {"error_class": error_class[:64], "attempt_number": attempt.attempt_number, "next_retry_seconds": delay}, attempt_id=attempt.attempt_id, created_at=now)
                else:
                    run.execution_state = ResearchExecutionState.FAILED.value
                    run.status = ResearchRunStatus.FAILED.value
                    run.completed_at = now
                    self._add_event_session(session, run.id, "FAILED", "The research run failed safely.", {"error_class": error_class[:64], "retryable": bool(retryable)}, attempt_id=attempt.attempt_id, created_at=now)
                attempt.next_retry_at = run.next_attempt_at
                return True
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The research execution failure could not be recorded.") from exc

    def get_research_attempt(self, run_id: str, owner_id: str = LEGACY_OWNER_ID) -> ResearchAttemptSummary | None:
        with self.session_factory() as session:
            record = session.scalar(select(ResearchExecutionAttemptRecord).join(ResearchRunRecord, ResearchRunRecord.id == ResearchExecutionAttemptRecord.research_run_id).where(ResearchExecutionAttemptRecord.research_run_id == run_id, ResearchRunRecord.owner_id == owner_id).order_by(ResearchExecutionAttemptRecord.attempt_number.desc()))
            return _to_attempt_summary(record) if record else None

    def list_research_attempts(self, run_id: str, owner_id: str = LEGACY_OWNER_ID) -> list[ResearchAttemptSummary]:
        with self.session_factory() as session:
            records = session.scalars(
                select(ResearchExecutionAttemptRecord)
                .join(ResearchRunRecord, ResearchRunRecord.id == ResearchExecutionAttemptRecord.research_run_id)
                .where(ResearchExecutionAttemptRecord.research_run_id == run_id, ResearchRunRecord.owner_id == owner_id)
                .order_by(ResearchExecutionAttemptRecord.attempt_number)
            ).all()
            return [_to_attempt_summary(record) for record in records]

    def research_execution_metrics(self) -> dict[str, int]:
        """Small safe snapshot for local metrics/readiness diagnostics."""

        with self.session_factory() as session:
            values = session.scalars(select(ResearchRunRecord.execution_state)).all()
            attempts = session.scalars(select(ResearchExecutionAttemptRecord.status)).all()
        result = {"queued": 0, "active": 0, "completed": 0, "failed": 0, "cancelled": 0, "lease_expirations": 0, "retries": 0}
        for value in values:
            key = {ResearchExecutionState.QUEUED.value: "queued", ResearchExecutionState.CLAIMED.value: "active", ResearchExecutionState.RUNNING.value: "active", ResearchExecutionState.COMPLETED.value: "completed", ResearchExecutionState.FAILED.value: "failed", ResearchExecutionState.CANCELLED.value: "cancelled", ResearchExecutionState.CANCEL_REQUESTED.value: "active"}.get(value)
            if key:
                result[key] += 1
        result["lease_expirations"] = sum(1 for value in attempts if value == ResearchAttemptStatus.LOST.value)
        result["retries"] = max(0, len(attempts) - sum(1 for value in attempts if value in {ResearchAttemptStatus.SUCCEEDED.value, ResearchAttemptStatus.CANCELLED.value, ResearchAttemptStatus.LOST.value}))
        return result

    def _next_event_sequence(self, session: object, run_id: str) -> int:
        latest = session.scalar(select(ResearchRunEventRecord.sequence).where(ResearchRunEventRecord.run_id == run_id).order_by(ResearchRunEventRecord.sequence.desc().nullslast(), ResearchRunEventRecord.created_at.desc()).limit(1))
        return int(latest or 0) + 1

    def _add_event_session(self, session: object, run_id: str, event_type: str, message: str, metadata: dict[str, object], *, attempt_id: str | None = None, created_at: datetime | None = None, event_id: str | None = None) -> None:
        now = created_at or datetime.now(timezone.utc)
        session.add(ResearchRunEventRecord(id=event_id or f"event_{uuid4().hex}", run_id=run_id, event_type=event_type, message=message[:2000], event_metadata=dict(metadata), created_at=now, attempt_id=attempt_id, sequence=self._next_event_sequence(session, run_id)))

    def get_by_source_identity(self, source_identity: str, owner_id: str = LEGACY_OWNER_ID) -> IngestedPaper | None:
        with self.session_factory() as session:
            record = session.scalar(
                select(PaperRecord).where(
                    PaperRecord.source_identity.in_((source_identity, _scoped_source_identity(source_identity, owner_id))),
                    PaperRecord.owner_id == owner_id,
                )
            )
            return _to_model(record) if record and record.status == "COMPLETED" else None

    def get_by_id(self, paper_id: str, owner_id: str = LEGACY_OWNER_ID) -> IngestedPaper | None:
        with self.session_factory() as session:
            record = session.scalar(select(PaperRecord).where(PaperRecord.id == paper_id, PaperRecord.owner_id == owner_id))
            return _to_model(record) if record and record.status == "COMPLETED" else None

    def list_papers(self, owner_id: str = LEGACY_OWNER_ID) -> list[IngestedPaper]:
        with self.session_factory() as session:
            records = session.scalars(
                select(PaperRecord)
                .where(PaperRecord.status == "COMPLETED", PaperRecord.owner_id == owner_id)
                .order_by(PaperRecord.created_at)
            ).all()
            return [_to_model(record) for record in records]

    def create_placeholder(
        self, *, paper_id: str, source_identity: str, arxiv_id: str, owner_id: str = LEGACY_OWNER_ID
    ) -> None:
        try:
            with self.session_factory.begin() as session:
                record = session.scalar(
                    select(PaperRecord).where(PaperRecord.id == paper_id, PaperRecord.owner_id == owner_id)
                )
                if record is None:
                    session.add(
                        PaperRecord(
                            id=paper_id,
                            source_identity=_scoped_source_identity(source_identity, owner_id),
                            owner_id=owner_id,
                            arxiv_id=arxiv_id,
                            status="PENDING",
                        )
                    )
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The paper could not be saved.") from exc

    def save_metadata(
        self, paper_id: str, metadata: PaperMetadata, *, status: str, owner_id: str = LEGACY_OWNER_ID
    ) -> None:
        try:
            with self.session_factory.begin() as session:
                record = session.scalar(select(PaperRecord).where(PaperRecord.id == paper_id, PaperRecord.owner_id == owner_id))
                if record is None:
                    raise PaperPersistenceError("The paper could not be saved.")
                record.arxiv_id = metadata.arxiv_id
                record.title = metadata.title
                record.authors = metadata.authors
                record.abstract = metadata.abstract
                record.published_at = metadata.published_at
                record.arxiv_updated_at = metadata.updated_at
                record.categories = metadata.categories
                record.source_url = metadata.source_url
                record.pdf_url = metadata.pdf_url
                record.status = status
                record.error_message = None
        except PaperPersistenceError:
            raise
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The paper could not be saved.") from exc

    def save_parsed(
        self,
        paper_id: str,
        metadata: PaperMetadata,
        sections: list[ParsedSection],
        local_pdf_path: Path,
        owner_id: str = LEGACY_OWNER_ID,
        *,
        status: str = "COMPLETED",
    ) -> IngestedPaper:
        try:
            with self.session_factory.begin() as session:
                record = session.scalar(select(PaperRecord).where(PaperRecord.id == paper_id, PaperRecord.owner_id == owner_id))
                if record is None:
                    raise PaperPersistenceError("The paper could not be saved.")
                record.status = status
                record.local_pdf_path = str(local_pdf_path)
                record.error_message = None
                record.sections.clear()
                record.sections.extend(
                    PaperSectionRecord(title=section.title, order=section.order, text=section.text)
                    for section in sections
                )
                session.flush()
                return _to_model(record)
        except PaperPersistenceError:
            raise
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The paper could not be saved.") from exc

    def replace_document(
        self,
        document: StructuredDocument,
        evidence: list[Evidence],
        owner_id: str = LEGACY_OWNER_ID,
    ) -> None:
        """Replace one paper's normalized document and evidence in one transaction."""

        try:
            with self.session_factory.begin() as session:
                paper = session.scalar(
                    select(PaperRecord).where(PaperRecord.id == document.paper_id, PaperRecord.owner_id == owner_id)
                )
                if paper is None:
                    raise PaperPersistenceError("The paper could not be saved.")
                existing = session.scalar(
                    select(DocumentRecord)
                    .join(PaperRecord, PaperRecord.id == DocumentRecord.paper_id)
                    .where(DocumentRecord.paper_id == document.paper_id, PaperRecord.owner_id == owner_id)
                )
                _namespace_colliding_ids(session, document, evidence)
                if existing is not None:
                    session.delete(existing)
                    session.flush()

                record = DocumentRecord(
                    id=document.id,
                    paper_id=document.paper_id,
                    page_count=document.page_count,
                    parser_name=document.parser_name,
                    parser_version=document.parser_version,
                    source_hash=document.source_hash,
                    document_hash=document.document_hash,
                    created_at=document.created_at,
                )
                for section in document.sections:
                    section_record = DocumentSectionRecord(
                        id=section.id,
                        title=section.title,
                        level=section.level,
                        order=section.order,
                        parent_id=section.parent_id,
                        page_start=section.page_start,
                        page_end=section.page_end,
                    )
                    section_record.paragraphs.extend(
                        DocumentParagraphRecord(
                            id=paragraph.id,
                            order=paragraph.order,
                            text=paragraph.text,
                            page=paragraph.page,
                            content_hash=paragraph.content_hash,
                            evidence_id=paragraph.evidence_id,
                            **_region_columns(paragraph.source_region),
                        )
                        for paragraph in section.paragraphs
                    )
                    record.sections.append(section_record)
                record.evidence.extend(
                    EvidenceRecord(
                        id=item.id,
                        paper_id=item.paper_id,
                        document_id=item.document_id,
                        evidence_type=item.evidence_type.value,
                        source_text=item.source_text,
                        page=item.page,
                        section_id=item.section_id,
                        paragraph_id=item.paragraph_id,
                        figure_id=item.figure_id,
                        table_id=item.table_id,
                        equation_id=item.equation_id,
                        created_at=item.created_at,
                        **_region_columns(item.source_region),
                    )
                    for item in evidence
                )
                for kind, items in (
                    ("figure", document.figures),
                    ("table", document.tables),
                    ("equation", document.equations),
                    ("reference", document.references),
                ):
                    record.artifacts.extend(
                        ArtifactRecord(
                            id=f"{document.id}:{kind}:{item.id}",
                            document_id=document.id,
                            paper_id=document.paper_id,
                            kind=kind,
                            payload=item.model_dump(mode="json"),
                        )
                        for item in items
                    )
                session.add(record)
        except PaperPersistenceError:
            raise
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The structured document could not be saved.") from exc

    def get_document(self, paper_id: str, owner_id: str = LEGACY_OWNER_ID) -> StructuredDocument | None:
        with self.session_factory() as session:
            record = session.scalar(
                select(DocumentRecord)
                .options(
                    selectinload(DocumentRecord.sections).selectinload(DocumentSectionRecord.paragraphs),
                    selectinload(DocumentRecord.artifacts),
                )
                .join(PaperRecord, PaperRecord.id == DocumentRecord.paper_id)
                .where(DocumentRecord.paper_id == paper_id, PaperRecord.owner_id == owner_id)
            )
            paper = session.scalar(select(PaperRecord).where(PaperRecord.id == paper_id, PaperRecord.owner_id == owner_id))
            if record is None or paper is None or paper.title is None or paper.source_url is None or paper.pdf_url is None:
                return None
            return _to_document(record, paper)

    def get_evidence(self, paper_id: str, evidence_id: str, owner_id: str = LEGACY_OWNER_ID) -> Evidence | None:
        with self.session_factory() as session:
            record = session.scalar(
                select(EvidenceRecord)
                .join(PaperRecord, PaperRecord.id == EvidenceRecord.paper_id)
                .where(EvidenceRecord.paper_id == paper_id, EvidenceRecord.id == evidence_id, PaperRecord.owner_id == owner_id)
            )
            return _to_evidence(record) if record else None

    def get_evidence_many(
        self, paper_id: str, evidence_ids: list[str], owner_id: str = LEGACY_OWNER_ID
    ) -> dict[str, Evidence]:
        if not evidence_ids:
            return {}
        with self.session_factory() as session:
            records = session.scalars(
                select(EvidenceRecord)
                .join(PaperRecord, PaperRecord.id == EvidenceRecord.paper_id)
                .where(EvidenceRecord.paper_id == paper_id, EvidenceRecord.id.in_(evidence_ids), PaperRecord.owner_id == owner_id)
            ).all()
            return {record.id: _to_evidence(record) for record in records}

    def get_evidence_for_document(
        self, paper_id: str, document_id: str, owner_id: str = LEGACY_OWNER_ID
    ) -> list[Evidence]:
        with self.session_factory() as session:
            records = session.scalars(
                select(EvidenceRecord)
                .join(PaperRecord, PaperRecord.id == EvidenceRecord.paper_id)
                .where(EvidenceRecord.paper_id == paper_id, EvidenceRecord.document_id == document_id, PaperRecord.owner_id == owner_id)
                .order_by(EvidenceRecord.id)
            ).all()
            return [_to_evidence(record) for record in records]

    def get_embeddings(
        self,
        paper_id: str,
        document_id: str,
        embedding_model: str,
        embedding_version: str,
        owner_id: str = LEGACY_OWNER_ID,
    ) -> dict[str, tuple[list[float], str]]:
        with self.session_factory() as session:
            records = session.scalars(
                select(EvidenceEmbeddingRecord)
                .join(PaperRecord, PaperRecord.id == EvidenceEmbeddingRecord.paper_id)
                .where(
                    EvidenceEmbeddingRecord.paper_id == paper_id,
                    EvidenceEmbeddingRecord.document_id == document_id,
                    EvidenceEmbeddingRecord.embedding_model == embedding_model,
                    EvidenceEmbeddingRecord.embedding_version == embedding_version,
                    PaperRecord.owner_id == owner_id,
                )
            ).all()
            return {record.evidence_id: (list(record.vector or []), record.evidence_hash) for record in records}

    def save_embeddings(
        self,
        paper_id: str,
        document_id: str,
        provider: EmbeddingProvider,
        items: list[tuple[Evidence, list[float]]],
        owner_id: str = LEGACY_OWNER_ID,
    ) -> None:
        import hashlib

        try:
            with self.session_factory.begin() as session:
                if session.scalar(select(PaperRecord.id).where(PaperRecord.id == paper_id, PaperRecord.owner_id == owner_id)) is None:
                    raise PaperPersistenceError("The paper was not found.")
                for evidence, vector in items:
                    record_id = hashlib.sha256(
                        f"{paper_id}|{document_id}|{evidence.id}|{provider.model}|{provider.version}".encode("utf-8")
                    ).hexdigest()
                    values = {
                        "id": record_id,
                        "evidence_id": evidence.id,
                        "paper_id": paper_id,
                        "document_id": document_id,
                        "embedding_model": provider.model,
                        "embedding_version": provider.version,
                        "dimension": len(vector),
                        "vector": vector,
                        "evidence_hash": hashlib.sha256(evidence.source_text.encode("utf-8")).hexdigest(),
                        "created_at": datetime.now(timezone.utc),
                    }
                    existing = session.get(EvidenceEmbeddingRecord, record_id)
                    if existing is None:
                        session.add(EvidenceEmbeddingRecord(**values))
                    else:
                        for key, value in values.items():
                            setattr(existing, key, value)
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The evidence embeddings could not be saved.") from exc

    def create_chat_session(self, session: ChatSession, owner_id: str = LEGACY_OWNER_ID) -> ChatSession:
        try:
            with self.session_factory.begin() as db_session:
                paper = db_session.scalar(
                    select(PaperRecord).where(PaperRecord.id == session.paper_id, PaperRecord.owner_id == owner_id)
                )
                if paper is None:
                    raise PaperPersistenceError("The paper was not found.")
                if db_session.scalar(
                    select(DocumentRecord.id).where(
                        DocumentRecord.id == session.document_id,
                        DocumentRecord.paper_id == session.paper_id,
                    )
                ) is None:
                    raise PaperPersistenceError("The structured document was not found.")
                db_session.add(
                    ChatSessionRecord(
                        id=session.id,
                        owner_id=owner_id,
                        paper_id=session.paper_id,
                        document_id=session.document_id,
                        document_hash=session.document_hash,
                        created_at=session.created_at,
                        updated_at=session.updated_at,
                    )
                )
            return session
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The chat session could not be saved.") from exc

    def get_chat_session(self, session_id: str, owner_id: str = LEGACY_OWNER_ID) -> ChatSession | None:
        with self.session_factory() as db_session:
            record = db_session.scalar(
                select(ChatSessionRecord)
                .join(PaperRecord, PaperRecord.id == ChatSessionRecord.paper_id)
                .where(ChatSessionRecord.id == session_id, ChatSessionRecord.owner_id == owner_id, PaperRecord.owner_id == owner_id)
            )
            return _to_chat_session(record) if record else None

    def save_chat_message(self, message: ChatMessage, owner_id: str = LEGACY_OWNER_ID) -> None:
        try:
            with self.session_factory.begin() as db_session:
                session_record = db_session.scalar(
                    select(ChatSessionRecord).where(
                        ChatSessionRecord.id == message.session_id,
                        ChatSessionRecord.owner_id == owner_id,
                    )
                )
                if session_record is None:
                    raise PaperPersistenceError("The chat session was not found.")
                db_session.add(
                    ChatMessageRecord(
                        id=message.id,
                        session_id=message.session_id,
                        role=message.role.value,
                        content=message.content,
                        status=message.status.value if message.status else None,
                        citation_ids=[citation.model_dump(mode="json") for citation in message.citations],
                        sufficient_evidence=message.sufficient_evidence,
                        document_id=message.document_id,
                        retrieval_query=message.retrieval_query,
                        retrieved_evidence_ids=message.retrieved_evidence_ids,
                        retrieval_scores=message.retrieval_scores,
                        retriever_version=message.retriever_version,
                        provider=message.provider,
                        model=message.model,
                        created_at=message.created_at,
                    )
                )
                session_record.updated_at = message.created_at
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The chat message could not be saved.") from exc

    def get_chat_messages(self, session_id: str, owner_id: str = LEGACY_OWNER_ID) -> list[ChatMessage]:
        with self.session_factory() as db_session:
            allowed = db_session.scalar(
                select(ChatSessionRecord.id).where(ChatSessionRecord.id == session_id, ChatSessionRecord.owner_id == owner_id)
            )
            if allowed is None:
                return []
            records = db_session.scalars(
                select(ChatMessageRecord)
                .join(ChatSessionRecord, ChatSessionRecord.id == ChatMessageRecord.session_id)
                .where(ChatMessageRecord.session_id == session_id, ChatSessionRecord.owner_id == owner_id)
                .order_by(ChatMessageRecord.created_at, ChatMessageRecord.id)
            ).all()
            return [_to_chat_message(record) for record in records]

    def get_idempotent_response(self, scope: str, key: str) -> dict[str, object] | None:
        scope_key = f"{scope}:{key}"
        with self.session_factory() as session:
            record = session.get(IdempotencyRecord, scope_key)
            return dict(record.response_payload) if record else None

    def save_idempotent_response(self, scope: str, key: str, payload: dict[str, object]) -> None:
        scope_key = f"{scope}:{key}"
        try:
            with self.session_factory.begin() as session:
                record = session.get(IdempotencyRecord, scope_key)
                if record is None:
                    session.add(IdempotencyRecord(scope_key=scope_key, idempotency_key=key, response_payload=payload))
                else:
                    record.response_payload = payload
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The idempotency record could not be saved.") from exc

    def create_workspace(self, name: str, owner_id: str = LEGACY_OWNER_ID, claim: ExecutionClaim | None = None) -> Workspace:
        now = datetime.now(timezone.utc)
        workspace = Workspace(id=f"workspace_{uuid4().hex}", name=name.strip(), owner_id=owner_id, created_at=now, updated_at=now)
        try:
            with self.session_factory.begin() as session:
                if claim is not None and self._claim_record(session, claim) is None:
                    raise PaperPersistenceError("The research execution claim was lost.")
                session.add(WorkspaceRecord(**workspace.model_dump()))
            return workspace
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The workspace could not be saved.") from exc

    def get_workspace(self, workspace_id: str, owner_id: str = LEGACY_OWNER_ID) -> Workspace | None:
        with self.session_factory() as session:
            record = session.scalar(select(WorkspaceRecord).where(WorkspaceRecord.id == workspace_id, WorkspaceRecord.owner_id == owner_id))
            return _to_workspace(record) if record else None

    def list_workspaces(self, owner_id: str = LEGACY_OWNER_ID) -> list[Workspace]:
        with self.session_factory() as session:
            return [
                _to_workspace(record)
                for record in session.scalars(
                    select(WorkspaceRecord).where(WorkspaceRecord.owner_id == owner_id).order_by(WorkspaceRecord.created_at)
                ).all()
            ]

    def update_workspace(self, workspace_id: str, name: str, owner_id: str = LEGACY_OWNER_ID) -> Workspace | None:
        try:
            with self.session_factory.begin() as session:
                record = session.scalar(
                    select(WorkspaceRecord).where(WorkspaceRecord.id == workspace_id, WorkspaceRecord.owner_id == owner_id)
                )
                if record is None:
                    return None
                record.name = name.strip()
                record.updated_at = datetime.now(timezone.utc)
                return _to_workspace(record)
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The workspace could not be updated.") from exc

    def delete_workspace(self, workspace_id: str, owner_id: str = LEGACY_OWNER_ID) -> bool:
        try:
            with self.session_factory.begin() as session:
                record = session.scalar(
                    select(WorkspaceRecord).where(WorkspaceRecord.id == workspace_id, WorkspaceRecord.owner_id == owner_id)
                )
                if record is None:
                    return False
                session.delete(record)
                return True
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The workspace could not be deleted.") from exc

    def get_workspace_papers(self, workspace_id: str, owner_id: str = LEGACY_OWNER_ID) -> list[WorkspacePaperView]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(WorkspacePaperRecord)
                .join(WorkspaceRecord, WorkspaceRecord.id == WorkspacePaperRecord.workspace_id)
                .where(WorkspacePaperRecord.workspace_id == workspace_id, WorkspaceRecord.owner_id == owner_id)
                .order_by(WorkspacePaperRecord.added_at)
            ).all()
            result: list[WorkspacePaperView] = []
            for row in rows:
                paper = session.scalar(
                    select(PaperRecord).where(PaperRecord.id == row.paper_id, PaperRecord.owner_id == owner_id)
                )
                if paper is None or paper.title is None:
                    continue
                analysis = session.scalar(
                    select(AnalysisRecord)
                    .join(PaperRecord, PaperRecord.id == AnalysisRecord.paper_id)
                    .where(AnalysisRecord.paper_id == row.paper_id, PaperRecord.owner_id == owner_id)
                )
                result.append(WorkspacePaperView(paper_id=row.paper_id, title=paper.title, arxiv_id=paper.arxiv_id, analyzed=analysis is not None, added_at=row.added_at))
            return result

    def add_workspace_paper(self, workspace_id: str, paper_id: str, owner_id: str = LEGACY_OWNER_ID, claim: ExecutionClaim | None = None) -> WorkspacePaper:
        if self.get_workspace(workspace_id, owner_id) is None or self.get_by_id(paper_id, owner_id) is None:
            raise PaperPersistenceError("The workspace or paper was not found.")
        now = datetime.now(timezone.utc)
        item = WorkspacePaper(workspace_id=workspace_id, paper_id=paper_id, added_at=now)
        try:
            with self.session_factory.begin() as session:
                if claim is not None and self._claim_record(session, claim) is None:
                    raise PaperPersistenceError("The research execution claim was lost.")
                existing = session.scalar(select(WorkspacePaperRecord).where(WorkspacePaperRecord.workspace_id == workspace_id, WorkspacePaperRecord.paper_id == paper_id))
                if existing is None:
                    session.add(WorkspacePaperRecord(workspace_id=workspace_id, paper_id=paper_id, added_at=now))
                workspace = session.scalar(
                    select(WorkspaceRecord).where(WorkspaceRecord.id == workspace_id, WorkspaceRecord.owner_id == owner_id)
                )
                if workspace is not None:
                    workspace.updated_at = now
            return item
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The paper could not be added to the workspace.") from exc

    def remove_workspace_paper(self, workspace_id: str, paper_id: str, owner_id: str = LEGACY_OWNER_ID) -> bool:
        try:
            with self.session_factory.begin() as session:
                row = session.scalar(
                    select(WorkspacePaperRecord)
                    .join(WorkspaceRecord, WorkspaceRecord.id == WorkspacePaperRecord.workspace_id)
                    .where(
                        WorkspacePaperRecord.workspace_id == workspace_id,
                        WorkspacePaperRecord.paper_id == paper_id,
                        WorkspaceRecord.owner_id == owner_id,
                    )
                )
                if row is None:
                    return False
                session.delete(row)
                workspace = session.scalar(select(WorkspaceRecord).where(WorkspaceRecord.id == workspace_id, WorkspaceRecord.owner_id == owner_id))
                if workspace is not None:
                    workspace.updated_at = datetime.now(timezone.utc)
            return True
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The paper could not be removed from the workspace.") from exc

    def create_research_run(self, run: ResearchRun, owner_id: str = LEGACY_OWNER_ID) -> ResearchRun:
        try:
            with self.session_factory.begin() as session:
                if run.workspace_id is not None and session.scalar(
                    select(WorkspaceRecord.id).where(
                        WorkspaceRecord.id == run.workspace_id,
                        WorkspaceRecord.owner_id == owner_id,
                    )
                ) is None:
                    raise PaperPersistenceError("The workspace was not found.")
                values = run.model_dump()
                values["status"] = run.status.value
                values["execution_state"] = run.execution_state.value
                values["owner_id"] = owner_id
                session.add(ResearchRunRecord(**values))
            return run
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The research run could not be saved.") from exc

    def get_research_run(self, run_id: str, owner_id: str = LEGACY_OWNER_ID) -> ResearchRun | None:
        with self.session_factory() as session:
            record = session.scalar(select(ResearchRunRecord).where(ResearchRunRecord.id == run_id, ResearchRunRecord.owner_id == owner_id))
            return _to_research_run(record) if record else None

    def get_research_run_owner(self, run_id: str) -> str | None:
        """Return the durable owner for trusted worker execution (never client input)."""

        with self.session_factory() as session:
            return session.scalar(select(ResearchRunRecord.owner_id).where(ResearchRunRecord.id == run_id))

    def is_owner_enabled(self, owner_id: str) -> bool:
        with self.session_factory() as session:
            record = session.get(UserRecord, owner_id)
            return record is not None and record.disabled_at is None

    def update_research_run(self, run: ResearchRun, owner_id: str = LEGACY_OWNER_ID, claim: ExecutionClaim | None = None) -> ResearchRun:
        try:
            with self.session_factory.begin() as session:
                record = session.scalar(select(ResearchRunRecord).where(ResearchRunRecord.id == run.id, ResearchRunRecord.owner_id == owner_id))
                if record is None:
                    raise PaperPersistenceError("The research run was not found.")
                if claim is not None and self._claim_record(session, claim) is None:
                    raise PaperPersistenceError("The research execution claim was lost.")
                if claim is not None and record.cancel_requested_at is not None and run.status != ResearchRunStatus.CANCELLED:
                    raise PaperPersistenceError("The research run cancellation request won the race.")
                values = run.model_dump()
                values["status"] = run.status.value
                values["execution_state"] = run.execution_state.value
                if claim is not None:
                    # Durable control fields are owned by the execution state
                    # machine, never by a stale stage snapshot.
                    for key in ("execution_state", "active_attempt_id", "attempt_count", "cancel_requested_at", "next_attempt_at"):
                        values[key] = getattr(record, key)
                for key, value in values.items():
                    setattr(record, key, value)
            return run
        except PaperPersistenceError:
            raise
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The research run could not be updated.") from exc

    def save_research_plan(self, run_id: str, plan: ResearchPlan, owner_id: str = LEGACY_OWNER_ID, claim: ExecutionClaim | None = None) -> None:
        try:
            with self.session_factory.begin() as session:
                if session.scalar(select(ResearchRunRecord.id).where(ResearchRunRecord.id == run_id, ResearchRunRecord.owner_id == owner_id)) is None:
                    raise PaperPersistenceError("The research run was not found.")
                if claim is not None and self._claim_record(session, claim) is None:
                    raise PaperPersistenceError("The research execution claim was lost.")
                record = session.get(ResearchRunPlanRecord, run_id)
                values = {"payload": plan.model_dump(mode="json"), "updated_at": datetime.now(timezone.utc)}
                if record is None:
                    session.add(ResearchRunPlanRecord(run_id=run_id, **values))
                else:
                    record.payload = values["payload"]
                    record.updated_at = values["updated_at"]
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The research plan could not be saved.") from exc

    def get_research_plan(self, run_id: str, owner_id: str = LEGACY_OWNER_ID) -> ResearchPlan | None:
        with self.session_factory() as session:
            if session.scalar(select(ResearchRunRecord.id).where(ResearchRunRecord.id == run_id, ResearchRunRecord.owner_id == owner_id)) is None:
                return None
            record = session.scalar(
                select(ResearchRunPlanRecord)
                .join(ResearchRunRecord, ResearchRunRecord.id == ResearchRunPlanRecord.run_id)
                .where(ResearchRunPlanRecord.run_id == run_id, ResearchRunRecord.owner_id == owner_id)
            )
            if record is None:
                return None
            try:
                return ResearchPlan.model_validate(record.payload)
            except ValueError as exc:
                raise PaperPersistenceError("The stored research plan is invalid.") from exc

    def add_research_query(self, run_id: str, query: str, iteration: int, owner_id: str = LEGACY_OWNER_ID, claim: ExecutionClaim | None = None) -> None:
        try:
            with self.session_factory.begin() as session:
                if session.scalar(select(ResearchRunRecord.id).where(ResearchRunRecord.id == run_id, ResearchRunRecord.owner_id == owner_id)) is None:
                    raise PaperPersistenceError("The research run was not found.")
                if claim is not None and self._claim_record(session, claim) is None:
                    raise PaperPersistenceError("The research execution claim was lost.")
                session.add(ResearchRunQueryRecord(id=f"query_{uuid4().hex}", run_id=run_id, query=query, iteration=iteration, created_at=datetime.now(timezone.utc)))
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The research query could not be saved.") from exc

    def get_research_queries(self, run_id: str, owner_id: str = LEGACY_OWNER_ID) -> list[str]:
        with self.session_factory() as session:
            if session.scalar(select(ResearchRunRecord.id).where(ResearchRunRecord.id == run_id, ResearchRunRecord.owner_id == owner_id)) is None:
                return []
            records = session.scalars(
                select(ResearchRunQueryRecord)
                .join(ResearchRunRecord, ResearchRunRecord.id == ResearchRunQueryRecord.run_id)
                .where(ResearchRunQueryRecord.run_id == run_id, ResearchRunRecord.owner_id == owner_id)
                .order_by(ResearchRunQueryRecord.created_at, ResearchRunQueryRecord.id)
            ).all()
            return [record.query for record in records]

    def save_research_candidates(self, run_id: str, candidates: list[PaperCandidate], owner_id: str = LEGACY_OWNER_ID, claim: ExecutionClaim | None = None) -> None:
        try:
            with self.session_factory.begin() as session:
                if session.scalar(select(ResearchRunRecord.id).where(ResearchRunRecord.id == run_id, ResearchRunRecord.owner_id == owner_id)) is None:
                    raise PaperPersistenceError("The research run was not found.")
                if claim is not None and self._claim_record(session, claim) is None:
                    raise PaperPersistenceError("The research execution claim was lost.")
                for candidate in candidates:
                    record_id = f"{run_id}:{candidate.candidate_id}"
                    record = session.get(ResearchRunCandidateRecord, record_id)
                    values = {
                        "run_id": run_id,
                        "candidate_id": candidate.candidate_id,
                        "payload": candidate.model_dump(mode="json"),
                        "ranking_score": candidate.ranking_score,
                        "selected": candidate.selected,
                        "ingestion_status": candidate.ingestion_status,
                        "paper_id": candidate.paper_id,
                        "error": candidate.error,
                    }
                    if record is None:
                        session.add(ResearchRunCandidateRecord(id=record_id, **values))
                    else:
                        for key, value in values.items():
                            setattr(record, key, value)
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The research candidates could not be saved.") from exc

    def get_research_candidates(self, run_id: str, owner_id: str = LEGACY_OWNER_ID) -> list[PaperCandidate]:
        with self.session_factory() as session:
            if session.scalar(select(ResearchRunRecord.id).where(ResearchRunRecord.id == run_id, ResearchRunRecord.owner_id == owner_id)) is None:
                return []
            records = session.scalars(
                select(ResearchRunCandidateRecord)
                .join(ResearchRunRecord, ResearchRunRecord.id == ResearchRunCandidateRecord.run_id)
                .where(ResearchRunCandidateRecord.run_id == run_id, ResearchRunRecord.owner_id == owner_id)
                .order_by(ResearchRunCandidateRecord.ranking_score.desc(), ResearchRunCandidateRecord.candidate_id)
            ).all()
            try:
                return [PaperCandidate.model_validate(record.payload) for record in records]
            except ValueError as exc:
                raise PaperPersistenceError("The stored research candidates are invalid.") from exc

    def add_research_event(self, event: ResearchRunEvent, owner_id: str = LEGACY_OWNER_ID, claim: ExecutionClaim | None = None) -> None:
        try:
            with self.session_factory.begin() as session:
                if self.engine.dialect.name == "sqlite":
                    self._begin_claim_transaction(session)
                if session.scalar(select(ResearchRunRecord.id).where(ResearchRunRecord.id == event.research_run_id, ResearchRunRecord.owner_id == owner_id)) is None:
                    raise PaperPersistenceError("The research run was not found.")
                if claim is not None and self._claim_record(session, claim) is None:
                    raise PaperPersistenceError("The research execution claim was lost.")
                self._add_event_session(session, event.research_run_id, event.event_type, event.message, event.metadata, attempt_id=claim.attempt_id if claim else event.attempt_id, created_at=event.created_at, event_id=event.id)
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The research event could not be saved.") from exc

    def get_research_events(self, run_id: str, owner_id: str = LEGACY_OWNER_ID) -> list[ResearchRunEvent]:
        with self.session_factory() as session:
            if session.scalar(select(ResearchRunRecord.id).where(ResearchRunRecord.id == run_id, ResearchRunRecord.owner_id == owner_id)) is None:
                return []
            records = session.scalars(
                select(ResearchRunEventRecord)
                .join(ResearchRunRecord, ResearchRunRecord.id == ResearchRunEventRecord.run_id)
                .where(ResearchRunEventRecord.run_id == run_id, ResearchRunRecord.owner_id == owner_id)
                .order_by(ResearchRunEventRecord.created_at, ResearchRunEventRecord.id)
            ).all()
            return [ResearchRunEvent(id=record.id, research_run_id=record.run_id, event_type=record.event_type, message=record.message, metadata=dict(record.event_metadata or {}), created_at=record.created_at, attempt_id=record.attempt_id, sequence=record.sequence) for record in records]

    def save_research_report(self, run_id: str, report: ResearchReportIR, owner_id: str = LEGACY_OWNER_ID, claim: ExecutionClaim | None = None) -> None:
        try:
            with self.session_factory.begin() as session:
                if session.scalar(select(ResearchRunRecord.id).where(ResearchRunRecord.id == run_id, ResearchRunRecord.owner_id == owner_id)) is None:
                    raise PaperPersistenceError("The research run was not found.")
                if claim is not None and self._claim_record(session, claim) is None:
                    raise PaperPersistenceError("The research execution claim was lost.")
                record = session.get(ResearchRunReportRecord, run_id)
                values = {"coverage": report.coverage.model_dump(mode="json"), "payload": report.model_dump(mode="json"), "updated_at": datetime.now(timezone.utc)}
                if record is None:
                    session.add(ResearchRunReportRecord(run_id=run_id, **values))
                else:
                    record.coverage = values["coverage"]
                    record.payload = values["payload"]
                    record.updated_at = values["updated_at"]
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The research report could not be saved.") from exc

    def get_research_report(self, run_id: str, owner_id: str = LEGACY_OWNER_ID) -> ResearchReportIR | None:
        with self.session_factory() as session:
            if session.scalar(select(ResearchRunRecord.id).where(ResearchRunRecord.id == run_id, ResearchRunRecord.owner_id == owner_id)) is None:
                return None
            record = session.scalar(
                select(ResearchRunReportRecord)
                .join(ResearchRunRecord, ResearchRunRecord.id == ResearchRunReportRecord.run_id)
                .where(ResearchRunReportRecord.run_id == run_id, ResearchRunRecord.owner_id == owner_id)
            )
            if record is None:
                return None
            try:
                return ResearchReportIR.model_validate(record.payload)
            except ValueError as exc:
                raise PaperPersistenceError("The stored research report is invalid.") from exc

    def get_source_pdf_path(self, paper_id: str, owner_id: str = LEGACY_OWNER_ID) -> Path | None:
        """Return a persisted PDF path only for a completed paper."""

        with self.session_factory() as session:
            record = session.scalar(select(PaperRecord).where(PaperRecord.id == paper_id, PaperRecord.owner_id == owner_id))
            if record is None or record.status != "COMPLETED" or not record.local_pdf_path:
                return None
            return Path(record.local_pdf_path)

    def get_analysis_record(self, paper_id: str, owner_id: str = LEGACY_OWNER_ID) -> tuple[PaperIR, str] | None:
        with self.session_factory() as session:
            record = session.scalar(
                select(AnalysisRecord)
                .join(PaperRecord, PaperRecord.id == AnalysisRecord.paper_id)
                .where(AnalysisRecord.paper_id == paper_id, PaperRecord.owner_id == owner_id)
            )
            if record is None:
                return None
            try:
                return PaperIR.model_validate(record.payload), record.cache_key
            except ValueError as exc:
                raise PaperPersistenceError("The stored paper analysis is invalid.") from exc

    def get_verification_by_cache_keys(
        self, paper_id: str, cache_keys: list[str], owner_id: str = LEGACY_OWNER_ID
    ) -> dict[str, VerificationResult]:
        if not cache_keys:
            return {}
        with self.session_factory() as session:
            records = session.scalars(
                select(VerificationRecord)
                .join(PaperRecord, PaperRecord.id == VerificationRecord.paper_id)
                .where(VerificationRecord.paper_id == paper_id, VerificationRecord.cache_key.in_(cache_keys), PaperRecord.owner_id == owner_id)
            ).all()
            try:
                return {
                    record.cache_key: VerificationResult.model_validate(record.payload)
                    for record in records
                }
            except ValueError as exc:
                raise PaperPersistenceError("The stored verification result is invalid.") from exc

    def save_verification_results(
        self, paper_id: str, document_id: str, results: list[VerificationResult], owner_id: str = LEGACY_OWNER_ID
    ) -> None:
        try:
            with self.session_factory.begin() as session:
                if session.scalar(select(PaperRecord.id).where(PaperRecord.id == paper_id, PaperRecord.owner_id == owner_id)) is None:
                    raise PaperPersistenceError("The paper was not found.")
                for result in results:
                    payload = result.model_dump(mode="json")
                    record = session.scalar(
                        select(VerificationRecord)
                        .join(PaperRecord, PaperRecord.id == VerificationRecord.paper_id)
                        .where(
                            VerificationRecord.cache_key == result.cache_key,
                            VerificationRecord.paper_id == paper_id,
                            PaperRecord.owner_id == owner_id,
                        )
                    )
                    values = {
                        "paper_id": paper_id,
                        "claim_id": result.claim_id,
                        "document_id": document_id,
                        "document_hash": result.document_hash,
                        "claim_hash": result.claim_hash,
                        "evidence_hash": result.evidence_hash,
                        "provider": result.verifier_provider,
                        "model": result.verifier_model,
                        "prompt_version": result.prompt_version,
                        "schema_version": result.schema_version,
                        "cache_key": result.cache_key,
                        "payload": payload,
                        "verified_at": result.verified_at,
                    }
                    if record is None:
                        session.add(VerificationRecord(**values))
                    else:
                        for key, value in values.items():
                            setattr(record, key, value)
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The paper verification could not be saved.") from exc

    def save_analysis(
        self,
        paper_ir: PaperIR,
        *,
        cache_key: str,
        provider: str,
        model: str,
        prompt_version: str,
        schema_version: str,
        owner_id: str = LEGACY_OWNER_ID,
    ) -> None:
        try:
            with self.session_factory.begin() as session:
                if session.scalar(select(PaperRecord.id).where(PaperRecord.id == paper_ir.paper_id, PaperRecord.owner_id == owner_id)) is None:
                    raise PaperPersistenceError("The paper was not found.")
                record = session.scalar(
                    select(AnalysisRecord)
                    .join(PaperRecord, PaperRecord.id == AnalysisRecord.paper_id)
                    .where(AnalysisRecord.paper_id == paper_ir.paper_id, PaperRecord.owner_id == owner_id)
                )
                values = {
                    "document_id": paper_ir.document_id,
                    "document_hash": paper_ir.document_hash,
                    "provider": provider,
                    "model": model,
                    "prompt_version": prompt_version,
                    "schema_version": schema_version,
                    "cache_key": cache_key,
                    "payload": paper_ir.model_dump(mode="json"),
                }
                if record is None:
                    session.add(AnalysisRecord(paper_id=paper_ir.paper_id, **values))
                else:
                    for key, value in values.items():
                        setattr(record, key, value)
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The paper analysis could not be saved.") from exc

    def update_status(
        self, paper_id: str, status: str, *, error_message: str | None = None, owner_id: str = LEGACY_OWNER_ID
    ) -> None:
        try:
            with self.session_factory.begin() as session:
                record = session.scalar(select(PaperRecord).where(PaperRecord.id == paper_id, PaperRecord.owner_id == owner_id))
                if record:
                    record.status = status
                    record.error_message = error_message
                    if status == "FAILED":
                        # A parse can fail after the paper row was staged as
                        # PARSED but before its normalized document/evidence
                        # transaction commits. Keep failed work diagnosable
                        # without exposing half-populated sections or a source
                        # pointer that is no longer considered valid.
                        record.sections.clear()
                        record.local_pdf_path = None
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The paper status could not be saved.") from exc


class SQLiteDatabase(SQLDatabase):
    """Backward-compatible name for Phase 1 callers and tests."""

    def __init__(self, database_url: str = "sqlite:///./paperlens.db") -> None:
        if not database_url.startswith("sqlite:"):
            raise ValueError("SQLiteDatabase requires a sqlite database URL")
        super().__init__(database_url)


def _configure_sqlite_connection(dbapi_connection: object, connection_record: object) -> None:
    """Enable constraints and bounded lock waits for SQLite development databases."""

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA journal_mode=WAL")
    finally:
        cursor.close()


def _scoped_source_identity(source_identity: str, owner_id: str) -> str:
    """Keep source idempotency tenant-local while accepting legacy raw keys."""

    if owner_id == LEGACY_OWNER_ID:
        return source_identity
    return f"{owner_id}:{source_identity}"


def _as_utc(value: datetime) -> datetime:
    """Normalize SQLite's naive datetime round-trips for lease comparisons."""

    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _namespace_colliding_ids(session: object, document: StructuredDocument, evidence: list[Evidence]) -> None:
    """Keep legacy per-document IDs readable while making the global SQL keys safe."""

    prefix = f"{document.id}__"
    section_ids = [section.id for section in document.sections]
    if section_ids and session.scalar(
        select(DocumentSectionRecord.id).where(
            DocumentSectionRecord.id.in_(section_ids),
            DocumentSectionRecord.document_id != document.id,
        )
    ) is not None:
        section_map = {section.id: f"{prefix}{section.id}" for section in document.sections}
        paragraph_map = {
            paragraph.id: f"{prefix}{paragraph.id}"
            for section in document.sections
            for paragraph in section.paragraphs
        }
        for section in document.sections:
            old_id = section.id
            section.id = section_map[old_id]
            section.parent_id = section_map.get(section.parent_id, section.parent_id)
            for paragraph in section.paragraphs:
                paragraph.id = paragraph_map[paragraph.id]
                paragraph.section_id = section.id
        for item in evidence:
            item.section_id = section_map.get(item.section_id, item.section_id)
            item.paragraph_id = paragraph_map.get(item.paragraph_id, item.paragraph_id)

    evidence_ids = [item.id for item in evidence]
    if evidence_ids and session.scalar(
        select(EvidenceRecord.id).where(
            EvidenceRecord.id.in_(evidence_ids),
            EvidenceRecord.document_id != document.id,
        )
    ) is not None:
        evidence_map = {item.id: f"{prefix}{item.id}" for item in evidence}
        for item in evidence:
            item.id = evidence_map[item.id]
        for section in document.sections:
            for paragraph in section.paragraphs:
                paragraph.evidence_id = evidence_map.get(paragraph.evidence_id, paragraph.evidence_id)
        for artifact in (*document.figures, *document.tables, *document.equations, *document.references):
            artifact.evidence_ids = [evidence_map.get(item, item) for item in artifact.evidence_ids]


def _to_model(record: PaperRecord) -> IngestedPaper:
    if record.title is None or record.source_url is None or record.pdf_url is None:
        raise PaperPersistenceError("The paper is not complete.")
    return IngestedPaper(
        id=record.id,
        status=record.status,
        metadata=PaperMetadata(
            arxiv_id=record.arxiv_id,
            title=record.title,
            authors=list(record.authors or []),
            abstract=record.abstract,
            published_at=record.published_at,
            updated_at=record.arxiv_updated_at,
            categories=list(record.categories or []),
            source_url=record.source_url,
            pdf_url=record.pdf_url,
        ),
        sections=[
            ParsedSection(title=section.title, order=section.order, text=section.text)
            for section in record.sections
        ],
    )


def _region_columns(region: SourceRegion | None) -> dict[str, object]:
    return {
        "region_page": region.page if region else None,
        "x0": region.x0 if region else None,
        "y0": region.y0 if region else None,
        "x1": region.x1 if region else None,
        "y1": region.y1 if region else None,
    }


def _source_region(record: object) -> SourceRegion | None:
    page = getattr(record, "region_page", None)
    coordinates = [getattr(record, name, None) for name in ("x0", "y0", "x1", "y1")]
    if page is None:
        return None
    return SourceRegion(page=page, x0=coordinates[0], y0=coordinates[1], x1=coordinates[2], y1=coordinates[3])


def _to_document(record: DocumentRecord, paper: PaperRecord) -> StructuredDocument:
    if paper.title is None or paper.source_url is None or paper.pdf_url is None:
        raise PaperPersistenceError("The paper is not complete.")
    metadata = PaperMetadata(
        arxiv_id=paper.arxiv_id,
        title=paper.title,
        authors=list(paper.authors or []),
        abstract=paper.abstract,
        published_at=paper.published_at,
        updated_at=paper.arxiv_updated_at,
        categories=list(paper.categories or []),
        source_url=paper.source_url,
        pdf_url=paper.pdf_url,
    )
    sections = [
        PaperSection(
            id=section.id,
            title=section.title,
            level=section.level,
            order=section.order,
            parent_id=section.parent_id,
            page_start=section.page_start,
            page_end=section.page_end,
            paragraphs=[
                PaperParagraph(
                    id=paragraph.id,
                    section_id=section.id,
                    order=paragraph.order,
                    text=paragraph.text,
                    page=paragraph.page,
                    source_region=_source_region(paragraph),
                    content_hash=paragraph.content_hash,
                    evidence_id=paragraph.evidence_id,
                )
                for paragraph in section.paragraphs
            ],
        )
        for section in record.sections
    ]
    artifacts = {item.kind: [] for item in record.artifacts}
    for item in record.artifacts:
        artifacts.setdefault(item.kind, []).append(item.payload)
    return StructuredDocument(
        id=record.id,
        paper_id=record.paper_id,
        metadata=metadata,
        sections=sections,
        page_count=record.page_count,
        parser_name=record.parser_name,
        parser_version=record.parser_version,
        source_hash=record.source_hash,
        document_hash=record.document_hash,
        created_at=record.created_at,
        figures=[PaperFigure.model_validate(item) for item in artifacts.get("figure", [])],
        tables=[PaperTable.model_validate(item) for item in artifacts.get("table", [])],
        equations=[PaperEquation.model_validate(item) for item in artifacts.get("equation", [])],
        references=[PaperReference.model_validate(item) for item in artifacts.get("reference", [])],
    )


def _to_evidence(record: EvidenceRecord) -> Evidence:
    return Evidence(
        id=record.id,
        paper_id=record.paper_id,
        document_id=record.document_id,
        evidence_type=EvidenceType(record.evidence_type),
        source_text=record.source_text,
        page=record.page,
        section_id=record.section_id,
        paragraph_id=record.paragraph_id,
        figure_id=record.figure_id,
        table_id=record.table_id,
        equation_id=record.equation_id,
        source_region=_source_region(record),
        created_at=record.created_at,
    )


def _to_chat_session(record: ChatSessionRecord) -> ChatSession:
    return ChatSession(
        id=record.id,
        paper_id=record.paper_id,
        document_id=record.document_id,
        document_hash=record.document_hash,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _to_chat_message(record: ChatMessageRecord) -> ChatMessage:
    from ..models.chat import ChatCitation

    citations = []
    for item in list(record.citation_ids or []):
        if isinstance(item, dict):
            citations.append(ChatCitation.model_validate(item))
        else:
            citations.append(ChatCitation(evidence_id=str(item)))
    return ChatMessage(
        id=record.id,
        session_id=record.session_id,
        role=ChatRole(record.role),
        content=record.content,
        status=ChatMessageStatus(record.status) if record.status else None,
        citations=citations,
        sufficient_evidence=record.sufficient_evidence,
        document_id=record.document_id,
        retrieval_query=record.retrieval_query,
        retrieved_evidence_ids=list(record.retrieved_evidence_ids or []),
        retrieval_scores={str(key): float(value) for key, value in dict(record.retrieval_scores or {}).items()},
        retriever_version=record.retriever_version,
        provider=record.provider,
        model=record.model,
        created_at=record.created_at,
    )


def _to_user(record: UserRecord) -> User:
    return User(id=record.id, email=record.email, created_at=record.created_at)


def _to_workspace(record: WorkspaceRecord) -> Workspace:
    return Workspace(id=record.id, name=record.name, owner_id=record.owner_id, created_at=record.created_at, updated_at=record.updated_at)


def _to_research_run(record: ResearchRunRecord) -> ResearchRun:
    return ResearchRun(
        id=record.id,
        workspace_id=record.workspace_id,
        research_question=record.research_question,
        status=ResearchRunStatus(record.status),
        created_at=record.created_at,
        updated_at=record.updated_at,
        completed_at=record.completed_at,
        max_iterations=record.max_iterations,
        max_candidates=record.max_candidates,
        max_ingested_papers=record.max_ingested_papers,
        planner_provider=record.planner_provider,
        planner_model=record.planner_model,
        prompt_version=record.prompt_version,
        schema_version=record.schema_version,
        execution_state=ResearchExecutionState(getattr(record, "execution_state", ResearchExecutionState.IDLE.value)),
        active_attempt_id=getattr(record, "active_attempt_id", None),
        attempt_count=int(getattr(record, "attempt_count", 0) or 0),
        cancel_requested_at=getattr(record, "cancel_requested_at", None),
        next_attempt_at=getattr(record, "next_attempt_at", None),
    )


def _to_attempt_summary(record: ResearchExecutionAttemptRecord) -> ResearchAttemptSummary:
    return ResearchAttemptSummary(
        attempt_id=record.attempt_id,
        research_run_id=record.research_run_id,
        worker_id=record.worker_id,
        attempt_number=record.attempt_number,
        status=ResearchAttemptStatus(record.status),
        claimed_at=record.claimed_at,
        lease_expires_at=record.lease_expires_at,
        heartbeat_at=record.heartbeat_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        next_retry_at=record.next_retry_at,
        retryable=record.retryable,
        error_class=record.error_class,
        error_message=record.error_message,
    )
