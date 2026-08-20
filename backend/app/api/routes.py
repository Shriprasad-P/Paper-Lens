"""HTTP routes for the initial PaperLens foundation."""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse, PlainTextResponse

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
from ..models.research import CitationGraph, ComparisonRequest, PaperComparisonIR, WorkspaceCreate, WorkspaceResponse, Workspace
from ..models.research import ResearchDepth, ResearchRun, ResearchRunCreate, ResearchRunEvent, ResearchRunResponse, ResearchRunStatus
from ..comparison.service import ComparisonError, PaperComparisonService
from ..citation_graph.service import build_citation_graph
from ..research.agent import ResearchAgentError

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


@router.get("/health/live")
async def health_live() -> dict[str, str]:
    """Process liveness probe; it intentionally does not call dependencies."""

    return {"status": "ok", "service": "paperlens-api"}


@router.get("/health/ready")
async def health_ready(request: Request) -> dict[str, Any]:
    """Readiness probe for the database and required local paper storage."""

    database_ok = request.app.state.database.healthcheck()
    storage_root = Path(request.app.state.settings.paper_storage_path).expanduser()
    storage_ok = storage_root.is_dir() and storage_root.exists()
    if not database_ok or not storage_ok:
        raise HTTPException(status_code=503, detail="The service is not ready.")
    return {"status": "ready", "database": "ok", "storage": "ok"}


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(request: Request) -> PlainTextResponse:
    """Expose bounded process metrics without paper content or user labels."""

    if not request.app.state.settings.metrics_enabled:
        raise HTTPException(status_code=404, detail="Metrics are disabled.")
    return PlainTextResponse(request.app.state.metrics.prometheus(), media_type="text/plain; version=0.0.4")


@router.post("/api/papers/ingest", response_model=IngestedPaper, status_code=status.HTTP_200_OK)
async def ingest_paper(payload: IngestRequest, request: Request) -> IngestedPaper:
    """Ingest an arXiv paper and return its normalized document structure."""

    idempotency_key = _idempotency_key(request)
    scope = f"ingest:{_scope_digest(payload.source.strip())}"
    if idempotency_key:
        cached = request.app.state.database.get_idempotent_response(scope, idempotency_key)
        if cached is not None:
            return IngestedPaper.model_validate(cached)
    try:
        result = await request.app.state.ingestion_service.ingest(payload.source)
        if idempotency_key:
            request.app.state.database.save_idempotent_response(scope, idempotency_key, result.model_dump(mode="json"))
        return result
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
                    venue=reference.venue,
                    doi=reference.doi,
                    arxiv_id=reference.arxiv_id,
                    url=reference.url,
                    evidence_ids=reference.evidence_ids,
                )
                for reference in document.references
            ],
            section_count=len(document.sections),
            paragraph_count=sum(len(section.paragraphs) for section in document.sections),
            figure_count=len(document.figures),
            table_count=len(document.tables),
            equation_count=len(document.equations),
            reference_count=len(document.references),
            figures=document.figures,
            tables=document.tables,
            equations=document.equations,
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


@router.get("/api/papers/{paper_id}/documents/{document_id}/figures/{figure_id}")
async def get_figure_image(paper_id: str, document_id: str, figure_id: str, request: Request) -> FileResponse:
    """Serve only a parser-recorded figure image below the configured paper root."""

    document = request.app.state.database.get_document(paper_id)
    if document is None or document.id != document_id:
        raise HTTPException(status_code=404, detail="Structured document not found.")
    figure = next((item for item in document.figures if item.id == figure_id), None)
    if figure is None or not figure.image_reference:
        raise HTTPException(status_code=404, detail="Figure image is unavailable.")
    image_path = _safe_source_path(request, Path(figure.image_reference))
    if image_path is None:
        raise HTTPException(status_code=404, detail="Figure image is unavailable.")
    media_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    return FileResponse(image_path, media_type=media_type, filename=image_path.name, content_disposition_type="inline")


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
    idempotency_key = _idempotency_key(request)
    scope = f"chat:{_scope_digest(f'{paper_id}:{session_id}:{payload.question.strip()}')}"
    if idempotency_key:
        cached = request.app.state.database.get_idempotent_response(scope, idempotency_key)
        if cached is not None:
            return ChatAnswerResponse.model_validate(cached)
    try:
        message = await request.app.state.chat_service.answer(paper_id, session_id, payload.question)
        assert message.status is not None
        response = ChatAnswerResponse(
            message_id=message.id,
            answer=message.content,
            status=message.status,
            sufficient_evidence=bool(message.sufficient_evidence),
            citations=message.citations,
        )
        if idempotency_key:
            request.app.state.database.save_idempotent_response(scope, idempotency_key, response.model_dump(mode="json"))
        return response
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


@router.post("/api/workspaces", response_model=Workspace, status_code=status.HTTP_201_CREATED)
async def create_workspace(payload: WorkspaceCreate, request: Request) -> Workspace:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Workspace name is required.")
    try:
        return request.app.state.database.create_workspace(name)
    except PaperPersistenceError as exc:
        raise HTTPException(status_code=500, detail="The workspace could not be saved.") from exc


@router.get("/api/workspaces", response_model=list[Workspace])
async def list_workspaces(request: Request) -> list[Workspace]:
    return request.app.state.database.list_workspaces()


