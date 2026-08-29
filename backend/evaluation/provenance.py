"""Reproducibility and validation helpers for the Phase 15 evaluator.

The evaluator deliberately treats benchmark data, annotations, and model
predictions as separate, hashable inputs.  These helpers are dependency-light
so an offline report can be regenerated without importing the application
runtime or contacting a provider.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "1"
HASH_ALGORITHM = "sha256"


class EvaluationDataError(ValueError):
    """Raised when benchmark data cannot be used safely."""


def canonical_json(value: Any) -> bytes:
    """Return stable JSON bytes for hashing and provenance records."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_paths(paths: Iterable[Path], *, root: Path | None = None) -> str:
    """Hash a deterministic set of files including relative names."""

    resolved = sorted((path for path in paths if path.is_file()), key=lambda p: str(p))
    digest = hashlib.sha256()
    for path in resolved:
        relative = path.relative_to(root) if root else path
        digest.update(str(relative).replace("\\", "/").encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


DEFAULT_ANNOTATION_FILES = (
    "retrieval.jsonl",
    "verification.jsonl",
    "chat.jsonl",
    "agent.jsonl",
)


def annotation_file_hashes(
    annotation_dir: Path,
    *,
    filenames: Iterable[str] = DEFAULT_ANNOTATION_FILES,
) -> dict[str, str]:
    """Hash the canonical JSONL ledgers without normalising their bytes.

    Annotation files are intentionally hashed exactly as stored.  A reviewer
    changing a label, evidence ID, or note therefore changes the benchmark
    identity even when the resulting JSON has the same semantic shape.
    """

    names = list(dict.fromkeys(str(name) for name in filenames))
    missing = [name for name in names if not (annotation_dir / name).is_file()]
    if missing:
        raise EvaluationDataError("Annotation ledger is missing: " + ", ".join(missing))
    return {name: sha256_file(annotation_dir / name) for name in names}


def combined_annotation_hash(
    annotation_dir: Path,
    *,
    filenames: Iterable[str] = DEFAULT_ANNOTATION_FILES,
) -> str:
    """Return the frozen hash of the ordered annotation ledger bytes."""

    names = list(dict.fromkeys(str(name) for name in filenames))
    try:
        payload = b"".join((annotation_dir / name).read_bytes() for name in names)
    except OSError as exc:
        raise EvaluationDataError("Cannot read annotation ledgers") from exc
    return sha256_bytes(payload)


def real_corpus_hash(manifest: Mapping[str, Any]) -> str:
    """Hash the immutable identity of a real evaluation corpus.

    Timestamps, local paths, and mutable review state are deliberately omitted;
    source/version/PDF/document/evidence identities and paper-separated splits
    are the reproducibility boundary.
    """

    papers = manifest.get("papers", []) if isinstance(manifest, Mapping) else []
    identity = {
        "corpus_schema_version": manifest.get("corpus_schema_version"),
        "benchmark_version": manifest.get("benchmark_version"),
        "dataset_version": manifest.get("dataset_version"),
        "corpus_kind": manifest.get("corpus_kind"),
        "evidence_registry_hash": manifest.get("evidence_registry_hash"),
        "documents_export_hash": manifest.get("documents_export_hash"),
        "splits": manifest.get("splits", {}),
        "papers": [
            {
                key: paper.get(key)
                for key in (
                    "paper_id",
                    "source_identifier",
                    "version",
                    "versioned_identifier",
                    "source_pdf_sha256",
                    "paperlens_source_id",
                    "paperlens_document_id",
                    "normalized_document_hash",
                    "parser_version",
                    "ingestion_version",
                    "evidence_registry_version",
                    "evidence_count",
                    "ingestion_status",
                    "split",
                )
            }
            for paper in papers
        ],
    }
    return sha256_json(identity)


def benchmark_hash(
    *,
    corpus_manifest: Mapping[str, Any],
    annotation_hashes: Mapping[str, str],
    schema_versions: Mapping[str, str] | None = None,
) -> str:
    """Identify one benchmark version across corpus, annotations, and schema."""

    return sha256_json(
        {
            "corpus_hash": corpus_manifest.get("corpus_hash") or real_corpus_hash(corpus_manifest),
            "splits": corpus_manifest.get("splits", {}),
            "annotation_hashes": dict(sorted(annotation_hashes.items())),
            "schema_versions": dict(sorted((schema_versions or {}).items())),
        }
    )


def config_hash(config: Mapping[str, Any]) -> str:
    """Hash a provider/retrieval configuration without retaining secrets."""

    return sha256_json(dict(config))


def embedding_provenance(
    *,
    provider: str,
    model: str,
    revision: str | None,
    dimension: int,
    normalization: str,
    distance_metric: str,
    chunk_strategy: str,
    document_hash: str,
    evidence_id: str,
) -> dict[str, Any]:
    """Return reproducible identity for one evidence embedding artifact."""

    config = {
        "provider": provider,
        "model": model,
        "revision": revision,
        "dimension": dimension,
        "normalization": normalization,
        "distance_metric": distance_metric,
        "chunk_strategy": chunk_strategy,
    }
    return {
        "document_hash": document_hash,
        "evidence_id": evidence_id,
        "embedding_config": config,
        "embedding_config_hash": config_hash(config),
    }


def generation_provenance(
    *,
    provider: str,
    model: str,
    revision: str | None,
    temperature: float,
    top_p: float,
    max_output_tokens: int,
    prompt_versions: Mapping[str, str],
    retry_policy: Mapping[str, Any],
    validation_config: Mapping[str, Any],
) -> dict[str, Any]:
    """Return secret-free identity for a provider-backed generation run."""

    config = {
        "provider": provider,
        "model": model,
        "revision": revision,
        "temperature": temperature,
        "top_p": top_p,
        "max_output_tokens": max_output_tokens,
        "prompt_versions": dict(prompt_versions),
        "retry_policy": dict(retry_policy),
        "validation_config": dict(validation_config),
    }
    return {"generation_config": config, "generation_config_hash": config_hash(config)}


@dataclass(frozen=True)
class FrozenPredictionEnvelope:
    """A provider-independent prediction snapshot.

    ``predictions`` is intentionally opaque to the evaluator.  Component
    runners validate the shape they consume, while this envelope guarantees
    that the exact bytes and generation configuration are recorded.
    """

    schema_version: str
    dataset_hash: str
    annotation_hash: str | None
    paperlens_commit: str | None
    provider: Mapping[str, Any]
    predictions: Mapping[str, Any]
    prediction_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "evaluation_schema_version": self.schema_version,
            "dataset_hash": self.dataset_hash,
            "annotation_hash": self.annotation_hash,
            "paperlens_commit": self.paperlens_commit,
            "provider": dict(self.provider),
            "predictions": self.predictions,
            "prediction_hash": self.prediction_hash,
        }


