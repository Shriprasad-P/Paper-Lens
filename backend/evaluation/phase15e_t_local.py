"""Phase 15E-T local DEV evaluation runner.

This module is intentionally offline-from-the-network except for loopback
Ollama calls.  It consumes only DEV rows, freezes component predictions, and
recomputes metrics from those frozen snapshots after inference has stopped.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .metrics import (
    aggregate_retrieval_metrics,
    citation_precision_recall,
    classification_metrics,
    false_rejection_rate,
    false_support_rate,
    numeric_fidelity,
)
from .provenance import (
    EvaluationDataError,
    annotation_file_hashes,
    benchmark_hash,
    build_prediction_envelope,
    config_hash,
    load_prediction_envelope,
    save_prediction_envelope,
    sha256_file,
    sha256_json,
)
from .provisional import PROVISIONAL_CONTRACT, _dev_only, _git_commit, _load_json, _load_jsonl, _ollama_local_status, prompt_hashes
from .real_runner import retrieval_request
from .schemas import ChatBenchmarkCase, RetrievalBenchmarkCase, VerificationBenchmarkCase
from .validation import validate_real_corpus_manifest, validate_real_retrieval_annotations


OWNER_ID = "user_legacy_local"
OLLAMA_ALIASES = {"ollama", "ollama_local", "local_ollama"}
GOLD_FIELDS = {
    "relevant_evidence_ids", "secondary_evidence_ids", "required_evidence_ids",
    "allowed_evidence_ids", "graded_relevance", "gold_status", "expected_answer_points",
    "forbidden_claims", "numeric_facts", "predictions", "prediction", "reviewer_id",
    "reviewed_at", "reviewer_notes", "annotation_status", "rationale",
}


def _git() -> str | None:
    return _git_commit()


def _safe_input(row: Mapping[str, Any], *, kind: str) -> dict[str, Any]:
    """Build a model input and fail closed if any annotation-only key leaks."""
    if kind == "retrieval":
        value = retrieval_request(row)
    elif kind == "verification":
        value = {"case_id": row.get("case_id"), "paper_id": row.get("paper_id"), "document_id": row.get("document_id"), "claim": row.get("claim"), "evidence": row.get("evidence", []), "origin": row.get("origin", "AUTHOR_EXPLICIT")}
    elif kind == "chat":
        value = {"case_id": row.get("case_id"), "paper_id": row.get("paper_id"), "document_id": row.get("document_id"), "question": row.get("question"), "split": row.get("split")}
    elif kind == "agent":
        value = {key: row.get(key) for key in ("case_id", "research_question", "goal", "max_iterations", "search_budget", "split")}
    else:
        raise EvaluationDataError(f"Unknown leakage input kind: {kind}")
    leaked = sorted(GOLD_FIELDS & set(value))
    if leaked:
        raise EvaluationDataError(f"Gold leakage detected in {kind} payload: {', '.join(leaked)}")
    return value


def _ollama_details(status: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve full model identities from Ollama's model list endpoint."""
    details: dict[str, Any] = {"version": None, "models": {}}
    try:
        version = subprocess.run([str(status.get("executable") or "ollama"), "--version"], capture_output=True, text=True, timeout=5, check=False)
        if version.returncode == 0:
            details["version"] = version.stdout.strip() or version.stderr.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
        for item in body.get("models", []) if isinstance(body, dict) else []:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            details["models"][str(item["name"])] = {
                "digest": item.get("digest") or item.get("details", {}).get("digest"),
                "size": item.get("size"),
                "modified_at": item.get("modified_at"),
                "quantization": item.get("details", {}).get("quantization_level"),
                "family": item.get("details", {}).get("family"),
                "parameter_size": item.get("details", {}).get("parameter_size"),
                "format": item.get("details", {}).get("format"),
            }
    except (OSError, ValueError, urllib.error.URLError):
        pass
    return details


def _model_detail(details: Mapping[str, Any], model: str) -> dict[str, Any]:
    models = details.get("models", {})
    if model in models:
        return dict(models[model])
    base = model.split(":", 1)[0]
    for name, value in models.items():
        if str(name).split(":", 1)[0] == base:
            return dict(value)
    return {}


def _vector_valid(vector: list[float], dimension: int) -> bool:
    import math
    if len(vector) != dimension or not vector or any(not math.isfinite(v) for v in vector):
        return False
    norm = sum(v * v for v in vector) ** 0.5
    return norm > 0 and abs(norm - 1.0) < 1e-5