@router.get("/api/workspaces/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(workspace_id: str, request: Request) -> WorkspaceResponse:
    workspace = request.app.state.database.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return WorkspaceResponse(workspace=workspace, papers=request.app.state.database.get_workspace_papers(workspace_id))


@router.post("/api/workspaces/{workspace_id}/papers/{paper_id}", response_model=WorkspaceResponse)
async def add_workspace_paper(workspace_id: str, paper_id: str, request: Request) -> WorkspaceResponse:
    try:
        request.app.state.database.add_workspace_paper(workspace_id, paper_id)
        workspace = request.app.state.database.get_workspace(workspace_id)
        if workspace is None:
            raise HTTPException(status_code=404, detail="Workspace not found.")
        return WorkspaceResponse(workspace=workspace, papers=request.app.state.database.get_workspace_papers(workspace_id))
    except PaperPersistenceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/api/workspaces/{workspace_id}/papers/{paper_id}", response_model=WorkspaceResponse)
async def remove_workspace_paper(workspace_id: str, paper_id: str, request: Request) -> WorkspaceResponse:
    if not request.app.state.database.remove_workspace_paper(workspace_id, paper_id):
        raise HTTPException(status_code=404, detail="Workspace paper not found.")
    workspace = request.app.state.database.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return WorkspaceResponse(workspace=workspace, papers=request.app.state.database.get_workspace_papers(workspace_id))


@router.post("/api/workspaces/{workspace_id}/compare", response_model=PaperComparisonIR)
async def compare_workspace(payload: ComparisonRequest, workspace_id: str, request: Request) -> PaperComparisonIR:
    if request.app.state.database.get_workspace(workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    allowed = {item.paper_id for item in request.app.state.database.get_workspace_papers(workspace_id)}
    if any(paper_id not in allowed for paper_id in payload.paper_ids):
        raise HTTPException(status_code=422, detail="Comparison papers must belong to the workspace.")
    try:
        return PaperComparisonService(request.app.state.database).compare(payload.paper_ids)
    except ComparisonError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/papers/{paper_id}/citation-graph", response_model=CitationGraph)
async def citation_graph(paper_id: str, request: Request) -> CitationGraph:
    try:
        return build_citation_graph(request.app.state.database, paper_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/research/runs", response_model=ResearchRunResponse, status_code=status.HTTP_201_CREATED)
async def create_research_run(payload: ResearchRunCreate, request: Request) -> ResearchRunResponse:
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Research question is required.")
    if payload.workspace_id and request.app.state.database.get_workspace(payload.workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    defaults = {
        ResearchDepth.QUICK: (1, 10, 3),
        ResearchDepth.STANDARD: (2, 20, 5),
        ResearchDepth.DEEP: (3, 30, 8),
    }[payload.depth]
    settings = request.app.state.settings
    run = ResearchRun(
        id=f"research_{uuid4().hex}",
        workspace_id=payload.workspace_id,
        research_question=question,
        status=ResearchRunStatus.CREATED,
        max_iterations=min(defaults[0], settings.research_max_iterations),
        max_candidates=min(defaults[1], settings.research_max_candidates),
        max_ingested_papers=min(defaults[2], settings.research_max_ingested_papers),
        planner_provider=getattr(request.app.state.research_agent.planner.provider, "__class__", type(None)).__name__ if getattr(request.app.state.research_agent, "planner", None) else None,
        planner_model=getattr(getattr(request.app.state.research_agent, "planner", None), "provider", None) and getattr(request.app.state.research_agent.planner.provider, "model", None),
    )
    try:
        request.app.state.database.create_research_run(run)
        request.app.state.database.add_research_event(ResearchRunEvent(id=f"event_{uuid4().hex}", research_run_id=run.id, event_type="RUN_CREATED", message="Research run created.", metadata={"depth": payload.depth.value}))
    except PaperPersistenceError as exc:
        raise HTTPException(status_code=500, detail="The research run could not be saved.") from exc
    return _research_response(request, run.id)


@router.get("/api/research/runs/{run_id}", response_model=ResearchRunResponse)
async def get_research_run(run_id: str, request: Request) -> ResearchRunResponse:
    return _research_response(request, run_id)


@router.post("/api/research/runs/{run_id}/execute", response_model=ResearchRunResponse)
async def execute_research_run(run_id: str, request: Request) -> ResearchRunResponse:
    try:
        await request.app.state.research_agent.execute(run_id)
    except ResearchAgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _research_response(request, run_id)


@router.post("/api/research/runs/{run_id}/cancel", response_model=ResearchRunResponse)
async def cancel_research_run(run_id: str, request: Request) -> ResearchRunResponse:
    try:
        await request.app.state.research_agent.cancel(run_id)
    except ResearchAgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _research_response(request, run_id)


@router.get("/api/research/runs/{run_id}/report")
async def get_research_report(run_id: str, request: Request) -> object:
    if request.app.state.database.get_research_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Research run not found.")
    report = request.app.state.database.get_research_report(run_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Research report not found.")
    return report


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


def _idempotency_key(request: Request) -> str | None:
    """Accept only bounded opaque retry keys; never use arbitrary header text in SQL."""

    value = request.headers.get("idempotency-key", "").strip()
    if not value:
        return None
    if len(value) > 128 or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for char in value):
        raise HTTPException(status_code=422, detail="Invalid Idempotency-Key header.")
    return value


def _scope_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _research_response(request: Request, run_id: str) -> ResearchRunResponse:
    run = request.app.state.database.get_research_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found.")
    report = request.app.state.database.get_research_report(run_id)
    coverage = report.coverage if report else None
    return ResearchRunResponse(
        run=run,
        plan=request.app.state.database.get_research_plan(run_id),
        queries=request.app.state.database.get_research_queries(run_id),
        candidates=request.app.state.database.get_research_candidates(run_id),
        events=request.app.state.database.get_research_events(run_id),
        coverage=coverage,
        report=report,
    )
