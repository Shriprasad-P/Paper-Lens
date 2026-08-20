"""HTTP routes for the initial PaperLens foundation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse

from ..ingestion.errors import (
    ArxivMetadataError,
    ArxivNotFoundError,
    IngestionError,
    InvalidArxivIdentifierError,
    PaperParseError,
    PaperPersistenceError,
    PdfDownloadError,
)
from ..extraction.service import ResearchExtractionError
from ..models.document import Evidence, PaperIR, StructuredDocument
from ..models.paper import IngestRequest, IngestedPaper
from ..models.reader import (
    ReaderDocumentSummary,
    ReaderPaperView,
    ReaderReference,
    ReaderResponse,
    ReaderSectionSummary,
    ReaderSource,
)
from ..models.verification import PaperVerificationResponse
from ..verification.service import PaperVerificationError
from ..visualization.planner import plan_visualizations
from ..chat.service import ChatDocumentChanged, ChatGenerationUnavailable, ChatSessionNotFound, PaperChatError
from ..models.chat import ChatAnswerResponse, ChatQuestion, ChatSessionCreateResponse, ChatSessionResponse

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """Report service and persistence health without exposing implementation details."""

    database_ok = request.app.state.database.healthcheck()
    return {
        "status": "ok" if database_ok else "degraded",
        "service": "paperlens-api",
        "database": "ok" if database_ok else "unavailable",
    }


@router.post("/api/papers/ingest", response_model=IngestedPaper, status_code=status.HTTP_200_OK)
async def ingest_paper(payload: IngestRequest, request: Request) -> IngestedPaper:
    """Ingest an arXiv paper and return its normalized document structure."""

    try:
        return await request.app.state.ingestion_service.ingest(payload.source)
    except InvalidArxivIdentifierError as exc:
        raise HTTPException(status_code=422, detail="Invalid arXiv identifier.") from exc
    except ArxivNotFoundError as exc:
        raise HTTPException(status_code=404, detail="The arXiv paper was not found.") from exc
    except ArxivMetadataError as exc:
        raise HTTPException(status_code=502, detail="Unable to retrieve metadata from arXiv.") from exc
    except PdfDownloadError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except PaperParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PaperPersistenceError as exc:
        raise HTTPException(status_code=500, detail="The paper could not be saved.") from exc
    except IngestionError as exc:
        raise HTTPException(status_code=500, detail="The paper could not be ingested.") from exc


@router.get("/api/papers/{paper_id}", response_model=IngestedPaper)
async def get_paper(paper_id: str, request: Request) -> IngestedPaper:
    """Return a completed normalized paper by its stable internal ID."""

    paper = request.app.state.database.get_by_id(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found.")
    return paper


@router.get("/api/papers/{paper_id}/document", response_model=StructuredDocument)
async def get_document(paper_id: str, request: Request) -> StructuredDocument:
    """Return the source-preserving normalized document for a paper."""

    document = request.app.state.database.get_document(paper_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Structured document not found.")
    return document


@router.get("/api/papers/{paper_id}/evidence/{evidence_id}", response_model=Evidence)
async def get_evidence(paper_id: str, evidence_id: str, request: Request) -> Evidence:
    """Return one provenance record scoped to its paper."""

    evidence = request.app.state.database.get_evidence(paper_id, evidence_id)
    if evidence is None:
        raise HTTPException(status_code=404, detail="Evidence not found.")
    return evidence


@router.get("/api/papers/{paper_id}/reader", response_model=ReaderResponse)
async def get_reader(paper_id: str, request: Request) -> ReaderResponse:
    """Return the small reader payload; evidence bodies are loaded on demand."""

    paper = request.app.state.database.get_by_id(paper_id)
    document = request.app.state.database.get_document(paper_id)
    if paper is None or document is None:
        raise HTTPException(status_code=404, detail="Paper reader data not found.")
    analysis_record = request.app.state.database.get_analysis_record(paper_id)
    verification = request.app.state.verification_service.current(paper_id)
    source_path = request.app.state.database.get_source_pdf_path(paper_id)
    source_available = _safe_source_path(request, source_path) is not None
    return ReaderResponse(
        paper=ReaderPaperView(id=paper.id, status=paper.status, metadata=paper.metadata),
        document=ReaderDocumentSummary(
            id=document.id,
            paper_id=document.paper_id,
            page_count=document.page_count,
            parser_name=document.parser_name,
            parser_version=document.parser_version,
            document_hash=document.document_hash,
            sections=[
                ReaderSectionSummary(
                    id=section.id,
                    title=section.title,
                    order=section.order,
                    page_start=section.page_start,
                    page_end=section.page_end,
                    paragraph_count=len(section.paragraphs),
                )
                for section in document.sections
            ],
            references=[
                ReaderReference(
                    id=reference.id,
                    order=reference.order,
                    raw_text=reference.raw_text,
                    title=reference.title,
                    authors=reference.authors,
                    year=reference.year,
                )
                for reference in document.references
            ],
            section_count=len(document.sections),
            paragraph_count=sum(len(section.paragraphs) for section in document.sections),
            figure_count=len(document.figures),
            table_count=len(document.tables),
            equation_count=len(document.equations),
            reference_count=len(document.references),
        ),
        analysis=analysis_record[0] if analysis_record else None,
        visualizations=plan_visualizations(analysis_record[0] if analysis_record else None),
        source=ReaderSource(
            available=source_available,
            endpoint=f"/api/papers/{paper_id}/source" if source_available else None,
            page_count=document.page_count,
        ),
        verification=verification,
    )


@router.get("/api/papers/{paper_id}/source")
async def get_source(paper_id: str, request: Request) -> FileResponse:
    """Serve the paper's persisted PDF without exposing filesystem paths."""

    paper = request.app.state.database.get_by_id(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found.")
    source_path = _safe_source_path(request, request.app.state.database.get_source_pdf_path(paper_id))
    if source_path is None:
        raise HTTPException(status_code=404, detail="Original PDF is unavailable.")
    return FileResponse(
        source_path,
        media_type="application/pdf",
        filename=f"{paper.metadata.arxiv_id.replace('/', '_')}.pdf",
        content_disposition_type="inline",
    )


@router.post("/api/papers/{paper_id}/extract", response_model=PaperIR)
async def extract_paper(paper_id: str, request: Request) -> PaperIR:
    """Run focused evidence-grounded research extraction for a document."""

    try:
        return await request.app.state.extraction_service.extract(paper_id)
    except ResearchExtractionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/papers/{paper_id}/analysis", response_model=PaperIR)
async def get_analysis(paper_id: str, request: Request) -> PaperIR:
    """Return the persisted PaperIR for a paper."""

    analysis = request.app.state.database.get_analysis_record(paper_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Paper analysis not found.")
    return analysis[0]


@router.post("/api/papers/{paper_id}/verify", response_model=PaperVerificationResponse)
async def verify_paper(paper_id: str, request: Request) -> PaperVerificationResponse:
    """Verify each persisted semantic claim against only its linked evidence."""

    try:
        return await request.app.state.verification_service.verify(paper_id)
    except PaperVerificationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PaperPersistenceError as exc:
        raise HTTPException(status_code=500, detail="The paper verification could not be loaded or saved.") from exc


@router.get("/api/papers/{paper_id}/verification", response_model=PaperVerificationResponse)
async def get_verification(paper_id: str, request: Request) -> PaperVerificationResponse:
    """Return only verification results current for the stored analysis/document."""

    if request.app.state.database.get_by_id(paper_id) is None:
        raise HTTPException(status_code=404, detail="Paper not found.")
    try:
        return request.app.state.verification_service.current(paper_id)
    except PaperPersistenceError as exc:
        raise HTTPException(status_code=500, detail="The paper verification could not be loaded.") from exc


@router.post("/api/papers/{paper_id}/chat/sessions", response_model=ChatSessionCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_chat_session(paper_id: str, request: Request) -> ChatSessionCreateResponse:
    """Create a chat bound to the paper's current normalized document version."""

    try:
        session = request.app.state.chat_service.create_session(paper_id)
        return ChatSessionCreateResponse(session_id=session.id, **session.model_dump(exclude={"id"}))
    except ChatSessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PaperPersistenceError as exc:
        raise HTTPException(status_code=500, detail="The chat session could not be saved.") from exc


@router.get("/api/papers/{paper_id}/chat/sessions/{session_id}", response_model=ChatSessionResponse)
async def get_chat_session(paper_id: str, session_id: str, request: Request) -> ChatSessionResponse:
    try:
        session, messages = request.app.state.chat_service.get_session(paper_id, session_id)
        return ChatSessionResponse(session=session, messages=messages)
    except ChatSessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/papers/{paper_id}/chat/sessions/{session_id}/messages", response_model=ChatAnswerResponse)
async def send_chat_message(paper_id: str, session_id: str, payload: ChatQuestion, request: Request) -> ChatAnswerResponse:
    try:
        message = await request.app.state.chat_service.answer(paper_id, session_id, payload.question)
        assert message.status is not None
        return ChatAnswerResponse(
            message_id=message.id,
            answer=message.content,
            status=message.status,
            sufficient_evidence=bool(message.sufficient_evidence),
            citations=message.citations,
        )
    except ChatSessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChatDocumentChanged as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ChatGenerationUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PaperChatError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PaperPersistenceError as exc:
        raise HTTPException(status_code=500, detail="The chat turn could not be saved.") from exc


def _safe_source_path(request: Request, source_path: object) -> Path | None:
    if not isinstance(source_path, Path):
        return None
    candidate = source_path.expanduser().resolve()
    root = Path(request.app.state.settings.paper_storage_path).expanduser().resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None