def build_prediction_envelope(
    predictions: Mapping[str, Any],
    *,
    dataset_hash: str,
    annotation_hash: str | None = None,
    paperlens_commit: str | None = None,
    provider: Mapping[str, Any] | None = None,
) -> FrozenPredictionEnvelope:
    """Build an immutable-style envelope and hash the prediction payload."""

    payload = dict(predictions)
    return FrozenPredictionEnvelope(
        schema_version=SCHEMA_VERSION,
        dataset_hash=dataset_hash,
        annotation_hash=annotation_hash,
        paperlens_commit=paperlens_commit,
        provider=dict(provider or {"mode": "offline", "provider": "none", "model": None}),
        predictions=payload,
        prediction_hash=sha256_json(payload),
    )


def save_prediction_envelope(envelope: FrozenPredictionEnvelope, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(envelope.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_prediction_envelope(path: Path) -> FrozenPredictionEnvelope:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationDataError(f"Cannot read frozen predictions: {path}") from exc
    required = {"evaluation_schema_version", "dataset_hash", "predictions", "prediction_hash"}
    missing = sorted(required - raw.keys()) if isinstance(raw, dict) else sorted(required)
    if missing:
        raise EvaluationDataError(f"Frozen predictions missing required fields: {', '.join(missing)}")
    calculated = sha256_json(raw["predictions"])
    if calculated != raw["prediction_hash"]:
        raise EvaluationDataError("Frozen prediction hash does not match its payload")
    return FrozenPredictionEnvelope(
        schema_version=str(raw["evaluation_schema_version"]),
        dataset_hash=str(raw["dataset_hash"]),
        annotation_hash=raw.get("annotation_hash"),
        paperlens_commit=raw.get("paperlens_commit"),
        provider=raw.get("provider") or {},
        predictions=raw["predictions"],
        prediction_hash=raw["prediction_hash"],
    )