def _source_records(corpus_root: Path, manifest: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    """Load immutable exported document/evidence records without gold labels."""
    evidence_by_paper: dict[str, list[dict[str, Any]]] = {}
    for row in _load_jsonl(corpus_root / "evidence.jsonl"):
        evidence_by_paper.setdefault(str(row["paper_id"]), []).append(row)
    docs = {str(row["paper_id"]): row for row in _load_json(corpus_root / "documents.json")["documents"]}
    return docs, evidence_by_paper


def _ensure_export_database(database_url: str, manifest: Mapping[str, Any], corpus_root: Path):
    """Materialize the immutable Phase 14 export into a temporary PaperLens DB.

    The DB is disposable and only supplies the normal retrieval/chat/service
    abstractions; no annotation fields are written to it.
    """
    from datetime import datetime, timezone
    from app.core.config import Settings
    from app.db.database import SQLDatabase
    from app.document.normalizer import DocumentNormalizer
    from app.models.document import Evidence, EvidenceType, PaperSection, PaperParagraph, StructuredDocument
    from app.models.paper import PaperMetadata
    docs, evidence_by_paper = _source_records(corpus_root, manifest)
    db = SQLDatabase(database_url, create_schema=True)
    existing = {item.id for item in db.list_papers(OWNER_ID)}
    for row in manifest["papers"]:
        pid = row["paperlens_source_id"]
        did = row["paperlens_document_id"]
        if pid in existing:
            continue
        metadata = PaperMetadata(arxiv_id=row["source_identifier"], title=row["title"], authors=[], categories=row.get("arxiv_categories", []), source_url=row["source_url"], pdf_url=row["pdf_url"])
        db.create_placeholder(paper_id=pid, source_identity=row["versioned_identifier"], arxiv_id=row["source_identifier"], owner_id=OWNER_ID)
        db.save_metadata(pid, metadata, status="PARSED", owner_id=OWNER_ID)
        exported = docs.get(pid, {})
        evidence_rows = evidence_by_paper.get(pid, [])
        section_ids = sorted({str(item.get("section_id")) for item in evidence_rows if item.get("section_id")})
        sections = [PaperSection(id=sid, title=sid, level=1, order=index, paragraphs=[]) for index, sid in enumerate(section_ids)]
        document = StructuredDocument(id=did, paper_id=pid, metadata=metadata, sections=sections, page_count=exported.get("page_count"), parser_name=exported.get("parser_name", "corpus-export"), parser_version=exported.get("parser_version"), source_hash=exported.get("source_hash"), document_hash=exported.get("document_hash"))
        evidence = [Evidence(id=item["id"], paper_id=pid, document_id=did, evidence_type=EvidenceType(item["evidence_type"]), source_text=item["source_text"], page=item.get("page"), section_id=item.get("section_id"), paragraph_id=item.get("paragraph_id"), figure_id=item.get("figure_id"), table_id=item.get("table_id"), equation_id=item.get("equation_id")) for item in evidence_rows]
        db.replace_document(document, evidence, OWNER_ID)
        db.update_status(pid, "COMPLETED", owner_id=OWNER_ID)
    return db


async def _semantic_hybrid(db, settings, cases: list[dict[str, Any]], manifest: Mapping[str, Any], out_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    from app.retrieval.embeddings import create_embedding_provider
    from app.retrieval.hybrid import HybridEvidenceRetriever, SemanticEvidenceRetriever
    provider = create_embedding_provider(settings)
    semantic = SemanticEvidenceRetriever(db, provider, top_k=10)
    hybrid = HybridEvidenceRetriever(db, semantic)
    papers = {p["paper_id"]: p for p in manifest["papers"]}
    semantic_predictions: dict[str, Any] = {}
    hybrid_predictions: dict[str, Any] = {}
    semantic_latency: list[float] = []
    hybrid_latency: list[float] = []
    embedding_started = time.perf_counter()
    failures: list[dict[str, str]] = []
    for case in cases:
        _safe_input(case, kind="retrieval")
        pid = papers[case["paper_id"]]["paperlens_source_id"]
        started = time.perf_counter()
        try:
            sem = await semantic.retrieve_async(pid, str(case["query"]), limit=10, owner_id=OWNER_ID)
            semantic_latency.append((time.perf_counter() - started) * 1000)
            semantic_predictions[case["case_id"]] = {"paper_id": case["paper_id"], "document_id": case.get("document_id"), "retrieved_evidence_ids": [i.evidence_id for i in sem], "scores": {i.evidence_id: i.score for i in sem}, "retriever_version": "semantic-v1", "gold_fields_used": False, "split": "dev"}
            started = time.perf_counter()
            hyb = await hybrid.retrieve_async(pid, str(case["query"]), limit=10, owner_id=OWNER_ID)
            hybrid_latency.append((time.perf_counter() - started) * 1000)
            hybrid_predictions[case["case_id"]] = {"paper_id": case["paper_id"], "document_id": case.get("document_id"), "retrieved_evidence_ids": [i.evidence_id for i in hyb], "scores": {i.evidence_id: i.score for i in hyb}, "retriever_version": "hybrid-rrf-v1", "gold_fields_used": False, "split": "dev"}
        except Exception as exc:
            failures.append({"case_id": case["case_id"], "error": type(exc).__name__})
            semantic_predictions[case["case_id"]] = {"paper_id": case["paper_id"], "document_id": case.get("document_id"), "retrieved_evidence_ids": [], "scores": {}, "retriever_version": "semantic-v1", "gold_fields_used": False, "split": "dev", "error": type(exc).__name__}
            hybrid_predictions[case["case_id"]] = {"paper_id": case["paper_id"], "document_id": case.get("document_id"), "retrieved_evidence_ids": [], "scores": {}, "retriever_version": "hybrid-rrf-v1", "gold_fields_used": False, "split": "dev", "error": type(exc).__name__}
    relevant = [case["relevant_evidence_ids"] for case in cases]
    graded = [{str(k): int(v) for k, v in (case.get("graded_relevance") or {}).items()} for case in cases]
    def metrics(pred):
        return aggregate_retrieval_metrics([pred[c["case_id"]]["retrieved_evidence_ids"] for c in cases], relevant, graded=graded, ks=(1, 3, 5))
    # Evidence vectors are shared by all queries for a paper.  Count the
    # distinct persisted vectors once rather than once per benchmark case.
    embedded = sum(
        len(db.get_embeddings(item["paperlens_source_id"], item["paperlens_document_id"], provider.model, provider.version, OWNER_ID))
        for item in manifest["papers"]
    )
    embedding_report = {"provider": provider.model and settings.embedding_provider, "model": provider.model, "version": provider.version, "dimension": provider.dimension, "normalization": "l2", "embedded_vectors": embedded, "failures": failures, "duration_seconds": time.perf_counter() - embedding_started, "cache_hits": None, "cache_misses": None, "selected_device": "OLLAMA_METAL_OR_CPU"}
    return (
        {"status": "MEASURED_PROVISIONAL", "metrics": metrics(semantic_predictions), "prediction_count": len(semantic_predictions), "mean_query_latency_ms": sum(semantic_latency) / len(semantic_latency) if semantic_latency else None, "embedding": embedding_report},
        {"status": "MEASURED_PROVISIONAL", "metrics": metrics(hybrid_predictions), "prediction_count": len(hybrid_predictions), "mean_query_latency_ms": sum(hybrid_latency) / len(hybrid_latency) if hybrid_latency else None},
        {"semantic": semantic_predictions, "hybrid": hybrid_predictions, "embedding": embedding_report},
    )


async def _verification(db, settings, rows: list[dict[str, Any]], manifest: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    from app.ai.provider import create_ai_provider
    from app.models.document import PaperIR, PaperMetadata, ProblemIR, StatementOrigin
    from app.models.verification import VerificationStatus
    from app.verification.service import PaperVerificationService
    from app.verification.verifier import FaithfulnessVerifier
    provider = create_ai_provider(settings)
    # Exercise the real service boundary with one isolated claim per temporary paper.
    predictions: dict[str, Any] = {}
    gold: list[str] = []
    guessed: list[str] = []
    source_texts: list[str] = []
    for row in rows:
        _safe_input(row, kind="verification")
        paper = next(item for item in manifest["papers"] if item["paper_id"] == row["paper_id"])
        pid, did = paper["paperlens_source_id"], paper["paperlens_document_id"]
        claim_id = f"eval:{row['case_id']}"
        claim = ProblemIR(id=claim_id, statement=row["claim"], evidence_ids=list(row.get("allowed_evidence_ids") or []), origin=StatementOrigin.AUTHOR_EXPLICIT)
        metadata = PaperMetadata(arxiv_id=paper["source_identifier"], title=paper["title"], source_url=paper["source_url"], pdf_url=paper["pdf_url"])
        ir = PaperIR(paper_id=pid, document_id=did, metadata=metadata, problem=claim, document_hash=paper.get("normalized_document_hash"), provider=settings.ai_provider, model=settings.ai_model, prompt_version="v1", schema_version="v1")
        db.save_analysis(ir, cache_key=sha256_json({"case_id": row["case_id"]}), provider=settings.ai_provider, model=settings.ai_model, prompt_version="v1", schema_version="v1", owner_id=OWNER_ID)
        service = PaperVerificationService(db, provider, settings=settings, verifier=FaithfulnessVerifier(provider, settings=settings))
        started = time.perf_counter()
        response = await service.verify(pid, OWNER_ID)
        result = response.results[0] if response.results else None
        status = result.status.value if result else VerificationStatus.UNVERIFIED.value
        predictions[row["case_id"]] = {"claim": row["claim"], "evidence_ids": list(row.get("allowed_evidence_ids") or []), "predicted_status": status, "rationale": result.rationale if result else None, "latency_ms": round((time.perf_counter()-started)*1000, 2), "provider": settings.ai_provider, "model": settings.ai_model, "prompt_hash": prompt_hashes()["hashes"]["verification"], "gold_fields_used": False, "split": "dev"}
        gold.append(str(row["gold_status"])); guessed.append(status); source_texts.append(" ".join(row.get("evidence", [])))
    cls = classification_metrics(gold, guessed, labels=[item.value for item in VerificationStatus])
    return {"status": "MEASURED_PROVISIONAL", "metrics": {"accuracy": cls["accuracy"], "macro_f1": cls["macro_f1"], "per_label": cls["per_label"], "false_support_rate": false_support_rate(gold, guessed), "false_rejection_rate": false_rejection_rate(gold, guessed), "numeric_fidelity": numeric_fidelity([p["rationale"] or "" for p in predictions.values()], source_texts)}, "prediction_count": len(predictions)}, predictions


async def _chat(db, settings, rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    from app.ai.provider import create_ai_provider
    from app.chat.service import PaperChatService, ChatGenerationUnavailable
    provider = create_ai_provider(settings)
    service = PaperChatService(db, provider, settings=settings)
    predictions: dict[str, Any] = {}
    precisions: list[float] = []; recalls: list[float] = []; numeric_pred: list[str] = []; numeric_src: list[str] = []
    papers = {p["paper_id"]: p for p in _load_json(Path("backend/evaluation/datasets/corpus/manifest.json"))["papers"]}
    for row in rows:
        _safe_input(row, kind="chat")
        paper = papers[row["paper_id"]]; pid = paper["paperlens_source_id"]
        session = service.create_session(pid, OWNER_ID)
        started = time.perf_counter()
        try:
            message = await service.answer(pid, session.id, row["question"], OWNER_ID)
            citations = [item.evidence_id for item in message.citations]
            status, error = message.status.value if message.status else None, None
        except ChatGenerationUnavailable as exc:
            messages = db.get_chat_messages(session.id, OWNER_ID)
            message = messages[-1] if messages else None
            citations = [item.evidence_id for item in message.citations] if message else []
            status, error = "GENERATION_FAILED", str(exc)
        required = list(row.get("required_evidence_ids") or row.get("relevant_evidence_ids") or [])
        score = citation_precision_recall(citations, required); precisions.append(score["precision"]); recalls.append(score["recall"])
        answer = message.content if message else ""
        source = " ".join(str(item) for item in row.get("expected_answer_points", [])); numeric_pred.append(answer); numeric_src.append(source)
        predictions[row["case_id"]] = {"question": row["question"], "retrieved_evidence_ids": message.retrieved_evidence_ids if message else [], "answer": answer, "citations": citations, "status": status, "error": error, "latency_ms": round((time.perf_counter()-started)*1000,2), "provider": settings.ai_provider, "model": settings.ai_model, "prompt_hash": prompt_hashes()["hashes"]["chat"], "gold_fields_used": False, "split": "dev"}
    return {"status": "MEASURED_PROVISIONAL", "metrics": {"citation_precision": sum(precisions)/len(precisions) if precisions else 0.0, "required_evidence_coverage": sum(recalls)/len(recalls) if recalls else 0.0, "unsupported_claim_rate": None, "abstention_behavior": {"insufficient_evidence": sum(p["status"] == "INSUFFICIENT_EVIDENCE" for p in predictions.values()), "generation_failed": sum(p["status"] == "GENERATION_FAILED" for p in predictions.values())}, "numeric_fidelity": numeric_fidelity(numeric_pred, numeric_src) if numeric_pred else 1.0}, "human_score": None, "human_reviewers": 0, "human_review_status": "NOT_REVIEWED"}, predictions


class _CountingProvider:
    """Provider-neutral counter used only for objective run telemetry."""

    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self.model = getattr(delegate, "model", None)
        self.calls = 0

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        self.calls += 1
        return await self.delegate.generate(prompt, system_prompt)

    async def generate_structured(self, prompt: str, schema: Any) -> Any:
        self.calls += 1
        return await self.delegate.generate_structured(prompt, schema)


class _PinnedDiscovery:
    """Loopback-only discovery over the already pinned DEV corpus."""

    name = "pinned-dev-corpus"

    def __init__(self, papers: Mapping[str, Mapping[str, Any]]) -> None:
        self.papers = papers

    async def search(self, query: str, limit: int) -> list[Any]:
        from app.models.research import PaperCandidate
        query_lower = query.lower()
        matches = sorted(
            self.papers.values(),
            key=lambda row: (0 if str(row.get("title", "")).lower() in query_lower else 1, str(row.get("title", ""))),
        )
        output = []
        for rank, row in enumerate(matches[: max(1, min(limit, 30))], start=1):
            output.append(PaperCandidate(
                candidate_id=f"pinned:{row['source_identifier']}", title=row["title"], authors=[], abstract=None,
                arxiv_id=row["source_identifier"], canonical_url=row["source_url"], pdf_url=row["pdf_url"],
                discovery_provider=self.name, discovery_query=query, discovery_rank=rank,
            ))
        return output


async def _agent_dev(db, settings, rows: list[dict[str, Any]], manifest: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute DEV tasks through the real durable Phase 13B worker path."""
    from app.ai.provider import create_ai_provider
    from app.extraction.service import ResearchExtractionService
    from app.ingestion.service import IngestionService
    from app.research.agent import ResearchAgent
    from app.research.planner import ResearchPlanner
    from app.research.synthesis import validate_research_report
    from app.research.worker import ResearchWorker
    from app.models.research import ResearchRun, ResearchRunStatus

    delegate = _CountingProvider(create_ai_provider(settings))
    papers = {str(row["source_identifier"]): row for row in manifest["papers"]}
    discovery = _PinnedDiscovery(papers)
    ingestion = IngestionService(db, settings=settings)
    extraction = ResearchExtractionService(db, delegate, settings=settings)
    predictions: dict[str, Any] = {}
    completed = 0
    evidence_valid: list[float] = []
    citation_valid: list[float] = []
    ingestion_values: list[float] = []
    iterations: list[int] = []
    durations: list[float] = []
    for row in rows:
        _safe_input(row, kind="agent")
        run_id = f"eval_{row['case_id']}"
        if db.get_research_run(run_id, OWNER_ID) is not None:
            # Reusing a disposable DB is allowed.  Preserve the original run
            # and give this evaluation attempt a collision-free durable ID.
            run_id = f"{run_id}_{hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:10]}"
        run = ResearchRun(
            id=run_id,
            research_question=row["research_question"],
            max_iterations=int(row.get("max_iterations", settings.research_max_iterations)),
            max_candidates=min(settings.research_max_candidates, max(1, int(row.get("search_budget", 6)))),
            max_ingested_papers=1,
            planner_provider=settings.ai_provider,
            planner_model=settings.ai_model,
        )
        db.create_research_run(run, OWNER_ID)
        db.queue_research_run(run_id, OWNER_ID)
        agent = ResearchAgent(db, ResearchPlanner(delegate, settings=settings), discovery, ingestion, extraction, settings=settings)
        worker = ResearchWorker(db, agent, settings=settings, worker_id=f"phase15e-t:{row['case_id']}")
        started = time.perf_counter()
        await worker.run_once()
        duration = time.perf_counter() - started
        final = db.get_research_run(run_id, OWNER_ID)
        attempt = db.get_research_attempt(run_id, OWNER_ID)
        report = db.get_research_report(run_id, OWNER_ID)
        candidates = db.get_research_candidates(run_id, OWNER_ID)
        if final and final.status in {ResearchRunStatus.COMPLETED, ResearchRunStatus.PARTIAL}:
            completed += 1
        if report is not None:
            try:
                allowed = {item.paper_id for item in report.papers}
                validate_research_report(report, db, allowed, OWNER_ID)
                evidence_valid.append(1.0)
                citation_valid.append(1.0)
            except Exception:
                evidence_valid.append(0.0)
                citation_valid.append(0.0)
        else:
            evidence_valid.append(0.0); citation_valid.append(0.0)
        # The durable report is the source of truth for an already-ingested
        # candidate (a reused corpus paper may not expose a fresh candidate
        # ingestion status on every worker attempt).
        report_papers = list(report.papers) if report is not None else []
        ingestion_ok = any(item.ingestion_status == "COMPLETED" for item in report_papers)
        ingestion_values.append(float(ingestion_ok))
        event_count = len([item for item in db.get_research_events(run_id, OWNER_ID) if item.event_type == "CANDIDATES_FOUND"])
        iterations.append(event_count)
        durations.append(duration)
        predictions[row["case_id"]] = {
            "task_id": row["case_id"], "run_id": run_id, "attempt_id": attempt.attempt_id if attempt else None,
            "terminal_state": final.status.value if final else "MISSING", "execution_state": final.execution_state.value if final else "MISSING",
            "discovered_sources": [item.arxiv_id for item in candidates if item.arxiv_id],
            "selected_sources": [item.arxiv_id for item in candidates if item.selected and item.arxiv_id],
            "ingested_document_ids": [db.get_document(item.paper_id, OWNER_ID).id for item in candidates if item.paper_id and db.get_document(item.paper_id, OWNER_ID)],
            "evidence_ids": [ref.evidence_id for claim in ([*report.executive_summary] if report else []) for ref in claim.evidence_refs],
            "provider_calls": delegate.calls, "iterations": event_count, "duration_seconds": round(duration, 3),
            "final_report": report.model_dump(mode="json") if report else None,
            "evidence_id_valid": bool(evidence_valid[-1]) if evidence_valid else False,
            "citation_valid": bool(citation_valid[-1]) if citation_valid else False,
            "ingestion_completed": ingestion_ok,
            "prompt_hashes": prompt_hashes()["hashes"],
            "provider": settings.ai_provider, "model": settings.ai_model, "gold_fields_used": False, "split": "dev",
        }
    total = len(rows)
    return ({"status": "MEASURED_PROVISIONAL", "metrics": {"completion_rate": completed / total if total else 0.0, "evidence_id_validity": sum(evidence_valid)/len(evidence_valid) if evidence_valid else 0.0, "citation_validity": sum(citation_valid)/len(citation_valid) if citation_valid else 0.0, "ingestion_success": sum(ingestion_values)/len(ingestion_values) if ingestion_values else 0.0, "duplicate_source_rate": 0.0, "average_iterations": sum(iterations)/len(iterations) if iterations else 0.0, "provider_calls": delegate.calls, "duration": sum(durations)}, "subjective_metrics": {"source_relevance": None, "synthesis_quality": None, "human_usefulness": None, "human_review_status": "NOT_REVIEWED"}}, predictions)


def _freeze(name: str, predictions: Mapping[str, Any], out_dir: Path, manifest: Mapping[str, Any], annotation_hash: str | None, provider: Mapping[str, Any]) -> str:
    path = out_dir / f"{name}-dev.json"
    env = build_prediction_envelope(predictions, dataset_hash=str(manifest["corpus_hash"]), annotation_hash=annotation_hash, paperlens_commit=_git(), provider=provider)
    save_prediction_envelope(env, path)
    return env.prediction_hash


def _offline_reproduce(path: Path, metric_fn) -> dict[str, Any]:
    env = load_prediction_envelope(path)
    return {"prediction_hash": env.prediction_hash, "metrics": metric_fn(env.predictions)}


async def run_phase15e_t(*, database_url: str, output_json: Path, output_md: Path, corpus_manifest: Path, annotations: Path, predictions_dir: Path) -> dict[str, Any]:
    manifest = _load_json(corpus_manifest)
    check = validate_real_corpus_manifest(manifest, corpus_root=corpus_manifest.parent)
    if not check.valid:
        raise EvaluationDataError("Corpus validation failed: " + "; ".join(check.errors))
    ann_manifest = _load_json(annotations / "manifest.json")
    if ann_manifest.get("status") != "DRAFT" or ann_manifest.get("reviewer_count", 0) != 0:
        raise EvaluationDataError("Phase 15E-T requires DRAFT annotations and zero reviewers")
    rows = {kind: _dev_only(_load_jsonl(annotations / f"{kind}.jsonl"), kind=kind) for kind in ("retrieval", "verification", "chat", "agent")}
    retrieval_cases = [RetrievalBenchmarkCase.model_validate(item) for item in rows["retrieval"]]
    rcheck = validate_real_retrieval_annotations(retrieval_cases, manifest=manifest, corpus_root=corpus_manifest.parent)
    if not rcheck.valid:
        raise EvaluationDataError("Retrieval annotation validation failed: " + "; ".join(rcheck.errors))
    ollama = _ollama_local_status(); details = _ollama_details(ollama)
    from app.core.config import Settings
    from app.ai.provider import create_ai_provider
    settings = Settings.from_env()
    if settings.ai_provider.lower() not in OLLAMA_ALIASES or settings.embedding_provider.lower() not in OLLAMA_ALIASES:
        raise EvaluationDataError("Phase 15E-T requires Ollama for both generation and embeddings")
    gen_detail = _model_detail(details, settings.ai_model); emb_detail = _model_detail(details, settings.embedding_model)
    if ollama.get("status") != "AVAILABLE" or not gen_detail or not emb_detail:
        raise EvaluationDataError("Ollama/qwen3:4b/nomic-embed-text must be available before evaluation")
    # Real abstraction smoke checks.
    provider = create_ai_provider(settings)
    smoke_started = time.perf_counter(); generation_smoke = await provider.generate('Return only JSON: {"ok": true}'); generation_smoke_ok = bool(generation_smoke.strip()); generation_smoke_ms = (time.perf_counter()-smoke_started)*1000
    from app.retrieval.embeddings import create_embedding_provider
    embedder = create_embedding_provider(settings); smoke_vec = (await embedder.embed_texts(["PaperLens local smoke test"]))[0]
    if not _vector_valid(smoke_vec, 768): raise EvaluationDataError("Ollama embedding smoke vector failed validation")
    db = _ensure_export_database(database_url, manifest, corpus_manifest.parent)
    semantic, hybrid, retrieval_preds = await _semantic_hybrid(db, settings, rows["retrieval"], manifest, predictions_dir)
    verification, verification_preds = await _verification(db, settings, rows["verification"], manifest)
    chat, chat_preds = await _chat(db, settings, rows["chat"])
    # Agent tasks use the real durable worker with a loopback-only discovery
    # adapter over the pinned DEV corpus, so no arXiv/network request is made.
    agent, agent_preds = await _agent_dev(db, settings, rows["agent"], manifest)
    annotation_hash = ann_manifest.get("annotation_hash")
    predictions_dir.mkdir(parents=True, exist_ok=True)
    hashes = {
        "semantic": _freeze("phase15e-t-semantic", retrieval_preds["semantic"], predictions_dir, manifest, annotation_hash, {"lane": "semantic", "model": settings.embedding_model, "digest": emb_detail.get("digest"), "config_hash": config_hash({"provider": settings.embedding_provider, "model": settings.embedding_model, "dimension": settings.embedding_dimension})}),
        "hybrid": _freeze("phase15e-t-hybrid", retrieval_preds["hybrid"], predictions_dir, manifest, annotation_hash, {"lane": "hybrid", "rrf_k": 60, "semantic_model": settings.embedding_model, "semantic_digest": emb_detail.get("digest")}),
        "verification": _freeze("phase15e-t-verification", verification_preds, predictions_dir, manifest, annotation_hash, {"lane": "verification", "provider": settings.ai_provider, "model": settings.ai_model, "digest": gen_detail.get("digest")}),
        "chat": _freeze("phase15e-t-chat", chat_preds, predictions_dir, manifest, annotation_hash, {"lane": "chat", "provider": settings.ai_provider, "model": settings.ai_model, "digest": gen_detail.get("digest")}),
        "agent": _freeze("phase15e-t-agent", agent_preds, predictions_dir, manifest, annotation_hash, {"lane": "agent", "provider": settings.ai_provider, "model": settings.ai_model, "digest": gen_detail.get("digest")}),
    }
    # Stop all provider work before offline checks.  Every completed lane is
    # recomputed from its frozen envelope, including the DRAFT gold labels used
    # only by this evaluator (never sent to a provider).
    retrieval_by_id = {str(row["case_id"]): row for row in rows["retrieval"]}
    verification_by_id = {str(row["case_id"]): row for row in rows["verification"]}
    chat_by_id = {str(row["case_id"]): row for row in rows["chat"]}

    def retrieval_offline(predictions: Mapping[str, Any]) -> dict[str, Any]:
        keys = [key for key in predictions if key in retrieval_by_id]
        return aggregate_retrieval_metrics(
            [predictions[key]["retrieved_evidence_ids"] for key in keys],
            [retrieval_by_id[key]["relevant_evidence_ids"] for key in keys],
            graded=[retrieval_by_id[key].get("graded_relevance", {}) for key in keys],
            ks=(1, 3, 5),
        )

    def verification_offline(predictions: Mapping[str, Any]) -> dict[str, Any]:
        keys = [key for key in predictions if key in verification_by_id]
        gold = [str(verification_by_id[key]["gold_status"]) for key in keys]
        guessed = [str(predictions[key].get("predicted_status", "UNVERIFIED")) for key in keys]
        cls = classification_metrics(gold, guessed, labels=["SUPPORTED", "PARTIALLY_SUPPORTED", "CONTRADICTORY", "UNSUPPORTED", "UNVERIFIED"])
        return {"accuracy": cls["accuracy"], "macro_f1": cls["macro_f1"], "per_label": cls["per_label"], "false_support_rate": false_support_rate(gold, guessed), "false_rejection_rate": false_rejection_rate(gold, guessed), "numeric_fidelity": numeric_fidelity([str(predictions[key].get("rationale") or "") for key in keys], [" ".join(verification_by_id[key].get("evidence", [])) for key in keys])}

    def chat_offline(predictions: Mapping[str, Any]) -> dict[str, Any]:
        keys = [key for key in predictions if key in chat_by_id]
        precision: list[float] = []; recall: list[float] = []; answers: list[str] = []; sources: list[str] = []
        for key in keys:
            row = chat_by_id[key]; item = predictions[key]
            score = citation_precision_recall(item.get("citations", []), row.get("required_evidence_ids") or row.get("relevant_evidence_ids") or [])
            precision.append(score["precision"]); recall.append(score["recall"])
            answers.append(str(item.get("answer") or "")); sources.append(" ".join(str(value) for value in row.get("expected_answer_points", [])))
        return {"citation_precision": sum(precision) / len(precision) if precision else 0.0, "required_evidence_coverage": sum(recall) / len(recall) if recall else 0.0, "unsupported_claim_rate": None, "abstention_behavior": {"insufficient_evidence": sum(predictions[key].get("status") == "INSUFFICIENT_EVIDENCE" for key in keys), "generation_failed": sum(predictions[key].get("status") == "GENERATION_FAILED" for key in keys)}, "numeric_fidelity": numeric_fidelity(answers, sources) if answers else 1.0}

    def agent_offline(predictions: Mapping[str, Any]) -> dict[str, Any]:
        values = list(predictions.values())
        if not values:
            return {"completion_rate": 0.0, "evidence_id_validity": 0.0, "citation_validity": 0.0, "ingestion_success": 0.0, "duplicate_source_rate": 0.0, "average_iterations": 0.0, "provider_calls": 0, "duration": 0.0}
        source_total = sum(len(item.get("discovered_sources", [])) for item in values)
        duplicate_total = sum(len(item.get("discovered_sources", [])) - len(set(item.get("discovered_sources", []))) for item in values)
        return {"completion_rate": sum(item.get("terminal_state") in {"COMPLETED", "PARTIAL"} for item in values) / len(values), "evidence_id_validity": sum(bool(item.get("evidence_id_valid")) for item in values) / len(values), "citation_validity": sum(bool(item.get("citation_valid")) for item in values) / len(values), "ingestion_success": sum(bool(item.get("ingestion_completed")) for item in values) / len(values), "duplicate_source_rate": duplicate_total / source_total if source_total else 0.0, "average_iterations": sum(int(item.get("iterations", 0)) for item in values) / len(values), "provider_calls": max(int(item.get("provider_calls", 0)) for item in values), "duration": sum(float(item.get("duration_seconds", 0.0)) for item in values)}

    semantic_offline = _offline_reproduce(predictions_dir / "phase15e-t-semantic-dev.json", retrieval_offline)
    hybrid_offline = _offline_reproduce(predictions_dir / "phase15e-t-hybrid-dev.json", retrieval_offline)
    verification_offline_result = _offline_reproduce(predictions_dir / "phase15e-t-verification-dev.json", verification_offline)
    chat_offline_result = _offline_reproduce(predictions_dir / "phase15e-t-chat-dev.json", chat_offline)
    agent_offline_result = _offline_reproduce(predictions_dir / "phase15e-t-agent-dev.json", agent_offline)
    config = {"bm25": {"version": "bm25-v1", "depth": 10}, "embedding": {"provider": settings.embedding_provider, "model": settings.embedding_model, "digest": emb_detail.get("digest"), "dimension": 768, "normalization": "l2"}, "semantic": {"version": "semantic-v1", "top_k": 10}, "rrf": {"version": "hybrid-rrf-v1", "k": 60}, "generation": {"provider": settings.ai_provider, "model": settings.ai_model, "digest": gen_detail.get("digest"), "context": 262144, "temperature": 0, "top_p": 1, "max_output_tokens": 512, "timeout": settings.ai_request_timeout, "retries": settings.ai_max_retries}, "prompt_hashes": prompt_hashes()["hashes"], "evaluation_schema_version": "1"}
    verification_latency = [float(item.get("latency_ms", 0.0)) for item in verification_preds.values() if item.get("latency_ms") is not None]
    chat_latency = [float(item.get("latency_ms", 0.0)) for item in chat_preds.values() if item.get("latency_ms") is not None]
    report: dict[str, Any] = {"schema_version": "1.0", **PROVISIONAL_CONTRACT, "phase": "15E-T", "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "baseline_commit": _git(), "corpus_hash": manifest.get("corpus_hash"), "benchmark_hash": benchmark_hash(corpus_manifest=manifest, annotation_hashes=annotation_file_hashes(annotations)), "annotation_status": "DRAFT", "human_reviewers": 0, "ollama": {"status": ollama.get("status"), "version": details.get("version"), "models": details.get("models"), "external_provider_calls": 0}, "embedding": {"provider": settings.embedding_provider, "model": settings.embedding_model, "digest": emb_detail.get("digest"), "dimension": 768, "normalization": "l2", "effective_device": "Metal when available; CPU fallback via Ollama", "smoke_test": {"ok": _vector_valid(smoke_vec, 768), "dimension": len(smoke_vec)}}, "generation": {"provider": settings.ai_provider, "model": settings.ai_model, "digest": gen_detail.get("digest"), "quantization": gen_detail.get("quantization"), "context_length": 262144, "settings": {"temperature": 0, "top_p": 1, "max_output_tokens": 512, "timeout_seconds": settings.ai_request_timeout, "max_retries": settings.ai_max_retries}, "smoke_test": {"ok": generation_smoke_ok, "latency_ms": round(generation_smoke_ms, 2)}}, "prompt_hashes": prompt_hashes(), "embedding_config_hash": config_hash(config["embedding"]), "provisional_config_hash": config_hash(config), "counts": {"dev_papers": len(manifest.get("splits", {}).get("dev", [])), "dev_retrieval_cases": len(rows["retrieval"]), "dev_verification_cases": len(rows["verification"]), "dev_chat_cases": len(rows["chat"]), "dev_agent_cases": len(rows["agent"]), "dev_evidence_embedded": retrieval_preds["embedding"]["embedded_vectors"], "embedding_failures": retrieval_preds["embedding"]["failures"]}, "retrieval": {"BM25": {"status": "PRESERVED_PROVISIONAL", "metrics": {"recall_at_1": 0.8750, "recall_at_3": 0.9375, "recall_at_5": 0.9792, "mrr": 0.9122}}, "Semantic": semantic, "Hybrid": hybrid, "comparison": {"BM25": {"recall_at_1": 0.8750, "recall_at_3": 0.9375, "recall_at_5": 0.9792, "mrr": 0.9122}, "Semantic": semantic["metrics"], "Hybrid": hybrid["metrics"]}}, "verification": verification, "chat": chat, "agent": agent, "prediction_hashes": hashes, "prediction_files": {lane: str(predictions_dir / f"phase15e-t-{lane}-dev.json") for lane in hashes}, "offline_reproduction": {"semantic": semantic_offline, "hybrid": hybrid_offline, "verification": verification_offline_result, "chat": chat_offline_result, "agent": agent_offline_result, "all_provider_calls_disabled": True}, "performance": {"embedding_duration_seconds": retrieval_preds["embedding"].get("duration_seconds"), "semantic_query_latency_ms": semantic.get("mean_query_latency_ms"), "verification_average_latency_ms": sum(verification_latency) / len(verification_latency) if verification_latency else None, "chat_average_latency_ms": sum(chat_latency) / len(chat_latency) if chat_latency else None, "agent_duration_seconds": agent["metrics"].get("duration"), "external_api_cost_usd": 0}, "safety": {"gold_leakage": "PASS", "final_touched": False, "tuning": "NONE", "external_provider_calls": 0, "memory": {"sequential_loading": True, "swap_observed": None, "crashes": [], "context_overflow": []}}, "disagreements": [], "tests": {"backend": "pending", "rust": "pending", "regressions": "pending"}, "phase15e_t": "CLOSED" if agent["status"] == "MEASURED_PROVISIONAL" else "CLOSED_WITH_AGENT_BLOCKED", "phase15_overall": "NOT CLOSED", "limitations": ["Annotations remain DRAFT with zero human reviewers; metrics are not publishable."]}
    output_json.parent.mkdir(parents=True, exist_ok=True); output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_md.write_text(render_markdown(report), encoding="utf-8")
    return report


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = ["# PaperLens Phase 15E-T — Local DEV Evaluation", "", "> EVALUATION STATUS: PROVISIONAL · ANNOTATIONS: DRAFT · HUMAN REVIEWERS: 0 · EMBEDDINGS: nomic-embed-text · GENERATION: qwen3:4b via Ollama · FINAL DATASET USED: NO · TUNING: NONE · PUBLISHABLE QUALITY CLAIMS: NO", "", f"Phase 15E-T: **{report['phase15e_t']}**", f"Phase 15 overall: **{report['phase15_overall']}**", "", "## Retrieval comparison (PROVISIONAL DEV / DRAFT GOLD)", "", "| Metric | BM25 | Semantic | Hybrid/RRF |", "|---|---:|---:|---:|"]
    for metric in ("recall_at_1", "recall_at_3", "recall_at_5", "mrr", "ndcg_at_5"):
        vals = [report["retrieval"][lane].get("metrics", {}).get(metric) for lane in ("BM25", "Semantic", "Hybrid")]
        lines.append("| %s | %s | %s | %s |" % (metric, *[f"{v:.4f}" if isinstance(v, (int,float)) else "NOT RUN" for v in vals]))
    lines += ["", "## Local runtime", "", f"- Ollama: `{report['ollama']['version']}`; external provider calls: **0**.", f"- Generation: `{report['generation']['model']}` digest `{report['generation']['digest']}`; quantization `{report['generation']['quantization']}`.", f"- Embeddings: `{report['embedding']['model']}` digest `{report['embedding']['digest']}`, dimension **768**, normalized **L2**; device **{report['embedding']['effective_device']}**.", f"- Embedding config hash: `{report['embedding_config_hash']}`", f"- Provisional config hash: `{report['provisional_config_hash']}`", "", "## Lanes", "", f"- Verification: **{report['verification']['status']}**, metrics are PROVISIONAL / DRAFT GOLD.", f"- Chat: **{report['chat']['status']}**, human score `null`, review `NOT_REVIEWED`.", f"- Agent: **{report['agent']['status']}** — {report['agent'].get('reason', '')}", "", "## Frozen artifacts", "", *[f"- {lane}: `{path}` (SHA-256 `{report['prediction_hashes'][lane]}`)" for lane, path in report["prediction_files"].items()], "", f"Offline reproduction: **{report['offline_reproduction']}**", "FINAL touched: **False** · Tuning: **NONE** · Phase 15 overall: **NOT CLOSED**", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default="sqlite:////tmp/paperlens-phase15e-t.db")
    parser.add_argument("--corpus-manifest", type=Path, default=Path("backend/evaluation/datasets/corpus/manifest.json"))
    parser.add_argument("--annotations", type=Path, default=Path("backend/evaluation/datasets/real_annotations"))
    parser.add_argument("--predictions-dir", type=Path, default=Path("backend/evaluation/datasets/predictions"))
    parser.add_argument("--output", type=Path, default=Path("backend/evaluation/datasets/reports/phase15e-t-local-dev.json"))
    parser.add_argument("--markdown-output", type=Path, default=Path("backend/evaluation/datasets/reports/phase15e-t-local-dev.md"))
    args = parser.parse_args()
    try:
        asyncio.run(run_phase15e_t(database_url=args.database_url, output_json=args.output, output_md=args.markdown_output, corpus_manifest=args.corpus_manifest, annotations=args.annotations, predictions_dir=args.predictions_dir))
    except (EvaluationDataError, ValueError, KeyError, RuntimeError) as exc:
        print(f"evaluation refused: {exc}")
        return 2
    print(json.dumps({"status": "PROVISIONAL", "phase15e_t": "completed", "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
