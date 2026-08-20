"""SQLAlchemy persistence boundary for normalized papers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload, sessionmaker
from sqlalchemy.pool import StaticPool

from ..ingestion.errors import PaperPersistenceError
from ..models.document import (
    Evidence,
    EvidenceType,
    PaperParagraph,
    PaperSection,
    SourceRegion,
    StructuredDocument,
)
from ..models.document import PaperIR
from ..models.paper import IngestedPaper, PaperMetadata, ParsedSection


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
                session.add(record)
        except PaperPersistenceError:
            raise
        except SQLAlchemyError as exc:
            raise PaperPersistenceError("The structured document could not be saved.") from exc

    def get_document(self, paper_id: str) -> StructuredDocument | None:
        with self.session_factory() as session:
            record = session.scalar(
                select(DocumentRecord)
                .options(selectinload(DocumentRecord.sections).selectinload(DocumentSectionRecord.paragraphs))
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

    def get_analysis_record(self, paper_id: str) -> tuple[PaperIR, str] | None:
        with self.session_factory() as session:
            record = session.scalar(select(AnalysisRecord).where(AnalysisRecord.paper_id == paper_id))
            if record is None:
                return None
            try:
                return PaperIR.model_validate(record.payload), record.cache_key
            except ValueError as exc:
                raise PaperPersistenceError("The stored paper analysis is invalid.") from exc

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
