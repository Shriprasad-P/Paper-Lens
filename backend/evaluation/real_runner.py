"""Run the real-corpus evaluation lanes against a persisted PaperLens database.

This command intentionally measures only what is configured.  In particular,
it never substitutes ``hash-v1`` for semantic retrieval: without a real
embedding provider the semantic and hybrid lanes are recorded as NOT_RUN.
Human-review state is carried through to the report, so a draft corpus cannot
accidentally be labelled publishable.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

try:  # ``PYTHONPATH=backend`` is used by the CLI; package imports serve tests.
    from app.chat.retrieval import BM25EvidenceRetriever
    from app.core.config import Settings
    from app.db.database import SQLDatabase
except ModuleNotFoundError:  # pragma: no cover - exercised from repository root
    from backend.app.chat.retrieval import BM25EvidenceRetriever
    from backend.app.core.config import Settings
    from backend.app.db.database import SQLDatabase

from .metrics import aggregate_retrieval_metrics
from .provenance import EvaluationDataError, build_prediction_envelope, config_hash, save_prediction_envelope
from .schemas import RetrievalBenchmarkCase
from .validation import require_reviewed_cases, validate_frozen_rankings, validate_real_corpus_manifest, validate_real_retrieval_annotations


GOLD_ANNOTATION_FIELDS = frozenset(
    {
        "relevant_evidence_ids",
        "secondary_evidence_ids",
        "required_evidence_ids",
        "allowed_evidence_ids",
        "graded_relevance",
        "gold_status",
        "expected_answer_points",
        "forbidden_claims",
        "numeric_facts",
        "predictions",
        "prediction",
        "reviewer_id",
        "reviewed_at",
        "reviewer_notes",
        "annotation_status",
    }
)


def retrieval_request(case: Mapping[str, Any]) -> dict[str, Any]:
    """Build the retrieval-only input, excluding every gold annotation field."""

    return {
        "case_id": case.get("case_id"),
        "paper_id": case.get("paper_id"),
        "document_id": case.get("document_id"),
        "query": case.get("query"),
        "split": case.get("split"),
    }


def run_real_retrieval(
    *,
    corpus_manifest: Path,
    annotations: Path,
    database_url: str,
    owner_id: str = "user_legacy_local",
    prediction_path: Path | None = None,
    require_reviewed: bool = False,
) -> dict[str, Any]:
    """Run BM25 on real, ingested Evidence Registry records."""

    manifest = json.loads(corpus_manifest.read_text(encoding="utf-8"))
    validation = validate_real_corpus_manifest(manifest, corpus_root=corpus_manifest.parent)
    if not validation.valid:
        raise ValueError("Real corpus validation failed: " + "; ".join(validation.errors))
    annotation_manifest = json.loads((annotations / "manifest.json").read_text(encoding="utf-8"))
    cases = [json.loads(line) for line in (annotations / "retrieval.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    annotation_validation = validate_real_retrieval_annotations(
        [RetrievalBenchmarkCase.model_validate(case) for case in cases],
        manifest=manifest,
        corpus_root=corpus_manifest.parent,
    )
    if not annotation_validation.valid:
        raise ValueError("Real retrieval annotation validation failed: " + "; ".join(annotation_validation.errors))
    if require_reviewed:
        try:
            require_reviewed_cases(cases)
        except ValueError as exc:
            pending = [str(case.get("case_id", "<unknown>")) for case in cases if case.get("annotation_status") not in {"REVIEWED", "ADJUDICATED"}]
            suffix = f" Pending cases include: {', '.join(pending[:5])}" if pending else ""
            raise ValueError(f"Reviewed-only run refused: {len(pending) or 'some'} case(s) are not publishable.{suffix}") from exc
    paper_by_id = {paper["paper_id"]: paper for paper in manifest["papers"]}
    db = SQLDatabase(database_url, create_schema=False)
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
            "document_id": case["document_id"],
            "retrieved_evidence_ids": ranking,
            "scores": {item.evidence_id: item.score for item in items},
            "retriever_version": retriever.version,
            "split": case.get("split"),
        }
    ranking_report = validate_frozen_rankings(
        {case_id: prediction["retrieved_evidence_ids"] for case_id, prediction in predictions.items()},
        [case["case_id"] for case in cases],
    )
    ranking_report.raise_if_invalid()
    metrics = aggregate_retrieval_metrics(rankings, relevant, graded=graded, ks=(1, 3, 5))
    metrics["hit_at_5"] = sum(float(bool(set(rank[:5]) & set(truth))) for rank, truth in zip(rankings, relevant)) / len(cases) if cases else 0.0
    result = {
        "component": "retrieval",
        "status": "PRELIMINARY",
        "case_count": len(cases),
        "metrics": metrics,
        "lanes": {
            "BM25": {"status": "MEASURED", "retriever_version": retriever.version, "metrics": metrics},
            "Semantic": {"status": "NOT_RUN", "reason": "No real embedding provider configured; hash-v1 is excluded."},
            "Hybrid": {"status": "NOT_RUN", "reason": "Semantic lane unavailable; no hybrid score is reported."},
        },
        "annotation_status": annotation_manifest.get("status", "DRAFT"),
        "human_reviewed": bool(annotation_manifest.get("human_reviewed", False)),
        "provenance": {
            "corpus_hash": manifest.get("corpus_hash"),
            "annotation_hash": annotation_manifest.get("annotation_hash"),
            "paperlens_commit": _git_commit(),
            "database_url": database_url,
            "owner_id": owner_id,
        },
    }
    if prediction_path:
        envelope = build_prediction_envelope(
            predictions,
            dataset_hash=str(manifest["corpus_hash"]),
            annotation_hash=annotation_manifest.get("annotation_hash"),
            paperlens_commit=result["provenance"]["paperlens_commit"],
            provider={"mode": "production_retrieval", "retrieval": retriever.version, "semantic": "NOT_RUN", "hybrid": "NOT_RUN", "config_hash": config_hash({"retrieval": retriever.version, "semantic": "NOT_RUN", "hybrid": "NOT_RUN"})},
        )
        save_prediction_envelope(envelope, prediction_path)
        result["provenance"]["prediction_hash"] = envelope.prediction_hash
    return result


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-manifest", type=Path, default=Path("backend/evaluation/datasets/corpus/manifest.json"))
    parser.add_argument("--annotations", type=Path, default=Path("backend/evaluation/datasets/real_annotations"))
    parser.add_argument("--database-url", default=Settings.from_env().database_url)
    parser.add_argument("--output", type=Path, default=Path("backend/evaluation/datasets/predictions/real_retrieval_result.json"))
    parser.add_argument("--prediction-path", type=Path, default=Path("backend/evaluation/datasets/predictions/real_bm25.json"))
    parser.add_argument("--require-reviewed", action="store_true", help="Refuse to score any non-reviewed case.")
    args = parser.parse_args()
    try:
        result = run_real_retrieval(corpus_manifest=args.corpus_manifest, annotations=args.annotations, database_url=args.database_url, prediction_path=args.prediction_path, require_reviewed=args.require_reviewed)
    except (EvaluationDataError, ValueError) as exc:
        print(f"evaluation refused: {exc}")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "case_count": result["case_count"], "metrics": result["metrics"]}, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
