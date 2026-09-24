"""HTTP routes for the initial PaperLens foundation."""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import fitz
from fastapi import APIRouter, HTTPException, Request, Response, UploadFile, File, status
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

from ..ingestion.errors import (
    ArxivMetadataError,
    ArxivNotFoundError,
    IngestionError,
    InvalidArxivIdentifierError,
    PaperParseError,
    PaperPersistenceError,
    PdfDownloadError,
    PdfTooLargeError,
    PdfValidationError,
)
from ..ingestion.resolver import ResolverError, ResolvedPaper
from ..auth import audit, clear_session_cookie, get_current_user, issue_session, normalize_email, password_hash, require_current_user, revoke_presented_session, set_session_cookie, verify_password
from ..models.auth import UserLogin, UserRegistration, UserResponse
from ..models.provider import ProviderConfigCreate, ProviderConfigPublic, ProviderTestResponse
from ..provider_config import ProviderSecretError, decrypt_secret, encrypt_secret, mask_secret, public_config, runtime_provider, test_provider_connection
from ..visualization.archify import ArchifyAdapterError, render_archify_ir_async
from ..extraction.service import ResearchExtractionError, ResearchExtractionService
from ..models.document import Evidence, PaperIR, StructuredDocument
from ..models.interactive_paper import InteractivePaper
from ..interactive.service import InteractivePaperError, InteractivePaperService
from ..verification.service import PaperVerificationService
from ..chat.service import PaperChatService
from ..models.paper import IngestRequest, IngestedPaper
from ..models.reader import (
    CapabilityFlags,
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


@router.post("/api/auth/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: UserRegistration, request: Request, response: Response) -> UserResponse:
    email = normalize_email(payload.email)
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(status_code=422, detail="A valid email address is required.")
    if request.app.state.database.get_user_by_email(email) is not None:
        audit(request, "registration_failed", None, {"reason": "duplicate_identifier"})
        raise HTTPException(status_code=409, detail="An account with that email already exists.")
    try:
        user = request.app.state.database.create_user(f"user_{uuid4().hex}", email, password_hash(payload.password))
    except PaperPersistenceError as exc:
        audit(request, "registration_failed", None, {"reason": "persistence"})
        raise HTTPException(status_code=409, detail="An account with that email already exists.") from exc
    token = issue_session(request, user.id)
    set_session_cookie(request, response, token)
    audit(request, "registration", user.id)
    return UserResponse(user=user)


@router.post("/api/auth/login", response_model=UserResponse)
async def login(payload: UserLogin, request: Request, response: Response) -> UserResponse:
    email = normalize_email(payload.email)
    found = request.app.state.database.get_user_by_email(email)
    if found is None or not verify_password(payload.password, found[1]):
        audit(request, "login_failed", None, {"reason": "invalid_credentials"})
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    user = found[0]
    token = issue_session(request, user.id)
    set_session_cookie(request, response, token)
    audit(request, "login_success", user.id)
    return UserResponse(user=user)


@router.post("/api/auth/logout")
async def logout(request: Request, response: Response) -> dict[str, bool]:
    user = get_current_user(request)
    revoked = revoke_presented_session(request)
    clear_session_cookie(request, response)
    audit(request, "logout", user.id if user else None, {"session_revoked": revoked})
    return {"ok": True}


@router.get("/api/auth/me", response_model=UserResponse)
async def current_user(request: Request) -> UserResponse:
    return UserResponse(user=require_current_user(request))


@router.get("/api/provider-configs", response_model=list[ProviderConfigPublic])
async def list_provider_configs(request: Request) -> list[ProviderConfigPublic]:
    owner_id = require_current_user(request).id
    return [public_config(record) for record in request.app.state.database.list_provider_configs(owner_id)]


@router.post("/api/provider-configs", response_model=ProviderConfigPublic, status_code=status.HTTP_201_CREATED)
async def save_provider_config(payload: ProviderConfigCreate, request: Request) -> ProviderConfigPublic:
    owner_id = require_current_user(request).id
    if payload.provider_type.value in {"ollama", "mlx"} and not payload.base_url.startswith(("http://127.0.0.1", "http://localhost")):
        raise HTTPException(status_code=422, detail="Local providers must use an explicitly configured loopback endpoint.")
    existing = next((item for item in request.app.state.database.list_provider_configs(owner_id) if item.display_name == payload.display_name), None)
    secret = payload.api_key
    if secret is None and existing is not None:
        encrypted_secret = existing.encrypted_secret
        hint = existing.secret_hint
    else:
        encrypted_secret = encrypt_secret(request.app.state.settings, secret or "")
        hint = mask_secret(secret)
    try:
        record = request.app.state.database.save_provider_config(
            config_id=existing.id if existing else f"provider_{uuid4().hex}", owner_id=owner_id,
            provider_type=payload.provider_type.value, display_name=payload.display_name,
            base_url=payload.base_url.rstrip("/"), generation_model=payload.generation_model,
            embedding_model=payload.embedding_model, encrypted_secret=encrypted_secret,
            secret_version="fernet-v1", secret_hint=hint, enabled=payload.enabled,
        )
    except PaperPersistenceError as exc:
        raise HTTPException(status_code=409, detail="A provider with that name already exists.") from exc
    audit(request, "provider_config_saved", owner_id, {"provider_type": payload.provider_type.value})
    return public_config(record)


@router.post("/api/provider-configs/{config_id}/test", response_model=ProviderTestResponse)
async def test_provider_config(config_id: str, request: Request) -> ProviderTestResponse:
    owner_id = require_current_user(request).id
    record = request.app.state.database.get_provider_config(config_id, owner_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Provider configuration not found.")
    config = public_config(record)
    tested_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    try:
        message = await test_provider_connection(config, decrypt_secret(request.app.state.settings, record.encrypted_secret))
    except (ProviderSecretError, httpx.HTTPError, ValueError, TypeError) as exc:
        request.app.state.database.update_provider_test(config_id, owner_id, status="FAILED", tested_at=tested_at)
        raise HTTPException(status_code=502, detail="The provider connection test failed.") from exc
    request.app.state.database.update_provider_test(config_id, owner_id, status="PASSED", tested_at=tested_at)
    return ProviderTestResponse(provider_id=config_id, status="PASSED", message=message, tested_at=tested_at)


@router.delete("/api/provider-configs/{config_id}")
async def delete_provider_config(config_id: str, request: Request) -> dict[str, bool]:
    owner_id = require_current_user(request).id
    if not request.app.state.database.delete_provider_config(config_id, owner_id):
        raise HTTPException(status_code=404, detail="Provider configuration not found.")
    audit(request, "provider_config_revoked", owner_id, {"provider_id": config_id})
    return {"ok": True}


@router.get("/api/capabilities", response_model=CapabilityFlags)
async def capabilities(request: Request) -> CapabilityFlags:
    """Expose beta feature availability without leaking provider configuration."""

    settings = request.app.state.settings
    current = get_current_user(request)
    provider_configs = request.app.state.database.list_provider_configs(current.id) if current is not None else []
    return CapabilityFlags(
        ai_analysis_enabled=settings.ai_analysis_enabled,
        semantic_retrieval_enabled=settings.semantic_retrieval_enabled,
        research_agent_enabled=settings.research_agent_enabled,
        provider_configured=bool(provider_configs) or bool(settings.ai_api_key) or settings.ai_provider.lower() in {"ollama", "ollama_local", "local_ollama"},
        provider_types=sorted({item.provider_type for item in provider_configs}) or ([settings.ai_provider] if settings.ai_provider else []),
        supported_sources=["arxiv", "doi", "pmid", "pmcid", "scholarly_url", "citation_text", "bibtex", "ris", "pdf_upload"],
    )


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """Report service and persistence health without exposing implementation details."""

    database_ok = request.app.state.database.healthcheck()
    return {
        "status": "ok" if database_ok else "degraded",
        "service": "paperlens-api",
        "database": "ok" if database_ok else "unavailable",
        "version": request.app.state.settings.release_version,
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


@router.get("/health/version")
async def health_version(request: Request) -> dict[str, str]:
    """Return safe release metadata for deployment diagnosis."""

    settings = request.app.state.settings
    return {
        "version": settings.release_version,
        "git_sha": settings.build_sha,
        "build_timestamp": settings.build_timestamp,
    }


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(request: Request) -> PlainTextResponse:
    """Expose bounded process metrics without paper content or user labels."""

    if not request.app.state.settings.metrics_enabled:
        raise HTTPException(status_code=404, detail="Metrics are disabled.")
    body = request.app.state.metrics.prometheus()
    execution = request.app.state.database.research_execution_metrics()
    body += "\n".join(f"paperlens_research_{key} {value}" for key, value in sorted(execution.items())) + "\n"
    parser = getattr(getattr(request.app.state, "ingestion_service", None), "pdf_parser", None)
    if parser is not None:
        parse_metrics = dict(getattr(parser, "metrics", {}))
        parse_metrics["active_processes"] = int(getattr(parser, "active_processes", 0))
        parse_metrics["max_active_processes"] = int(getattr(parser, "max_active_processes", 0))
        body += "\n".join(f"paperlens_pdf_parse_{key} {value}" for key, value in sorted(parse_metrics.items())) + "\n"
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4")


@router.post("/api/papers/ingest", response_model=IngestedPaper, status_code=status.HTTP_200_OK)
async def ingest_paper(payload: IngestRequest, request: Request) -> IngestedPaper:
    """Ingest an arXiv paper and return its normalized document structure."""

    owner_id = require_current_user(request).id
    idempotency_key = _idempotency_key(request)
    scope = f"ingest:{owner_id}:{_scope_digest(payload.source.strip())}"
    if idempotency_key:
        cached = request.app.state.database.get_idempotent_response(scope, idempotency_key)
        if cached is not None:
            return IngestedPaper.model_validate(cached)
    try:
        result = await request.app.state.ingestion_service.ingest_input(payload.source, owner_id)
        if idempotency_key:
            request.app.state.database.save_idempotent_response(scope, idempotency_key, result.model_dump(mode="json"))
        return result
    except InvalidArxivIdentifierError as exc:
        raise HTTPException(status_code=422, detail="Invalid arXiv identifier.") from exc
    except ArxivNotFoundError as exc:
        raise HTTPException(status_code=404, detail="The arXiv paper was not found.") from exc
    except ArxivMetadataError as exc:
        raise HTTPException(status_code=502, detail="Unable to retrieve metadata from arXiv.") from exc
    except PdfTooLargeError as exc:
        raise HTTPException(status_code=413, detail={"code": exc.code, "message": "The paper exceeds the configured size limit."}) from exc
    except PdfValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": getattr(exc, "code", "PDF_MALFORMED"), "message": "The downloaded paper is not a usable PDF."}) from exc
    except PdfDownloadError as exc:
        raise HTTPException(status_code=502, detail="Unable to retrieve the paper PDF.") from exc
    except PaperParseError as exc:
        raise HTTPException(status_code=422, detail={"code": getattr(exc, "code", "PDF_PARSE_FAILED"), "message": str(exc)}) from exc
    except PaperPersistenceError as exc:
        raise HTTPException(status_code=500, detail="The paper could not be saved.") from exc
    except IngestionError as exc:
        raise HTTPException(status_code=500, detail="The paper could not be ingested.") from exc
    except ResolverError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/api/papers/resolve", response_model=ResolvedPaper)
async def resolve_paper(payload: IngestRequest, request: Request) -> ResolvedPaper:
    require_current_user(request)
    try:
        return await request.app.state.ingestion_service.resolve(payload.source)
    except ResolverError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/papers/upload", response_model=IngestedPaper, status_code=status.HTTP_200_OK)
async def upload_paper(request: Request, file: UploadFile = File(...)) -> IngestedPaper:
    owner_id = require_current_user(request).id
    filename = file.filename or "paper.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail="Only PDF uploads are supported.")
    content = await file.read()
    try:
        return await request.app.state.ingestion_service.ingest_upload(content, filename, owner_id)
    except PdfTooLargeError as exc:
        raise HTTPException(status_code=413, detail={"code": getattr(exc, "code", "PDF_TOO_LARGE"), "message": "The uploaded paper exceeds the configured size limit."}) from exc
    except PdfValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": getattr(exc, "code", "PDF_MALFORMED"), "message": "The uploaded file is not a usable PDF."}) from exc
    except PaperParseError as exc:
        raise HTTPException(status_code=422, detail={"code": getattr(exc, "code", "PDF_PARSE_FAILED"), "message": str(exc)}) from exc
    except PdfDownloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/papers", response_model=list[IngestedPaper])
async def list_papers(request: Request) -> list[IngestedPaper]:
    return request.app.state.database.list_papers(require_current_user(request).id)


@router.get("/api/papers/{paper_id}", response_model=IngestedPaper)
async def get_paper(paper_id: str, request: Request) -> IngestedPaper:
    """Return a completed normalized paper by its stable internal ID."""

    owner_id = require_current_user(request).id
    paper = request.app.state.database.get_by_id(paper_id, owner_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found.")
    return paper


@router.get("/api/papers/{paper_id}/document", response_model=StructuredDocument)
async def get_document(paper_id: str, request: Request) -> StructuredDocument:
    """Return the source-preserving normalized document for a paper."""

    owner_id = require_current_user(request).id
    document = request.app.state.database.get_document(paper_id, owner_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Structured document not found.")
    return document


@router.get("/api/papers/{paper_id}/evidence/{evidence_id}", response_model=Evidence)
async def get_evidence(paper_id: str, evidence_id: str, request: Request) -> Evidence:
    """Return one provenance record scoped to its paper."""

    owner_id = require_current_user(request).id
    evidence = request.app.state.database.get_evidence(paper_id, evidence_id, owner_id)
    if evidence is None:
        raise HTTPException(status_code=404, detail="Evidence not found.")
    return evidence


@router.get("/api/papers/{paper_id}/reader", response_model=ReaderResponse)
async def get_reader(paper_id: str, request: Request) -> ReaderResponse:
    """Return the small reader payload; evidence bodies are loaded on demand."""

    owner_id = require_current_user(request).id
    provider_configs = request.app.state.database.list_provider_configs(owner_id)
    paper = request.app.state.database.get_by_id(paper_id, owner_id)
    document = request.app.state.database.get_document(paper_id, owner_id)
    if paper is None or document is None:
        raise HTTPException(status_code=404, detail="Paper reader data not found.")
    analysis_record = request.app.state.database.get_analysis_record(paper_id, owner_id)
    verification = _verification_service(request, owner_id).current(paper_id, owner_id)
    source_path = request.app.state.database.get_source_pdf_path(paper_id, owner_id)
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
        capabilities=CapabilityFlags(
            ai_analysis_enabled=request.app.state.settings.ai_analysis_enabled,
            semantic_retrieval_enabled=request.app.state.settings.semantic_retrieval_enabled,
            research_agent_enabled=request.app.state.settings.research_agent_enabled,
            provider_configured=bool(provider_configs) or bool(request.app.state.settings.ai_api_key) or request.app.state.settings.ai_provider.lower() in {"ollama", "ollama_local", "local_ollama", "mlx", "mlx_lm"},
            provider_types=sorted({item.provider_type for item in provider_configs}) or ([request.app.state.settings.ai_provider] if request.app.state.settings.ai_provider else []),
            supported_sources=["arxiv", "doi", "pmid", "pmcid", "scholarly_url", "citation_text", "bibtex", "ris", "pdf_upload"],
        ),
        interactive_paper=await _interactive_paper(request, paper_id, owner_id),
    )


@router.get("/api/papers/{paper_id}/source")
async def get_source(paper_id: str, request: Request) -> FileResponse:
    """Serve the paper's persisted PDF without exposing filesystem paths."""

    owner_id = require_current_user(request).id
    paper = request.app.state.database.get_by_id(paper_id, owner_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found.")
    source_path = _safe_source_path(request, request.app.state.database.get_source_pdf_path(paper_id, owner_id))
    if source_path is None:
        raise HTTPException(status_code=404, detail="Original PDF is unavailable.")
    return FileResponse(
        source_path,
        media_type="application/pdf",
        filename=f"{paper.metadata.arxiv_id.replace('/', '_')}.pdf",
        content_disposition_type="inline",
    )


@router.get("/api/papers/{paper_id}/documents/{document_id}/figures/{figure_id}")
async def get_figure_image(paper_id: str, document_id: str, figure_id: str, request: Request) -> Response:
    """Serve an extracted figure or a bounded render from its original PDF page."""

    owner_id = require_current_user(request).id
    document = request.app.state.database.get_document(paper_id, owner_id)
    if document is None or document.id != document_id:
        raise HTTPException(status_code=404, detail="Structured document not found.")
    figure = next((item for item in document.figures if item.id == figure_id), None)
    if figure is None:
        raise HTTPException(status_code=404, detail="Figure image is unavailable.")
    if figure.image_reference:
        image_path = _safe_source_path(request, Path(figure.image_reference))
        if image_path is None:
            raise HTTPException(status_code=404, detail="Figure image is unavailable.")
        media_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
        return FileResponse(image_path, media_type=media_type, filename=image_path.name, content_disposition_type="inline")
    source_path = _safe_source_path(request, request.app.state.database.get_source_pdf_path(paper_id, owner_id))
    if source_path is None or figure.page is None:
        raise HTTPException(status_code=404, detail="Figure image is unavailable.")
    try:
        with fitz.open(source_path) as pdf:
            if figure.page < 1 or figure.page > len(pdf):
                raise HTTPException(status_code=404, detail="Figure image is unavailable.")
            page = pdf[figure.page - 1]
            clip = None
            region = figure.source_region
            if region is not None and region.x0 is not None and region.x1 is not None and region.y0 is not None and region.y1 is not None:
                clip = fitz.Rect(
                    max(0, region.x0 - 16),
                    max(0, region.y0 - 16),
                    min(page.rect.width, region.x1 + 16),
                    min(page.rect.height, region.y1 + 16),
                )
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), clip=clip, alpha=False)
            return Response(content=pixmap.tobytes("png"), media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Figure image is unavailable.") from exc


@router.post("/api/papers/{paper_id}/extract", response_model=PaperIR)
async def extract_paper(paper_id: str, request: Request) -> PaperIR:
    """Run focused evidence-grounded research extraction for a document."""

    if _capability_disabled(request, "ai_analysis_enabled"):
        raise HTTPException(status_code=503, detail="AI analysis is not enabled for this deployment.")
    owner_id = require_current_user(request).id
    try:
        return await _extraction_service(request, owner_id).extract(paper_id, owner_id)
    except ResearchExtractionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/papers/{paper_id}/interactive", response_model=InteractivePaper)
async def generate_interactive_paper(paper_id: str, request: Request) -> InteractivePaper:
    """Assemble, optionally simplify, and persist the unified interactive paper."""

    owner_id = require_current_user(request).id
    simplify = request.app.state.settings.ai_analysis_enabled
    try:
        return await _interactive_service(request, owner_id).generate(paper_id, owner_id, simplify=simplify)
    except InteractivePaperError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/papers/{paper_id}/interactive", response_model=InteractivePaper)
async def get_interactive_paper(paper_id: str, request: Request) -> InteractivePaper:
    """Return the current interactive paper, assembling from evidence if needed."""

    owner_id = require_current_user(request).id
    try:
        return await _interactive_service(request, owner_id).get_or_assemble(paper_id, owner_id)
    except InteractivePaperError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/papers/{paper_id}/interactive/{block_id}/archify", response_class=HTMLResponse)
async def render_interactive_archify(paper_id: str, block_id: str, request: Request) -> HTMLResponse:
    """Render one validated Archify block as a self-contained reader artifact."""

    owner_id = require_current_user(request).id
    try:
        paper = await _interactive_service(request, owner_id).get_or_assemble(paper_id, owner_id)
    except InteractivePaperError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    block = next((item for item in paper.blocks if item.id == block_id), None)
    if block is None or not block.archify_ir:
        raise HTTPException(status_code=404, detail="Archify visualization is unavailable.")
    try:
        html = await render_archify_ir_async(block.archify_ir)
    except (ArchifyAdapterError, OSError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail="Archify visualization could not be rendered.") from exc
    return HTMLResponse(content=html, headers={"X-PaperLens-Visualization": "archify-2.16.0", "X-Content-Type-Options": "nosniff"})


@router.get("/api/papers/{paper_id}/analysis", response_model=PaperIR)
async def get_analysis(paper_id: str, request: Request) -> PaperIR:
    """Return the persisted PaperIR for a paper."""

    owner_id = require_current_user(request).id
    analysis = request.app.state.database.get_analysis_record(paper_id, owner_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Paper analysis not found.")
    return analysis[0]


@router.post("/api/papers/{paper_id}/verify", response_model=PaperVerificationResponse)
async def verify_paper(paper_id: str, request: Request) -> PaperVerificationResponse:
    """Verify each persisted semantic claim against only its linked evidence."""

    if _capability_disabled(request, "ai_analysis_enabled"):
        raise HTTPException(status_code=503, detail="AI verification is not enabled for this deployment.")
    owner_id = require_current_user(request).id
    try:
        return await _verification_service(request, owner_id).verify(paper_id, owner_id)
    except PaperVerificationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PaperPersistenceError as exc:
        raise HTTPException(status_code=500, detail="The paper verification could not be loaded or saved.") from exc


@router.get("/api/papers/{paper_id}/verification", response_model=PaperVerificationResponse)
async def get_verification(paper_id: str, request: Request) -> PaperVerificationResponse:
    """Return only verification results current for the stored analysis/document."""

    owner_id = require_current_user(request).id
    if request.app.state.database.get_by_id(paper_id, owner_id) is None:
        raise HTTPException(status_code=404, detail="Paper not found.")
    try:
        return _verification_service(request, owner_id).current(paper_id, owner_id)
    except PaperPersistenceError as exc:
        raise HTTPException(status_code=500, detail="The paper verification could not be loaded.") from exc


@router.post("/api/papers/{paper_id}/chat/sessions", response_model=ChatSessionCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_chat_session(paper_id: str, request: Request) -> ChatSessionCreateResponse:
    """Create a chat bound to the paper's current normalized document version."""

    if _capability_disabled(request, "ai_analysis_enabled"):
        raise HTTPException(status_code=503, detail="Paper Chat is not enabled for this deployment.")
    owner_id = require_current_user(request).id
    try:
        session = _chat_service(request, owner_id).create_session(paper_id, owner_id)
        return ChatSessionCreateResponse(session_id=session.id, **session.model_dump(exclude={"id"}))
    except ChatSessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PaperPersistenceError as exc:
        raise HTTPException(status_code=500, detail="The chat session could not be saved.") from exc


@router.get("/api/papers/{paper_id}/chat/sessions/{session_id}", response_model=ChatSessionResponse)
async def get_chat_session(paper_id: str, session_id: str, request: Request) -> ChatSessionResponse:
    owner_id = require_current_user(request).id
    try:
        session, messages = _chat_service(request, owner_id).get_session(paper_id, session_id, owner_id)
        return ChatSessionResponse(session=session, messages=messages)
    except ChatSessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/papers/{paper_id}/chat/sessions/{session_id}/messages", response_model=ChatAnswerResponse)
async def send_chat_message(paper_id: str, session_id: str, payload: ChatQuestion, request: Request) -> ChatAnswerResponse:
    if _capability_disabled(request, "ai_analysis_enabled"):
        raise HTTPException(status_code=503, detail="Paper Chat is not enabled for this deployment.")
    owner_id = require_current_user(request).id
    idempotency_key = _idempotency_key(request)
    scope = f"chat:{owner_id}:{_scope_digest(f'{paper_id}:{session_id}:{payload.question.strip()}')}"
    if idempotency_key:
        cached = request.app.state.database.get_idempotent_response(scope, idempotency_key)
        if cached is not None:
            return ChatAnswerResponse.model_validate(cached)
    try:
        message = await _chat_service(request, owner_id).answer(paper_id, session_id, payload.question, owner_id)
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
    owner_id = require_current_user(request).id
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Workspace name is required.")
    try:
        return request.app.state.database.create_workspace(name, owner_id)
    except PaperPersistenceError as exc:
        raise HTTPException(status_code=500, detail="The workspace could not be saved.") from exc


@router.get("/api/workspaces", response_model=list[Workspace])
async def list_workspaces(request: Request) -> list[Workspace]:
    return request.app.state.database.list_workspaces(require_current_user(request).id)


@router.get("/api/workspaces/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(workspace_id: str, request: Request) -> WorkspaceResponse:
    owner_id = require_current_user(request).id
    workspace = request.app.state.database.get_workspace(workspace_id, owner_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return WorkspaceResponse(workspace=workspace, papers=request.app.state.database.get_workspace_papers(workspace_id, owner_id))


@router.patch("/api/workspaces/{workspace_id}", response_model=Workspace)
async def update_workspace(workspace_id: str, payload: WorkspaceCreate, request: Request) -> Workspace:
    owner_id = require_current_user(request).id
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Workspace name is required.")
    workspace = request.app.state.database.update_workspace(workspace_id, name, owner_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return workspace


@router.delete("/api/workspaces/{workspace_id}")
async def delete_workspace(workspace_id: str, request: Request) -> dict[str, bool]:
    owner_id = require_current_user(request).id
    if not request.app.state.database.delete_workspace(workspace_id, owner_id):
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return {"ok": True}


@router.post("/api/workspaces/{workspace_id}/papers/{paper_id}", response_model=WorkspaceResponse)
async def add_workspace_paper(workspace_id: str, paper_id: str, request: Request) -> WorkspaceResponse:
    owner_id = require_current_user(request).id
    try:
        request.app.state.database.add_workspace_paper(workspace_id, paper_id, owner_id)
        workspace = request.app.state.database.get_workspace(workspace_id, owner_id)
        if workspace is None:
            raise HTTPException(status_code=404, detail="Workspace not found.")
        return WorkspaceResponse(workspace=workspace, papers=request.app.state.database.get_workspace_papers(workspace_id, owner_id))
    except PaperPersistenceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/api/workspaces/{workspace_id}/papers/{paper_id}", response_model=WorkspaceResponse)
async def remove_workspace_paper(workspace_id: str, paper_id: str, request: Request) -> WorkspaceResponse:
    owner_id = require_current_user(request).id
    if not request.app.state.database.remove_workspace_paper(workspace_id, paper_id, owner_id):
        raise HTTPException(status_code=404, detail="Workspace paper not found.")
    workspace = request.app.state.database.get_workspace(workspace_id, owner_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return WorkspaceResponse(workspace=workspace, papers=request.app.state.database.get_workspace_papers(workspace_id, owner_id))


@router.post("/api/workspaces/{workspace_id}/compare", response_model=PaperComparisonIR)
async def compare_workspace(payload: ComparisonRequest, workspace_id: str, request: Request) -> PaperComparisonIR:
    owner_id = require_current_user(request).id
    if request.app.state.database.get_workspace(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    allowed = {item.paper_id for item in request.app.state.database.get_workspace_papers(workspace_id, owner_id)}
    if any(paper_id not in allowed for paper_id in payload.paper_ids):
        raise HTTPException(status_code=422, detail="Comparison papers must belong to the workspace.")
    try:
        return PaperComparisonService(request.app.state.database).compare(payload.paper_ids, owner_id)
    except ComparisonError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/papers/{paper_id}/citation-graph", response_model=CitationGraph)
async def citation_graph(paper_id: str, request: Request) -> CitationGraph:
    owner_id = require_current_user(request).id
    try:
        return build_citation_graph(request.app.state.database, paper_id, owner_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/research/runs", response_model=ResearchRunResponse, status_code=status.HTTP_201_CREATED)
async def create_research_run(payload: ResearchRunCreate, request: Request) -> ResearchRunResponse:
    if _capability_disabled(request, "research_agent_enabled"):
        raise HTTPException(status_code=503, detail="The Research Agent is not enabled for this deployment.")
    owner_id = require_current_user(request).id
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Research question is required.")
    if payload.workspace_id and request.app.state.database.get_workspace(payload.workspace_id, owner_id) is None:
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
        request.app.state.database.create_research_run(run, owner_id)
        request.app.state.database.add_research_event(ResearchRunEvent(id=f"event_{uuid4().hex}", research_run_id=run.id, event_type="RUN_CREATED", message="Research run created.", metadata={"depth": payload.depth.value}), owner_id)
    except PaperPersistenceError as exc:
        raise HTTPException(status_code=500, detail="The research run could not be saved.") from exc
    return _research_response(request, run.id, owner_id)


@router.get("/api/research/runs/{run_id}", response_model=ResearchRunResponse)
async def get_research_run(run_id: str, request: Request) -> ResearchRunResponse:
    return _research_response(request, run_id, require_current_user(request).id)


@router.post("/api/research/runs/{run_id}/execute", response_model=ResearchRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def execute_research_run(run_id: str, request: Request) -> ResearchRunResponse:
    owner_id = require_current_user(request).id
    queued = request.app.state.database.queue_research_run(run_id, owner_id)
    if queued is None:
        raise HTTPException(status_code=404, detail="Research run not found.")
    return _research_response(request, run_id, owner_id)


@router.post("/api/research/runs/{run_id}/cancel", response_model=ResearchRunResponse)
async def cancel_research_run(run_id: str, request: Request) -> ResearchRunResponse:
    owner_id = require_current_user(request).id
    try:
        await request.app.state.research_agent.cancel(run_id, owner_id)
    except ResearchAgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _research_response(request, run_id, owner_id)


@router.get("/api/research/runs/{run_id}/report")
async def get_research_report(run_id: str, request: Request) -> object:
    owner_id = require_current_user(request).id
    if request.app.state.database.get_research_run(run_id, owner_id) is None:
        raise HTTPException(status_code=404, detail="Research run not found.")
    report = request.app.state.database.get_research_report(run_id, owner_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Research report not found.")
    return report


async def _interactive_paper(request: Request, paper_id: str, owner_id: str) -> InteractivePaper | None:
    try:
        return await _interactive_service(request, owner_id).get_or_assemble(paper_id, owner_id)
    except InteractivePaperError:
        return None


def _provider_context(request: Request, owner_id: str):
    """Return the selected owner's provider runtime, or the legacy local default.

    A saved provider replaces the process-level fallback.  If an owner has
    provider rows but none has passed its bounded connection test, AI routes
    fail closed rather than silently calling another user's or deployment's
    provider.
    """

    records = request.app.state.database.list_provider_configs(owner_id)
    if not records:
        return None
    record = next((item for item in records if item.enabled and item.last_test_status == "PASSED"), None)
    if record is None:
        raise HTTPException(status_code=503, detail="Test an enabled provider before starting AI analysis.")
    try:
        return runtime_provider(request.app.state.settings, record)
    except ProviderSecretError as exc:
        raise HTTPException(status_code=503, detail="The configured provider secret is unavailable.") from exc


def _extraction_service(request: Request, owner_id: str) -> ResearchExtractionService:
    context = _provider_context(request, owner_id)
    if context is None:
        return request.app.state.extraction_service
    provider, settings = context
    return ResearchExtractionService(request.app.state.database, provider, settings=settings)


def _interactive_service(request: Request, owner_id: str) -> InteractivePaperService:
    context = _provider_context(request, owner_id)
    if context is None:
        return request.app.state.interactive_paper_service
    provider, settings = context
    return InteractivePaperService(request.app.state.database, provider, settings=settings)


def _verification_service(request: Request, owner_id: str) -> PaperVerificationService:
    context = _provider_context(request, owner_id)
    if context is None:
        return request.app.state.verification_service
    provider, settings = context
    return PaperVerificationService(request.app.state.database, provider, settings=settings)


def _chat_service(request: Request, owner_id: str) -> PaperChatService:
    context = _provider_context(request, owner_id)
    if context is None:
        return request.app.state.chat_service
    provider, settings = context
    return PaperChatService(request.app.state.database, provider, settings=settings)


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


def _capability_disabled(request: Request, name: str) -> bool:
    """Enforce capability flags on staging/production while preserving local fixtures."""

    settings = request.app.state.settings
    return settings.environment in {"staging", "production"} and not bool(getattr(settings, name, False))


def _research_response(request: Request, run_id: str, owner_id: str) -> ResearchRunResponse:
    run = request.app.state.database.get_research_run(run_id, owner_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found.")
    report = request.app.state.database.get_research_report(run_id, owner_id)
    coverage = report.coverage if report else None
    return ResearchRunResponse(
        run=run,
        plan=request.app.state.database.get_research_plan(run_id, owner_id),
        queries=request.app.state.database.get_research_queries(run_id, owner_id),
        candidates=request.app.state.database.get_research_candidates(run_id, owner_id),
        events=request.app.state.database.get_research_events(run_id, owner_id),
        coverage=coverage,
        report=report,
        attempt=request.app.state.database.get_research_attempt(run_id, owner_id),
    )
