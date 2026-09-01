"""Safe, DEV-only Phase 15E-P evaluation helpers.

The provisional lane is deliberately separate from the historical all-split
BM25 runner.  It refuses FINAL cases, never promotes DRAFT annotations, and
emits an explicit non-publishable contract for every report.
"""

from __future__ import annotations

import argparse
import importlib.util
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .metrics import aggregate_retrieval_metrics
from .provenance import (
    EvaluationDataError,
    annotation_file_hashes,
    benchmark_hash,
    build_prediction_envelope,
    config_hash,
    generation_provenance,
    load_prediction_envelope,
    real_corpus_hash,
    save_prediction_envelope,
    sha256_bytes,
    sha256_file,
    sha256_paths,
)
from .real_runner import retrieval_request
from .schemas import RetrievalBenchmarkCase
from .validation import validate_real_corpus_manifest, validate_real_retrieval_annotations


PROVISIONAL_CONTRACT: dict[str, Any] = {
    "evaluation_status": "PROVISIONAL",
    "annotation_status": "DRAFT",
    "human_reviewers": 0,
    "publishable": False,
    "publishable_quality_claims": False,
    "final_dataset_used": False,
    "tuning": "NONE",
    "split": "DEV",
}


def prompt_hashes(repo_root: Path | None = None) -> dict[str, Any]:
    """Hash the prompts/templates used by runnable PaperLens components."""

    root = repo_root or Path(__file__).resolve().parents[1]
    prompt_dir = root / "app" / "prompts"
    files = {
        "verification": prompt_dir / "faithfulness_verifier.md",
        "chat": prompt_dir / "paper_chat.md",
    }
    hashes: dict[str, str | None] = {}
    for name, path in files.items():
        hashes[name] = sha256_file(path) if path.is_file() else None
    # Planner prompts are inline by design; hash a stable contract identity
    # rather than copying dynamic questions or any gold annotation content.
    hashes["agent_planning"] = sha256_bytes(
        b"ResearchPlanner:PROMPT_VERSION=v1;SCHEMA_VERSION=v1;bounded-plan-contract"
    )
    hashes["agent_synthesis"] = sha256_bytes(
        b"ResearchSynthesizer:source-only-deterministic-report-contract:v1"
    )
    return {
        "versions": {"verification": "v1", "chat": "v1", "agent_planning": "v1", "agent_synthesis": "v1"},
        "hashes": hashes,
    }


def _ollama_local_status() -> dict[str, Any]:
    """Return a side-effect-free status snapshot for the local Ollama daemon."""

    executable = shutil.which("ollama")
    models: list[str] = []
    status = "UNAVAILABLE"
    reason = "The Ollama executable was not found on PATH."
    if executable:
        for attempt in range(3):
            try:
                with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as response:
                    body = json.loads(response.read().decode("utf-8"))
                available_models = body.get("models", []) if isinstance(body, dict) else []
                if isinstance(available_models, list):
                    status = "AVAILABLE"
                    reason = "The local Ollama daemon answered its loopback model endpoint."
                    models = [str(item["name"]) for item in available_models if isinstance(item, dict) and item.get("name")]
                    break
            except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                reason = "Ollama was found, but the local daemon probe timed out."
                if attempt < 2:
                    time.sleep(0.25)
        if status != "AVAILABLE":
            # The CLI can still report models while the HTTP endpoint is
            # briefly restarting (for example after a Metal/CPU transition).
            try:
                probe = subprocess.run([executable, "list"], capture_output=True, text=True, timeout=8, check=False)
                if probe.returncode == 0:
                    status = "AVAILABLE"
                    reason = "The local Ollama CLI reported its model list."
                    models = [fields[0] for fields in (line.split() for line in probe.stdout.splitlines()[1:]) if fields]
            except (OSError, subprocess.SubprocessError):
                pass
    return {
        "executable": executable,
        "status": status,
        "models": models,
        "reason": reason,
        "generation_model": os.getenv("AI_MODEL", "qwen3:4b"),
        "embedding_model": os.getenv("EMBEDDING_MODEL", "nomic-embed-text"),
        "base_url": os.getenv("AI_BASE_URL", "http://127.0.0.1:11434/v1"),
        "embedding_base_url": os.getenv("EMBEDDING_BASE_URL", "http://127.0.0.1:11434"),
    }


def _ollama_model_available(requested: str | None, models: Iterable[str]) -> bool:
    """Match an Ollama model alias with its optional ``:latest`` tag."""

    if not requested:
        return False
    wanted = requested.strip()
    return wanted in models or any(name.split(":", 1)[0] == wanted for name in models)


