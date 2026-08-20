"""SQLAlchemy persistence boundary for normalized papers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, UniqueConstraint, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
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
from ..models.research import Workspace, WorkspacePaper, WorkspacePaperView
from ..retrieval.embeddings import EmbeddingProvider


class Database(Protocol):
    def healthcheck(self) -> bool:
        """Return whether the backing store can execute a trivial query."""


class Base(DeclarativeBase):
    pass


class PaperRecord(Base):
    __tablename__ = "papers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(32), default="arxiv")
    source_identity: Mapped[str] = mapped_column(String(128), unique=True, index=True)
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


class SQLDatabase:
    """Synchronous SQLAlchemy adapter used by the async service boundary."""

    def __init__(self, database_url: str = "sqlite:///./paperlens.db", *, engine: Engine | None = None) -> None:
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        engine_kwargs: dict[str, object] = {"future": True, "connect_args": connect_args}
        if database_url in {"sqlite://", "sqlite:///:memory:"}:
            engine_kwargs["poolclass"] = StaticPool
        self.engine = engine or create_engine(database_url, **engine_kwargs)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)
        self.create_tables()

    def create_tables(self) -> None:
        Base.metadata.create_all(self.engine)

    def healthcheck(self) -> bool:
        try:
            with self.session_factory() as session:
                return session.execute(select(1)).scalar_one() == 1
        except SQLAlchemyError:
            return False

    def get_by_source_identity(self, source_identity: str) -> IngestedPaper | None:
        with self.session_factory() as session:
            record = session.scalar(select(PaperRecord).where(PaperRecord.source_identity == source_identity))
            return _to_model(record) if record and record.status == "COMPLETED" else None

    def get_by_id(self, paper_id: str) -> IngestedPaper | None:
        with self.session_factory() as session:
            record = session.get(PaperRecord, paper_id)
            return _to_model(record) if record and record.status == "COMPLETED" else None

    def list_papers(self) -> list[IngestedPaper]:
        with self.session_factory() as session:
            records = session.scalars(select(PaperRecord).where(PaperRecord.status == "COMPLETED").order_by(PaperRecord.created_at)).all()
            return [_to_model(record) for record in records]

    def create_placeholder(self, *, paper_id: str, source_identity: str, arxiv_id: str) -> None:
        try:
            with self.session_factory.begin() as session:
                record = session.get(PaperRecord, paper_id)
                if record is None:
                    session.add(
                        PaperRecord(
                            id=paper_id,
                            source_identity=source_identity,
                            arxiv_id=arxiv_id,
                            status="PENDING",
                        )
                    )
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The paper could not be saved.") from exc

    def save_metadata(self, paper_id: str, metadata: PaperMetadata, *, status: str) -> None:
        try:
            with self.session_factory.begin() as session:
                record = session.get(PaperRecord, paper_id)
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
    ) -> IngestedPaper:
        try:
            with self.session_factory.begin() as session:
                record = session.get(PaperRecord, paper_id)
                if record is None:
                    raise PaperPersistenceError("The paper could not be saved.")
                record.status = "COMPLETED"
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

    def replace_document(self, document: StructuredDocument, evidence: list[Evidence]) -> None:
        """Replace one paper's normalized document and evidence in one transaction."""

        try:
            with self.session_factory.begin() as session:
                paper = session.get(PaperRecord, document.paper_id)
                if paper is None:
                    raise PaperPersistenceError("The paper could not be saved.")
                existing = session.scalar(
                    select(DocumentRecord).where(DocumentRecord.paper_id == document.paper_id)
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

    def get_document(self, paper_id: str) -> StructuredDocument | None:
        with self.session_factory() as session:
            record = session.scalar(
                select(DocumentRecord)
                .options(
                    selectinload(DocumentRecord.sections).selectinload(DocumentSectionRecord.paragraphs),
                    selectinload(DocumentRecord.artifacts),
                )
                .where(DocumentRecord.paper_id == paper_id)
            )
            paper = session.get(PaperRecord, paper_id)
            if record is None or paper is None or paper.title is None or paper.source_url is None or paper.pdf_url is None:
                return None
            return _to_document(record, paper)

    def get_evidence(self, paper_id: str, evidence_id: str) -> Evidence | None:
        with self.session_factory() as session:
            record = session.scalar(
                select(EvidenceRecord).where(
                    EvidenceRecord.paper_id == paper_id,
                    EvidenceRecord.id == evidence_id,
                )
            )
            return _to_evidence(record) if record else None

    def get_evidence_many(self, paper_id: str, evidence_ids: list[str]) -> dict[str, Evidence]:
        if not evidence_ids:
            return {}
        with self.session_factory() as session:
            records = session.scalars(
                select(EvidenceRecord).where(
                    EvidenceRecord.paper_id == paper_id,
                    EvidenceRecord.id.in_(evidence_ids),
                )
            ).all()
            return {record.id: _to_evidence(record) for record in records}

    def get_evidence_for_document(self, paper_id: str, document_id: str) -> list[Evidence]:
        with self.session_factory() as session:
            records = session.scalars(
                select(EvidenceRecord)
                .where(EvidenceRecord.paper_id == paper_id, EvidenceRecord.document_id == document_id)
                .order_by(EvidenceRecord.id)
            ).all()
            return [_to_evidence(record) for record in records]

    def get_embeddings(
        self,
        paper_id: str,
        document_id: str,
        embedding_model: str,
        embedding_version: str,
    ) -> dict[str, tuple[list[float], str]]:
        with self.session_factory() as session:
            records = session.scalars(
                select(EvidenceEmbeddingRecord).where(
                    EvidenceEmbeddingRecord.paper_id == paper_id,
                    EvidenceEmbeddingRecord.document_id == document_id,
                    EvidenceEmbeddingRecord.embedding_model == embedding_model,
                    EvidenceEmbeddingRecord.embedding_version == embedding_version,
                )
            ).all()
            return {record.evidence_id: (list(record.vector or []), record.evidence_hash) for record in records}

    def save_embeddings(
        self,
        paper_id: str,
        document_id: str,
        provider: EmbeddingProvider,
        items: list[tuple[Evidence, list[float]]],
    ) -> None:
        import hashlib

        try:
            with self.session_factory.begin() as session:
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

    def create_chat_session(self, session: ChatSession) -> ChatSession:
        try:
            with self.session_factory.begin() as db_session:
                db_session.add(
                    ChatSessionRecord(
                        id=session.id,
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

    def get_chat_session(self, session_id: str) -> ChatSession | None:
        with self.session_factory() as db_session:
            record = db_session.get(ChatSessionRecord, session_id)
            return _to_chat_session(record) if record else None

    def save_chat_message(self, message: ChatMessage) -> None:
        try:
            with self.session_factory.begin() as db_session:
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
                session_record = db_session.get(ChatSessionRecord, message.session_id)
                if session_record is not None:
                    session_record.updated_at = message.created_at
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The chat message could not be saved.") from exc

    def get_chat_messages(self, session_id: str) -> list[ChatMessage]:
        with self.session_factory() as db_session:
            records = db_session.scalars(
                select(ChatMessageRecord)
                .where(ChatMessageRecord.session_id == session_id)
                .order_by(ChatMessageRecord.created_at, ChatMessageRecord.id)
            ).all()
            return [_to_chat_message(record) for record in records]

    def create_workspace(self, name: str) -> Workspace:
        now = datetime.now(timezone.utc)
        workspace = Workspace(id=f"workspace_{uuid4().hex}", name=name.strip(), created_at=now, updated_at=now)
        try:
            with self.session_factory.begin() as session:
                session.add(WorkspaceRecord(**workspace.model_dump()))
            return workspace
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The workspace could not be saved.") from exc

    def get_workspace(self, workspace_id: str) -> Workspace | None:
        with self.session_factory() as session:
            record = session.get(WorkspaceRecord, workspace_id)
            return _to_workspace(record) if record else None

    def list_workspaces(self) -> list[Workspace]:
        with self.session_factory() as session:
            return [_to_workspace(record) for record in session.scalars(select(WorkspaceRecord).order_by(WorkspaceRecord.created_at)).all()]

    def get_workspace_papers(self, workspace_id: str) -> list[WorkspacePaperView]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(WorkspacePaperRecord).where(WorkspacePaperRecord.workspace_id == workspace_id).order_by(WorkspacePaperRecord.added_at)
            ).all()
            result: list[WorkspacePaperView] = []
            for row in rows:
                paper = session.get(PaperRecord, row.paper_id)
                if paper is None or paper.title is None:
                    continue
                analysis = session.scalar(select(AnalysisRecord).where(AnalysisRecord.paper_id == row.paper_id))
                result.append(WorkspacePaperView(paper_id=row.paper_id, title=paper.title, arxiv_id=paper.arxiv_id, analyzed=analysis is not None, added_at=row.added_at))
            return result

    def add_workspace_paper(self, workspace_id: str, paper_id: str) -> WorkspacePaper:
        if self.get_workspace(workspace_id) is None or self.get_by_id(paper_id) is None:
            raise PaperPersistenceError("The workspace or paper was not found.")
        now = datetime.now(timezone.utc)
        item = WorkspacePaper(workspace_id=workspace_id, paper_id=paper_id, added_at=now)
        try:
            with self.session_factory.begin() as session:
                existing = session.scalar(select(WorkspacePaperRecord).where(WorkspacePaperRecord.workspace_id == workspace_id, WorkspacePaperRecord.paper_id == paper_id))
                if existing is None:
                    session.add(WorkspacePaperRecord(workspace_id=workspace_id, paper_id=paper_id, added_at=now))
                workspace = session.get(WorkspaceRecord, workspace_id)
                if workspace is not None:
                    workspace.updated_at = now
            return item
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The paper could not be added to the workspace.") from exc

    def remove_workspace_paper(self, workspace_id: str, paper_id: str) -> bool:
        try:
            with self.session_factory.begin() as session:
                row = session.scalar(select(WorkspacePaperRecord).where(WorkspacePaperRecord.workspace_id == workspace_id, WorkspacePaperRecord.paper_id == paper_id))
                if row is None:
                    return False
                session.delete(row)
                workspace = session.get(WorkspaceRecord, workspace_id)
                if workspace is not None:
                    workspace.updated_at = datetime.now(timezone.utc)
            return True
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The paper could not be removed from the workspace.") from exc

    def get_source_pdf_path(self, paper_id: str) -> Path | None:
        """Return a persisted PDF path only for a completed paper."""

        with self.session_factory() as session:
            record = session.get(PaperRecord, paper_id)
            if record is None or record.status != "COMPLETED" or not record.local_pdf_path:
                return None
            return Path(record.local_pdf_path)

    def get_analysis_record(self, paper_id: str) -> tuple[PaperIR, str] | None:
        with self.session_factory() as session:
            record = session.scalar(select(AnalysisRecord).where(AnalysisRecord.paper_id == paper_id))
            if record is None:
                return None
            try:
                return PaperIR.model_validate(record.payload), record.cache_key
            except ValueError as exc:
                raise PaperPersistenceError("The stored paper analysis is invalid.") from exc

    def get_verification_by_cache_keys(self, paper_id: str, cache_keys: list[str]) -> dict[str, VerificationResult]:
        if not cache_keys:
            return {}
        with self.session_factory() as session:
            records = session.scalars(
                select(VerificationRecord).where(
                    VerificationRecord.paper_id == paper_id,
                    VerificationRecord.cache_key.in_(cache_keys),
                )
            ).all()
            try:
                return {
                    record.cache_key: VerificationResult.model_validate(record.payload)
                    for record in records
                }
            except ValueError as exc:
                raise PaperPersistenceError("The stored verification result is invalid.") from exc

    def save_verification_results(self, paper_id: str, document_id: str, results: list[VerificationResult]) -> None:
        try:
            with self.session_factory.begin() as session:
                for result in results:
                    payload = result.model_dump(mode="json")
                    record = session.scalar(
                        select(VerificationRecord).where(VerificationRecord.cache_key == result.cache_key)
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
    ) -> None:
        try:
            with self.session_factory.begin() as session:
                record = session.scalar(select(AnalysisRecord).where(AnalysisRecord.paper_id == paper_ir.paper_id))
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

    def update_status(self, paper_id: str, status: str, *, error_message: str | None = None) -> None:
        try:
            with self.session_factory.begin() as session:
                record = session.get(PaperRecord, paper_id)
                if record:
                    record.status = status
                    record.error_message = error_message
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The paper status could not be saved.") from exc


class SQLiteDatabase(SQLDatabase):
    """Backward-compatible name for Phase 1 callers and tests."""

    def __init__(self, database_url: str = "sqlite:///./paperlens.db") -> None:
        if not database_url.startswith("sqlite:"):
            raise ValueError("SQLiteDatabase requires a sqlite database URL")
        super().__init__(database_url)


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


def _to_workspace(record: WorkspaceRecord) -> Workspace:
    return Workspace(id=record.id, name=record.name, created_at=record.created_at, updated_at=record.updated_at)
