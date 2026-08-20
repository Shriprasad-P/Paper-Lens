"""SQLAlchemy persistence boundary for normalized papers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import StaticPool

from ..ingestion.errors import PaperPersistenceError
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