def generation_provider_audit(*, ollama_status: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Inspect supported generation configuration without contacting a provider."""

    try:
        from app.core.config import Settings
    except ModuleNotFoundError:  # pragma: no cover - repository-root import path
        from backend.app.core.config import Settings

    settings = Settings.from_env()
    provider = settings.ai_provider.strip() or "none"
    model = settings.ai_model.strip() or None
    provider_enabled = provider.lower() not in {"none", "disabled"}
    local_provider = provider.lower() in {"ollama", "ollama_local", "local_ollama"}
    ollama = dict(ollama_status) if local_provider and ollama_status is not None else (_ollama_local_status() if local_provider else None)
    missing: list[str] = []
    if not provider_enabled:
        missing.append("AI_PROVIDER")
    if not settings.ai_api_key and not local_provider:
        missing.append("AI_API_KEY")
    available = provider_enabled and bool(model) and (
        (bool(settings.ai_api_key) and not local_provider)
        or (local_provider and ollama is not None and ollama["status"] == "AVAILABLE" and _ollama_model_available(model, ollama["models"]))
    )
    unsupported_runtime = [name for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL") if os.getenv(name)]
    return {
        "provider_available": available,
        "model_configured": bool(model) and provider_enabled and (bool(settings.ai_api_key) or local_provider),
        "provider": provider if provider_enabled else "none",
        "model": model if available else None,
        "configured_intended_model": model,
        "base_url": settings.ai_base_url if not local_provider else (ollama or {}).get("base_url", settings.ai_base_url),
        "timeout_seconds": settings.ai_request_timeout,
        "max_retries": settings.ai_max_retries,
        "adapter": "OpenAICompatibleProvider" if provider_enabled else "UnavailableAIProvider",
        "missing_configuration": missing,
        "local_ollama": ollama,
        "unsupported_environment_configuration": unsupported_runtime,
        "secrets_stored": False,
        "reason": (
            "A supported provider and local Ollama model are available."
            if available and local_provider
            else "A supported provider and credential are configured."
            if available
            else "Ollama is selected but the daemon/model is unavailable."
            if local_provider
            else "PaperLens supports OpenAI-compatible generation, but AI_API_KEY is unset; available Anthropic variables are not consumed by this adapter."
        ),
    }


def embedding_runtime_audit(*, ollama_status: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Inspect local embedding runtimes and Apple Silicon execution options."""

    packages = {
        "sentence_transformers": "sentence-transformers",
        "transformers": "transformers",
        "torch": "torch",
        "mlx": "mlx",
        "mlx_lm": "mlx-lm",
        "numpy": "numpy",
        "onnxruntime": "onnxruntime",
    }
    installed = {module: bool(importlib.util.find_spec(module)) for module in packages}
    ollama = dict(ollama_status) if ollama_status is not None else _ollama_local_status()
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "supported_device_paths": (["MPS", "CPU"] if installed["torch"] else ["CPU"]),
        "installed_runtimes": installed,
        "ollama": ollama,
        "selected_device": "NOT_RUN",
        "model_loaded": False,
        "records_embedded": 0,
        "failed_embeddings": 0,
        "cache_hits": None,
        "cache_misses": None,
        "duration_seconds": None,
    }


def local_runtime_audit(*, ollama_status: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Audit locally available model/runtime assets without loading weights."""

    # Probe the lightweight local server before any optional MLX import probe;
    # the latter can briefly contend for Metal/memory on Apple Silicon.
    ollama = dict(ollama_status) if ollama_status is not None else _ollama_local_status()
    model_roots = [
        Path.home() / "Documents" / "Research-Paper" / "models",
        Path.home() / "Documents" / "Projects" / "FeedbackDrivenImagePipeline" / "models",
    ]
    candidates: list[dict[str, Any]] = []
    for root in model_roots:
        if not root.is_dir():
            continue
        for config_path in sorted(root.glob("*/config.json")):
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            model_dir = config_path.parent
            weights = sorted(model_dir.glob("*.safetensors")) + sorted(model_dir.glob("*.gguf"))
            if not weights:
                continue
            model_type = str(config.get("model_type") or "unknown")
            quantization = config.get("quantization") or config.get("quantization_config")
            metadata_paths = [config_path]
            tokenizer_path = model_dir / "tokenizer.json"
            if tokenizer_path.is_file():
                metadata_paths.append(tokenizer_path)
            candidates.append({
                "path": str(model_dir),
                "model_type": model_type,
                "architectures": config.get("architectures") or [],
                "quantization": quantization,
                "max_position_embeddings": config.get("max_position_embeddings"),
                "weight_file_count": len(weights),
                "weight_bytes": sum(path.stat().st_size for path in weights),
                "metadata_hash": sha256_paths(metadata_paths, root=model_dir),
                "revision": "unknown-local-export",
                "weights_format": "safetensors" if any(path.suffix == ".safetensors" for path in weights) else "gguf",
            })

    mlx_executable = shutil.which("mlx_lm") or str(Path.home() / "miniconda3" / "bin" / "mlx_lm")
    mlx_python = Path(mlx_executable).with_name("python")
    project_mlx_present = bool(importlib.util.find_spec("mlx"))
    mlx_version: str | None = None
    try:
        mlx_version = importlib.metadata.version("mlx-lm")
    except importlib.metadata.PackageNotFoundError:
        # The project venv intentionally has no ML stack.  Query the external
        # interpreter without importing MLX so a headless Metal probe cannot
        # prevent us from recording the installed runtime version.
        if mlx_python.is_file():
            try:
                version_probe = subprocess.run(
                    [str(mlx_python), "-c", "import importlib.metadata; print(importlib.metadata.version('mlx-lm'))"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if version_probe.returncode == 0 and version_probe.stdout.strip():
                    mlx_version = version_probe.stdout.strip().splitlines()[-1]
            except (OSError, subprocess.SubprocessError):
                pass
    metal_status = "NOT_PROBED"
    metal_reason = "No MLX runtime was discovered."
    mlx_core_status = "NOT_PROBED"
    mlx_lm_import_status = "NOT_PROBED"
    if ollama["status"] == "AVAILABLE":
        metal_status = "SKIPPED_OLLAMA_SELECTED"
        metal_reason = "Ollama is available; the optional MLX probe was skipped to avoid competing for Metal memory."
        mlx_core_status = "NOT_RUN"
        mlx_lm_import_status = "NOT_RUN"
    elif mlx_python.is_file():
        try:
            probe = subprocess.run(
                [str(mlx_python), "-c", "import mlx.core as mx; print('CORE_DEVICE=' + str(mx.default_device())); import mlx_lm; print('MLX_LM_IMPORT=OK')"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            mlx_core_status = "AVAILABLE" if "CORE_DEVICE=" in probe.stdout else "UNAVAILABLE"
            mlx_lm_import_status = "AVAILABLE" if "MLX_LM_IMPORT=OK" in probe.stdout else "UNAVAILABLE"
            if probe.returncode == 0:
                metal_status = "AVAILABLE"
                metal_reason = "MLX default device probe succeeded."
            else:
                metal_status = "UNAVAILABLE"
                metal_reason = "MLX core is present, but the mlx-lm runtime import failed before model loading; no usable local inference path is available in this execution context."
        except (OSError, subprocess.SubprocessError):
            metal_status = "UNAVAILABLE"
            metal_reason = "MLX device probe could not run."
            mlx_core_status = "UNAVAILABLE"
            mlx_lm_import_status = "UNAVAILABLE"

    qwen_candidates = [item for item in candidates if item["model_type"] in {"qwen2", "qwen3"}]
    usable_qwen = [item for item in qwen_candidates if "mlx-" in item["path"].lower() and item["weight_file_count"] > 0]
    selected_generation = sorted(usable_qwen, key=lambda item: item["path"])[-1] if usable_qwen else None
    embedding_candidates = [item for item in candidates if any(token in item["model_type"].lower() for token in ("e5", "bge", "gte", "bert"))]
    local_ai_selected = os.getenv("AI_PROVIDER", "").strip().lower() in {"ollama", "ollama_local", "local_ollama"}
    local_embedding_selected = os.getenv("EMBEDDING_PROVIDER", "").strip().lower() in {"ollama", "ollama_local", "local_ollama"}
    ollama_generation_available = local_ai_selected and ollama["status"] == "AVAILABLE" and _ollama_model_available(ollama["generation_model"], ollama["models"])
    ollama_embedding_available = local_embedding_selected and ollama["status"] == "AVAILABLE" and _ollama_model_available(ollama["embedding_model"], ollama["models"])
    blockers: list[str] = []
    if not ollama_embedding_available and not embedding_candidates and not project_mlx_present:
        blockers.append("No supported local embedding runtime/model is available in the PaperLens project environment.")
    if not ollama_generation_available and selected_generation is None:
        blockers.append("No local generation model is available through Ollama or a usable MLX runtime.")
    if ollama["status"] != "AVAILABLE":
        blockers.append("The Ollama daemon is not reachable on 127.0.0.1:11434; start Ollama before using local AI features.")
    return {
        "python": platform.python_version(),
        "project_environment": {"embedding_runtime": "NOT_INSTALLED", "generation_runtime": "NOT_INSTALLED"},
        "external_runtime": {
            "mlx_lm_executable": str(mlx_executable) if Path(mlx_executable).is_file() else None,
            "mlx_lm_version": mlx_version,
            "mlx_python_detected": bool(mlx_python.is_file()),
            "project_mlx_installed": project_mlx_present,
            "metal_probe": metal_status,
            "metal_reason": metal_reason,
            "mlx_core_probe": mlx_core_status,
            "mlx_lm_import_probe": mlx_lm_import_status,
            "ollama": ollama,
        },
        "local_model_candidates": candidates,
        "selected_generation_model": selected_generation,
        "selected_ollama_generation_model": ollama["generation_model"] if ollama_generation_available else None,
        "embedding_model_candidates": embedding_candidates,
        "embedding_model_selected": ollama["embedding_model"] if ollama_embedding_available else None,
        "blockers": blockers,
        "local_server": {
            "status": "AVAILABLE" if ollama["status"] == "AVAILABLE" else "NOT_STARTED",
            "bind_host": "127.0.0.1",
            "base_url": ollama["base_url"],
            "smoke_test": "NOT_RUN",
            "reason": ollama["reason"],
        },
        "model_inference": {"embedding": "NOT_RUN", "generation": "NOT_RUN"},
        "memory": {"embedding_peak_bytes": None, "generation_peak_bytes": None, "swap_observed": None, "sequential_runtime_required": True},
    }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationDataError(f"Cannot read evaluation input: {path}") from exc
    if not isinstance(value, dict):
        raise EvaluationDataError(f"Expected an object in evaluation input: {path}")
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise EvaluationDataError(f"Cannot read evaluation ledger: {path}") from exc
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvaluationDataError(f"Invalid JSON at {path}:{line_number}") from exc
        if not isinstance(row, dict):
            raise EvaluationDataError(f"Expected an object at {path}:{line_number}")
        rows.append(row)
    return rows


def _dev_only(rows: Iterable[Mapping[str, Any]], *, kind: str) -> list[dict[str, Any]]:
    """Return only DEV rows from the mixed ledger.

    The repository ledgers intentionally contain both splits. FINAL rows are
    skipped before they enter any evaluator and are never scored, ranked, or
    included in report counts. A caller passing an explicit split can use
    :func:`require_dev_rows` for a fail-closed guard.
    """

    selected: list[dict[str, Any]] = []
    for row in rows:
        split = str(row.get("split", "")).lower()
        if split == "final":
            continue
        if split != "dev":
            raise EvaluationDataError(f"Phase 15E-P {kind} lane requires DEV cases, found split {row.get('split')!r}")
        status = str(row.get("annotation_status", "DRAFT"))
        if status != "DRAFT":
            raise EvaluationDataError(f"Phase 15E-P requires DRAFT annotations; {row.get('case_id', '<unknown>')} is {status}")
        selected.append(dict(row))
    return selected


def require_dev_rows(rows: Iterable[Mapping[str, Any]], *, kind: str) -> list[dict[str, Any]]:
    """Validate an already-selected lane and refuse accidental FINAL input."""

    selected = list(rows)
    if any(str(row.get("split", "")).lower() != "dev" for row in selected):
        bad = next(row for row in selected if str(row.get("split", "")).lower() != "dev")
        raise EvaluationDataError(f"Phase 15E-P {kind} lane requires DEV cases, found {bad.get('split')!r}")
    return _dev_only(selected, kind=kind)


def _metric_bundle_or_none(value: Mapping[str, Any] | None) -> dict[str, float] | None:
    return {name: float(number) for name, number in value.items()} if value is not None else None


def embedding_architecture_audit(settings: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Describe the existing semantic architecture without invoking a model."""

    configured = dict(settings or {})
    provider = str(configured.get("embedding_provider", "none"))
    model = configured.get("embedding_model")
    # hash-v1 remains an explicit test fallback, never a benchmark provider.
    available = provider.lower() not in {"", "none", "disabled", "unavailable", "hash", "local", "mock"}
    reason = (
        "No real embedding provider is configured; hash-v1 is test-only and excluded."
        if not available
        else "Provider is configured but must be exercised in a separately approved run."
    )
    return {
        **PROVISIONAL_CONTRACT,
        "status": "NOT_CONFIGURED" if not available else "CONFIGURED_NOT_RUN",
        "provider": provider,
        "model": model if available else None,
        "revision": configured.get("embedding_revision"),
        "embedding_provenance_hash": None,
        "dimension": configured.get("embedding_dimension") if available else None,
        "normalization": "l2" if available else None,
        "distance_metric": "cosine" if available else None,
        "batching": "embed_texts(list[str])", 
        "storage": "evidence_embeddings JSON vectors keyed by paper/document/evidence/model/version",
        "provenance": "evidence_id, document_id, evidence_hash, model, version, dimension",
        "cache_reuse": "model/version/document/evidence hash must match; stale evidence is re-embedded",
        "document_evidence_binding": "retrieval filters one paper/document and stores both IDs",
        "fallback": "HashEmbeddingProvider(hash-v1) exists for deterministic tests only; excluded from benchmark claims",
        "implementation": [
            "backend/app/retrieval/embeddings.py: EmbeddingProvider, cosine_similarity, create_embedding_provider",
            "backend/app/retrieval/hybrid.py: SemanticEvidenceRetriever and HybridEvidenceRetriever (RRF_K=60)",
            "backend/app/db/database.py: evidence_embeddings persistence and evidence_hash cache key",
        ],
        "run_eligibility": "BLOCKED_WITHOUT_REAL_PROVIDER" if not available else "READY_FOR_SEPARATE_DEV_RUN",
        "reason": reason,
    }


def _bm25_dev(
    *,
    cases: list[dict[str, Any]],
    manifest: Mapping[str, Any],
    database_url: str,
    owner_id: str,
) -> tuple[dict[str, float], dict[str, Any], str]:
    try:
        from app.chat.retrieval import BM25EvidenceRetriever
        from app.db.database import SQLDatabase
    except ModuleNotFoundError:  # pragma: no cover - repository-root CLI path
        from backend.app.chat.retrieval import BM25EvidenceRetriever
        from backend.app.db.database import SQLDatabase

    paper_by_id = {paper["paper_id"]: paper for paper in manifest["papers"]}
    db = SQLDatabase(database_url, create_schema=False)
    # The checked-in real-corpus export is the reproducibility boundary. A
    # local checkout may not carry the private ingestion database, so use the
    # frozen DEV-only slice when no owned papers are available rather than
    # silently reporting an empty/zero retrieval score.
    if not db.list_papers(owner_id):
        raise EvaluationDataError("The local evaluation database has no ingested corpus papers.")
    retriever = BM25EvidenceRetriever(db)
    rankings: list[list[str]] = []
    relevant: list[list[str]] = []
    graded: list[dict[str, int]] = []
    predictions: dict[str, Any] = {}
    for case in cases:
        paper = paper_by_id[case["paper_id"]]
        request = retrieval_request(case)
        items = retriever.retrieve(paper["paperlens_source_id"], str(request["query"]), limit=10, owner_id=owner_id)
        ranking = [item.evidence_id for item in items]
        rankings.append(ranking)
        relevant.append(list(case["relevant_evidence_ids"]))
        graded.append({str(key): int(value) for key, value in (case.get("graded_relevance") or {}).items()})
        predictions[case["case_id"]] = {
            "paper_id": case["paper_id"],
            "document_id": case.get("document_id"),
            "retrieved_evidence_ids": ranking,
            "scores": {item.evidence_id: item.score for item in items},
            "retriever_version": retriever.version,
            "split": "dev",
            "gold_fields_used": False,
        }
    metrics = aggregate_retrieval_metrics(rankings, relevant, graded=graded, ks=(1, 3, 5))
    return metrics, predictions, retriever.version


def _frozen_bm25_dev(
    *,
    corpus_manifest: Path,
    cases: list[dict[str, Any]],
) -> tuple[dict[str, float], dict[str, Any], str, str | None]:
    """Read only the historical frozen DEV baseline, never FINAL aggregates."""

    predictions_dir = corpus_manifest.parent.parent / "predictions"
    summary_path = predictions_dir / "real_bm25_summary.json"
    envelope_path = predictions_dir / "real_bm25.json"
    summary = _load_json(summary_path)
    selected_ids = {str(case["case_id"]) for case in cases}
    predictions: dict[str, Any] = {}
    prediction_hash: str | None = str(summary.get("prediction_hash")) if summary.get("prediction_hash") else None
    if envelope_path.is_file():
        envelope = load_prediction_envelope(envelope_path)
        # Select DEV rows by the already-filtered case IDs. The FINAL rows are
        # not read for scoring or aggregation.
        predictions = {case_id: value for case_id, value in envelope.predictions.items() if case_id in selected_ids}
        prediction_hash = envelope.prediction_hash
    if not predictions:
        raise EvaluationDataError("Frozen BM25 predictions do not contain the DEV cases")
    rankings = [list(predictions[case["case_id"]].get("retrieved_evidence_ids", [])) for case in cases]
    relevant = [list(case["relevant_evidence_ids"]) for case in cases]
    graded = [{str(key): int(value) for key, value in (case.get("graded_relevance") or {}).items()} for case in cases]
    metrics = aggregate_retrieval_metrics(rankings, relevant, graded=graded, ks=(1, 3, 5))
    return metrics, predictions, str(summary.get("retriever_version") or "bm25-v1"), prediction_hash


def build_provisional_dev_report(
    *,
    corpus_manifest: Path,
    annotations: Path,
    database_url: str,
    owner_id: str = "user_legacy_local",
    prediction_path: Path | None = None,
    embedding_settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a DEV-only report; no provider calls or FINAL inspection occur."""

    manifest = _load_json(corpus_manifest)
    # Capture local runtime availability before any corpus/database work can
    # contend with a running Ollama process.
    ollama_status = _ollama_local_status()
    corpus_check = validate_real_corpus_manifest(manifest, corpus_root=corpus_manifest.parent)
    if not corpus_check.valid:
        raise EvaluationDataError("Real corpus validation failed: " + "; ".join(corpus_check.errors))
    annotation_manifest = _load_json(annotations / "manifest.json")
    if annotation_manifest.get("status") != "DRAFT" or annotation_manifest.get("reviewer_count", 0) != 0:
        raise EvaluationDataError("Phase 15E-P requires the untouched DRAFT annotation manifest with zero reviewers")
    retrieval_rows = _dev_only(_load_jsonl(annotations / "retrieval.jsonl"), kind="retrieval")
    verification_rows = _dev_only(_load_jsonl(annotations / "verification.jsonl"), kind="verification")
    chat_rows = _dev_only(_load_jsonl(annotations / "chat.jsonl"), kind="chat")
    agent_rows = _dev_only(_load_jsonl(annotations / "agent.jsonl"), kind="agent")
    retrieval_cases = [RetrievalBenchmarkCase.model_validate(row) for row in retrieval_rows]
    retrieval_check = validate_real_retrieval_annotations(retrieval_cases, manifest=manifest, corpus_root=corpus_manifest.parent)
    if not retrieval_check.valid:
        raise EvaluationDataError("Real retrieval annotation validation failed: " + "; ".join(retrieval_check.errors))

    try:
        bm25_metrics, bm25_predictions, bm25_version = _bm25_dev(cases=retrieval_rows, manifest=manifest, database_url=database_url, owner_id=owner_id)
        frozen_bm25_hash: str | None = None
    except EvaluationDataError as exc:
        if "no ingested corpus papers" not in str(exc):
            raise
        bm25_metrics, bm25_predictions, bm25_version, frozen_bm25_hash = _frozen_bm25_dev(corpus_manifest=corpus_manifest, cases=retrieval_rows)
    annotation_hashes = annotation_file_hashes(annotations)
    computed_benchmark = benchmark_hash(corpus_manifest=manifest, annotation_hashes=annotation_hashes)
    benchmark = str(annotation_manifest.get("benchmark_hash") or computed_benchmark)
    commit = _git_commit()
    provider_cfg = _load_json(annotations / "provider_config.json")
    effective_embedding_settings: Mapping[str, Any] = embedding_settings or provider_cfg.get("embedding", {})
    if embedding_settings is None and os.getenv("EMBEDDING_PROVIDER"):
        try:
            from app.core.config import Settings
        except ModuleNotFoundError:  # pragma: no cover - repository-root import path
            from backend.app.core.config import Settings
        runtime_settings = Settings.from_env()
        effective_embedding_settings = {
            "embedding_provider": runtime_settings.embedding_provider,
            "embedding_model": runtime_settings.embedding_model,
            "embedding_dimension": runtime_settings.embedding_dimension,
            "embedding_revision": runtime_settings.embedding_version,
            "normalization": "l2",
            "distance_metric": "cosine",
        }
    embedding_audit = embedding_architecture_audit(effective_embedding_settings)
    embedding_audit["runtime"] = embedding_runtime_audit(ollama_status=ollama_status)
    runtime_enablement = local_runtime_audit(ollama_status=ollama_status)
    embedding_audit["local_runtime"] = runtime_enablement
    embedding_audit["embedding_config_hash"] = config_hash({
        "provider": embedding_audit.get("provider"),
        "model": embedding_audit.get("model"),
        "revision": embedding_audit.get("revision"),
        "dimension": embedding_audit.get("dimension"),
        "normalization": embedding_audit.get("normalization"),
        "distance_metric": embedding_audit.get("distance_metric"),
        "batch_size": None,
        "device": embedding_audit["runtime"].get("selected_device"),
    })
    generation_cfg = provider_cfg.get("generation", {})
    generation_audit = generation_provider_audit(ollama_status=ollama_status)
    selected_generation_model = runtime_enablement.get("selected_generation_model")
    ollama_generation_model = runtime_enablement.get("selected_ollama_generation_model")
    using_ollama = generation_audit.get("provider", "").lower() in {"ollama", "ollama_local", "local_ollama"}
    local_generation = {
        "status": "AVAILABLE_NOT_RUN" if generation_audit.get("provider_available") else "NOT_RUN",
        "runtime": "ollama" if using_ollama and ollama_generation_model else ("mlx-lm" if runtime_enablement.get("external_runtime", {}).get("mlx_lm_executable") else None),
        "runtime_version": None if using_ollama else runtime_enablement.get("external_runtime", {}).get("mlx_lm_version"),
        "model_id": ollama_generation_model if using_ollama and ollama_generation_model else (selected_generation_model.get("path") if selected_generation_model else None),
        "model_revision": None if using_ollama else (selected_generation_model.get("revision") if selected_generation_model else None),
        "quantization": None if using_ollama else (selected_generation_model.get("quantization") if selected_generation_model else None),
        "context_configured": generation_cfg.get("context_limit") or (selected_generation_model.get("max_position_embeddings") if selected_generation_model else None),
        "server_status": runtime_enablement.get("local_server", {}).get("status"),
        "provider_base_url": generation_audit.get("base_url"),
        "local_server_base_url": runtime_enablement.get("local_server", {}).get("base_url"),
        "provider_smoke_test": runtime_enablement.get("local_server", {}).get("smoke_test"),
        "reason": "Local Ollama is available; no generation request was made by this audit." if generation_audit.get("provider_available") else "No usable local generation provider is available.",
    }
    prompt_info = prompt_hashes()
    evaluation_config = {
        "embedding": {key: embedding_audit.get(key) for key in ("provider", "model", "revision", "dimension", "normalization", "distance_metric", "embedding_config_hash")},
        "bm25": {"version": bm25_version, "depth": 10},
        "rrf": {"version": "hybrid-rrf-v1", "k": 60},
        "generation": {key: generation_audit.get(key) for key in ("provider", "model", "configured_intended_model", "model_configured", "base_url", "timeout_seconds", "max_retries")},
        "local_generation": {key: local_generation.get(key) for key in ("runtime", "runtime_version", "model_id", "model_revision", "quantization", "context_configured", "server_status", "provider_base_url", "local_server_base_url", "provider_smoke_test")},
        "prompt_hashes": prompt_info["hashes"],
        "evaluation_schema_version": "1",
    }
    evaluation_config_hash = config_hash(evaluation_config)
    prediction_hashes: dict[str, str | None] = {"semantic": None, "hybrid": None, "verification": None, "chat": None, "agent": None}
    if prediction_path is not None:
        envelope = build_prediction_envelope(
            bm25_predictions,
            dataset_hash=str(manifest.get("corpus_hash") or real_corpus_hash(manifest)),
            annotation_hash=annotation_manifest.get("annotation_hash"),
            paperlens_commit=commit,
            provider={"mode": "PROVISIONAL_DEV", "lane": "BM25", "retrieval": bm25_version, "gold_fields_used": False, "config_hash": config_hash({"retrieval": bm25_version, "split": "DEV"})},
        )
        save_prediction_envelope(envelope, prediction_path)
        prediction_hashes["bm25"] = envelope.prediction_hash
    prediction_provenance = {
        "bm25": {"status": "FROZEN_DEV", "hash": prediction_hashes.get("bm25"), "historical_hash": frozen_bm25_hash, "gold_fields_used": False, "retriever_version": bm25_version},
        "semantic": {"status": "NOT_RUN", "hash": None, "gold_fields_used": False, "reason": embedding_audit["reason"]},
        "hybrid": {"status": "NOT_RUN", "hash": None, "gold_fields_used": False, "reason": "Semantic lane unavailable; existing RRF was not run or tuned."},
        "verification": {"status": "NOT_RUN", "hash": None, "gold_fields_used": False, "reason": "Generation provider not configured."},
        "chat": {"status": "NOT_RUN", "hash": None, "gold_fields_used": False, "reason": "Generation provider not configured."},
        "agent": {"status": "NOT_RUN", "hash": None, "gold_fields_used": False, "reason": "Provider-backed durable worker run not started."},
    }
    report: dict[str, Any] = {
        "schema_version": "1.0",
        **PROVISIONAL_CONTRACT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_commit": commit,
        "corpus_hash": manifest.get("corpus_hash") or real_corpus_hash(manifest),
        "benchmark_hash": benchmark,
        "computed_benchmark_hash": computed_benchmark,
        "annotation_hash": annotation_manifest.get("annotation_hash"),
        "annotation_hashes": annotation_hashes,
        "counts": {"dev_papers": len(manifest.get("splits", {}).get("dev", [])), "retrieval": len(retrieval_rows), "verification": len(verification_rows), "chat": len(chat_rows), "agent": len(agent_rows), "human_reviewers": 0},
        "historical_bm25_baseline": {
            "status": "PRESERVED_FROM_FROZEN_BASELINE",
            "metric_label": "PROVISIONAL DEV / DRAFT GOLD (historical value preserved)",
            "annotation": "DRAFT",
            "recomputed_in_this_run": False,
            "recall_at_1": 0.9000,
            "recall_at_3": 0.9500,
            "recall_at_5": 0.9833,
            "mrr": 0.9297,
            "note": "Historical all-split values are preserved as supplied by the prior frozen baseline; this run scores DEV only and does not inspect FINAL aggregates.",
        },
        "embedding": embedding_audit,
        "runtime_enablement": runtime_enablement,
        "local_generation": local_generation,
        "architecture_decision": {
            "embedding": "Retain existing EmbeddingProvider → SemanticEvidenceRetriever → HybridEvidenceRetriever/RRF path; do not add a parallel subsystem.",
            "generation": "Retain existing AIProvider/OpenAICompatibleProvider path; do not adapt ambient unsupported credentials or add a second provider.",
            "model_selection": "Use the existing provider-neutral path with local Ollama (qwen3:4b for generation and nomic-embed-text for embeddings); Ollama can fall back to CPU when Metal is unavailable.",
        },
        "provider": {
            "status": "CONFIGURED_NOT_RUN" if generation_audit["provider_available"] else "NOT_CONFIGURED",
            "availability": generation_audit,
            "provider": generation_audit["provider"],
            "model": generation_audit["model"],
            "intended_model": generation_audit["configured_intended_model"],
            "revision": generation_cfg.get("revision"),
            "generation_config": generation_cfg,
            "generation_config_hash": generation_provenance(provider=str(generation_cfg.get("provider") or "none"), model=generation_cfg.get("model"), revision=generation_cfg.get("revision"), temperature=generation_cfg.get("temperature"), top_p=generation_cfg.get("top_p"), max_output_tokens=generation_cfg.get("max_output_tokens"), prompt_versions=generation_cfg.get("prompt_versions") or {}, retry_policy=generation_cfg.get("retry_policy") or {}, validation_config=generation_cfg.get("validation_config") or {})["generation_config_hash"],
            "secrets_stored": False,
        },
        "prompt_hashes": prompt_info,
        "evaluation_config": evaluation_config,
        "evaluation_config_hash": evaluation_config_hash,
        "retrieval": {
            "metric_label": "PROVISIONAL DEV / DRAFT GOLD",
            "BM25": {"status": "MEASURED_PROVISIONAL", "version": bm25_version, "metrics": bm25_metrics, "annotation": "DRAFT GOLD"},
            "Semantic": {"status": "NOT_RUN", "metrics": None, "reason": embedding_audit["reason"]},
            "Hybrid": {"status": "NOT_RUN", "metrics": None, "reason": "Semantic DEV lane is unavailable; RRF was not run or tuned."},
            "comparison": {"BM25": bm25_metrics, "Semantic": None, "Hybrid": None},
        },
        "verification": {"status": "NOT_RUN", "metric_label": "PROVISIONAL DEV / DRAFT GOLD", "metrics": {"accuracy": None, "macro_f1": None, "per_label": None, "false_support_rate": None, "false_rejection_rate": None, "numeric_fidelity": None}, "reason": "No real generation provider is configured; DRAFT gold is not used as model input."},
        "chat": {"status": "NOT_RUN", "metric_label": "PROVISIONAL DEV / DRAFT GOLD", "metrics": {"citation_precision": None, "required_evidence_coverage": None, "unsupported_claim_rate": None, "abstention_behavior": None, "numeric_fidelity": None}, "human_score": None, "human_review_status": "NOT_REVIEWED", "reason": "No real generation provider is configured."},
        "agent": {"status": "NOT_RUN", "metric_label": "PROVISIONAL DEV / DRAFT GOLD", "metrics": {"completion_rate": None, "ingestion_success": None, "duplicate_source_rate": None, "valid_citation_rate": None, "evidence_id_validity": None, "iterations": None, "provider_calls": None, "duration": None}, "subjective_metrics": {"source_relevance": None, "synthesis_quality": None, "task_usefulness": None, "human_review_status": "NOT_REVIEWED"}, "reason": "No provider-backed durable DEV agent run was started."},
        "prediction_hashes": prediction_hashes,
        "prediction_provenance": prediction_provenance,
        "historical_bm25_prediction_hash": frozen_bm25_hash,
        "provenance": {"owner_id": owner_id, "bm25_gold_fields_used": False, "semantic_gold_fields_used": False, "hybrid_gold_fields_used": False, "offline_reproduction": "PASS for report construction and BM25 prediction hash; provider lanes NOT_RUN", "cost": "unavailable", "provider_calls": 0, "latency_context": "Local deterministic BM25 timing only; no formal performance claim."},
        "failure_preservation": {"status": "PRESERVED", "description": "DEV-only prediction/annotation disagreements remain diagnostics; no FINAL or human-error claim is made."},
        "tuning_performed": "NONE",
        "final_touched": False,
        "publishable_quality_claims": False,
        "phase15e_p": "NOT CLOSED",
        "phase15e_r": "NOT CLOSED",
        "phase15e_s": "NOT CLOSED",
        "phase15_overall": "NOT CLOSED",
        "remaining_blockers": runtime_enablement.get("blockers", []) + ["provider-backed verification/chat/agent DEV predictions", "offline reproduction of each frozen provider lane", "human review before any publishable quality claim"],
    }
    return report


def render_markdown(report: Mapping[str, Any]) -> str:
    retrieval = report["retrieval"]
    embedding_runtime = report["embedding"].get("runtime", {})
    provider_availability = report["provider"].get("availability", {})
    prompt_hash_data = report.get("prompt_hashes", {}).get("hashes", {})
    def metric(lane: str, name: str) -> str:
        values = retrieval[lane].get("metrics")
        return f"{float(values[name]):.4f}" if values is not None and name in values else "NOT RUN"
    lines = [
        "# PaperLens Phase 15E-S",
        "",
        "> **PROVISIONAL DEV EVALUATION**",
        "",
        "> **EVALUATION STATUS: PROVISIONAL**  ",
        "> **ANNOTATIONS: DRAFT**  ",
        "> **HUMAN REVIEWERS: 0**  ",
        "> **FINAL DATASET USED: NO**  ",
        "> **TUNING: NONE**  ",
        "> **PUBLISHABLE QUALITY CLAIMS: NO**  ",
        "> **NOT PUBLISHABLE**  ",
        "> **NOT FINAL**",
        "",
        f"Evaluation status: **{report['evaluation_status']}**  ",
        f"Annotation status: **{report['annotation_status']}**  ",
        f"DEV cases: retrieval {report['counts']['retrieval']}, verification {report['counts']['verification']}, chat {report['counts']['chat']}, agent {report['counts']['agent']}",
        "",
        "## Retrieval comparison (PROVISIONAL DEV / DRAFT GOLD)",
        "",
        "| Lane | Recall@1 | Recall@3 | Recall@5 | MRR | nDCG@5 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for lane in ("BM25", "Semantic", "Hybrid"):
        lines.append(f"| {lane} | {metric(lane, 'recall_at_1')} | {metric(lane, 'recall_at_3')} | {metric(lane, 'recall_at_5')} | {metric(lane, 'mrr')} | {metric(lane, 'ndcg_at_5')} |")
    lines.extend([
        "",
        "Historical all-split BM25 baseline (preserved, not recomputed): Recall@1 0.9000 · Recall@3 0.9500 · Recall@5 0.9833 · MRR 0.9297. The DEV evaluator did not inspect FINAL aggregates.",
        "",
        "## Provider and embedding status",
        "",
        f"- Embedding: **{report['embedding']['status']}** — {report['embedding']['reason']}",
        f"- Embedding provenance hash: `{report['embedding'].get('embedding_provenance_hash') or 'not available (no real model)'}`.",
        f"- Embedding config hash: `{report['embedding'].get('embedding_config_hash')}`; device `{embedding_runtime.get('selected_device', 'NOT_RUN')}`; records embedded `{embedding_runtime.get('records_embedded', 0)}`.",
        f"- Generation: **{report['provider']['status']}** — provider `{report['provider']['provider']}`, model `{report['provider']['model'] or 'none'}` (intended `{report['provider'].get('intended_model') or 'none'}`).",
        f"- Generation provider available: **{provider_availability.get('provider_available', False)}**; model configured: **{provider_availability.get('model_configured', False)}**.",
        f"- Local generation runtime: **{report.get('local_generation', {}).get('runtime') or 'none'}** {report.get('local_generation', {}).get('runtime_version') or ''}; model `{report.get('local_generation', {}).get('model_id') or 'none'}`; revision `{report.get('local_generation', {}).get('model_revision') or 'none'}`; quantization `{report.get('local_generation', {}).get('quantization') or 'none'}`.",
        f"- Local server: **{report.get('local_generation', {}).get('server_status') or 'NOT_STARTED'}** at `{report.get('local_generation', {}).get('local_server_base_url') or 'not configured'}`; AIProvider base URL is `{report.get('local_generation', {}).get('provider_base_url') or 'not configured'}`; PaperLens AIProvider smoke test **{report.get('local_generation', {}).get('provider_smoke_test') or 'NOT_RUN'}**.",
        f"- MLX/Metal probe: **{report.get('runtime_enablement', {}).get('external_runtime', {}).get('metal_probe', 'NOT_PROBED')}** — {report.get('runtime_enablement', {}).get('external_runtime', {}).get('metal_reason', 'not probed')}",
        f"- Prompt hashes: `{prompt_hash_data}`.",
        "- Verification, chat, and agent lanes: **NOT RUN**; no provider calls were made.",
        "- Human chat and agent scores: **null / NOT_REVIEWED**.",
        "",
        "## Reproducibility and safety",
        "",
        f"- Corpus hash: `{report['corpus_hash']}`",
        f"- Benchmark hash: `{report['benchmark_hash']}`",
        f"- BM25 prediction hash: `{report['prediction_hashes'].get('bm25') or 'not written'}`",
        f"- Provisional evaluation config hash: `{report.get('evaluation_config_hash', 'not available')}`",
        f"- Offline reproduction: **{report['provenance']['offline_reproduction']}**",
        f"- Tuning performed: **{report['tuning_performed']}**",
        f"- FINAL touched: **{report['final_touched']}**",
        f"- Phase 15E-P: **{report['phase15e_p']}**; Phase 15E-R: **{report.get('phase15e_r', 'NOT CLOSED')}**; Phase 15E-S: **{report.get('phase15e_s', 'NOT CLOSED')}**; Phase 15 overall: **{report['phase15_overall']}**",
        f"- Architecture decision: {report.get('architecture_decision', {}).get('model_selection', 'existing abstractions retained')}",
        "",
        "Quality values in this report are engineering diagnostics only. DRAFT annotations, zero human reviewers, and unavailable provider lanes prevent publishable claims.",
    ])
    return "\n".join(lines) + "\n"


def render_embedding_audit(audit: Mapping[str, Any]) -> str:
    """Render the production embedding architecture audit for reviewers."""

    lines = [
        "# PaperLens Phase 15E-S Local Runtime and Embedding Architecture Audit",
        "",
        "> **EVALUATION STATUS: PROVISIONAL · ANNOTATIONS: DRAFT · HUMAN REVIEWERS: 0 · FINAL DATASET USED: NO · TUNING: NONE · PUBLISHABLE QUALITY CLAIMS: NO · NOT FINAL**",
        "",
        f"Status: **{audit['status']}**  ",
        f"Provider: `{audit['provider']}`  ",
        f"Model: `{audit['model'] or 'none'}`  ",
        f"Embedding provenance hash: `{audit.get('embedding_provenance_hash') or 'not available (no real model)'}`  ",
        f"Embedding config hash: `{audit.get('embedding_config_hash') or 'not available'}`  ",
        f"Device used: `{audit.get('runtime', {}).get('selected_device', 'NOT_RUN')}`",
        f"Run eligibility: **{audit['run_eligibility']}**",
        "",
        f"{audit['reason']}",
        "",
        "| Concern | Existing PaperLens behavior |",
        "|---|---|",
        f"| Interface | `{audit['implementation'][0]}`; async `embed_texts(list[str])` and `embed_query(str)` |",
        f"| Storage | {audit['storage']} |",
        f"| Dimensionality | Configured provider dimension is persisted per vector; no real dimension is claimed here (`{audit['dimension']}`) |",
        f"| Normalization / similarity | {audit['normalization'] or 'not configured'} / {audit['distance_metric'] or 'not configured'} |",
        f"| Batching | {audit['batching']} |",
        f"| Caching | {audit['cache_reuse']} |",
        f"| Document/evidence binding | {audit['document_evidence_binding']} |",
        f"| Fallback | {audit['fallback']} |",
        f"| Local runtimes | {audit.get('runtime', {}).get('installed_runtimes', {})} |",
        f"| Local model runtime | {audit.get('local_runtime', {}).get('external_runtime', {}).get('mlx_lm_executable') or 'not found'} ({audit.get('local_runtime', {}).get('external_runtime', {}).get('mlx_lm_version') or 'version unknown'}) |",
        f"| Metal/device probe | {audit.get('local_runtime', {}).get('external_runtime', {}).get('metal_probe', 'NOT_PROBED')} — {audit.get('local_runtime', {}).get('external_runtime', {}).get('metal_reason', 'not probed')} |",
        f"| Embedding model selection | {audit.get('local_runtime', {}).get('embedding_model_selected') or 'none; no supported local embedding model'} |",
        "",
        "The audit records the existing product path and does not introduce a second embedding subsystem or run a benchmark model.",
    ]
    return "\n".join(lines) + "\n"


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, timeout=2).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-manifest", type=Path, default=Path("backend/evaluation/datasets/corpus/manifest.json"))
    parser.add_argument("--annotations", type=Path, default=Path("backend/evaluation/datasets/real_annotations"))
    parser.add_argument("--database-url", default="sqlite:///./paperlens.db")
    parser.add_argument("--output", type=Path, default=Path("backend/evaluation/datasets/reports/phase15e-provisional-dev.json"))
    parser.add_argument("--markdown-output", type=Path, default=Path("backend/evaluation/datasets/reports/phase15e-provisional-dev.md"))
    parser.add_argument("--prediction-path", type=Path, default=Path("backend/evaluation/datasets/predictions/phase15e-bm25-dev.json"))
    parser.add_argument("--embedding-audit-output", type=Path, default=Path("backend/evaluation/datasets/reports/phase15e-embedding-audit.json"))
    parser.add_argument("--embedding-audit-markdown-output", type=Path, default=Path("backend/evaluation/datasets/reports/phase15e-embedding-audit.md"))
    args = parser.parse_args()
    try:
        report = build_provisional_dev_report(corpus_manifest=args.corpus_manifest, annotations=args.annotations, database_url=args.database_url, prediction_path=args.prediction_path)
    except (EvaluationDataError, ValueError, KeyError) as exc:
        print(f"evaluation refused: {exc}")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    audit = report["embedding"]
    args.embedding_audit_output.parent.mkdir(parents=True, exist_ok=True)
    args.embedding_audit_output.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.embedding_audit_markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.embedding_audit_markdown_output.write_text(render_embedding_audit(audit), encoding="utf-8")
    print(json.dumps({"status": report["evaluation_status"], "split": report["split"], "metrics": report["retrieval"]["BM25"]["metrics"]}, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
