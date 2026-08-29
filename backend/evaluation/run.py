"""Command-line entry point for reproducible PaperLens evaluation runs."""

from __future__ import annotations

import argparse
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .fixtures.loaders import dataset_hash, load_failure_examples, load_frozen_smoke_predictions, load_manifest, load_manifest_model, load_paper_annotations, load_smoke_cases
from .provenance import sha256_file
from .reports.writer import write_report
from .runners.offline import run_all, run_component
from .schemas import EvaluationReport, EvaluationRunMetadata, EvaluationStatus
from .validation import validate_agent_tasks, validate_chat_cases, validate_manifest, validate_paper_annotations, validate_retrieval_cases, validate_verification_cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run PaperLens offline evaluation benchmarks.")
    parser.add_argument("component", choices=["smoke", "parsing", "extraction", "evidence", "verification", "retrieval", "chat", "research_agent", "synthesis", "performance", "all"])
    parser.add_argument("--output-dir", type=Path, default=Path("evaluation-results"))
    parser.add_argument("--retrieval-mode", default=os.getenv("RETRIEVAL_MODE", "LEXICAL"))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--live", action="store_true", help="Mark an explicitly controlled live run; ordinary commands never call external providers.")
    parser.add_argument("--split", choices=["DEV", "FINAL", "SMOKE"], default="SMOKE")
    parser.add_argument("--validate-inputs", action="store_true", help="Validate benchmark manifest and human annotation ledger, then exit.")
    args = parser.parse_args(argv)
    metadata = build_metadata(args)
    manifest = load_manifest()
    cases = load_smoke_cases()
    manifest_model = load_manifest_model()
    annotation_report = validate_paper_annotations(manifest_model, load_paper_annotations())
    manifest_report = validate_manifest(manifest_model)
    case_reports = {
        "retrieval": validate_retrieval_cases(cases["retrieval"]),
        "verification": validate_verification_cases(cases["verification"]),
        "chat": validate_chat_cases(cases["chat"]),
        "research_agent": validate_agent_tasks(cases["research_agent"]),
    }
    if args.validate_inputs:
        all_reports = (manifest_report, annotation_report, *case_reports.values())
        for warning in tuple(warning for report in all_reports for warning in report.warnings):
            print(f"warning: {warning}")
        for error in tuple(error for report in all_reports for error in report.errors):
            print(f"error: {error}")
        return 0 if all(report.valid for report in all_reports) else 2
    if args.component == "smoke":
        components = ["retrieval", "evidence", "verification", "chat", "research_agent", "synthesis"]
    elif args.component == "all":
        components = ["parsing", "extraction", "retrieval", "verification", "chat", "research_agent", "synthesis"]
    else:
        components = [args.component]
    results = [run_component(component, metadata) for component in components]
    report = EvaluationReport(
        status=EvaluationStatus.PRELIMINARY,
        metadata=metadata,
        results=results,
        recommendations=[
            "Add reviewed/adjudicated annotations and frozen production predictions before treating metrics as validated.",
            "Keep BM25 as the production default until a measured quality/latency benchmark supports a change.",
            "The checked-in public-paper manifest is identifier-only; acquire and hash immutable PDF versions before publishing quality numbers.",
        ],
        failure_examples=load_failure_examples(),
    )
    output_dir = args.output_dir / datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    json_path, markdown_path = write_report(report, output_dir)
    (output_dir / "manifest-summary.json").write_text(__import__("json").dumps({"benchmark_version": manifest["benchmark_version"], "dataset_version": manifest["dataset_version"], "paper_count": len(manifest["papers"]), "retrieval_query_count": len(cases["retrieval"]), "verification_case_count": len(cases["verification"]), "chat_question_count": len(cases["chat"]), "manifest_validation": manifest_report.__dict__, "annotation_validation": annotation_report.__dict__, "case_validation": {name: report.__dict__ for name, report in case_reports.items()}}, indent=2, default=list), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")
    return 0


def build_metadata(args: argparse.Namespace) -> EvaluationRunMetadata:
    manifest = load_manifest()
    prediction_snapshot = load_frozen_smoke_predictions()
    annotation_path = Path(__file__).parent / "datasets" / "annotations.jsonl"
    return EvaluationRunMetadata(
        benchmark_version=manifest["benchmark_version"],
        dataset_version=manifest["dataset_version"],
        annotation_version="v1",
        metric_version="v1",
        evaluation_schema_version="1",
        git_commit=_git_commit(),
        dataset_hash=dataset_hash(),
        annotation_hash=sha256_file(annotation_path),
        prediction_hash=prediction_snapshot.prediction_hash,
        retrieval_mode=args.retrieval_mode,
        ai_provider=os.getenv("AI_PROVIDER", "none") if not args.live else os.getenv("AI_PROVIDER", "configured-live"),
        ai_model=os.getenv("AI_MODEL") if args.live else None,
        embedding_provider=os.getenv("EMBEDDING_PROVIDER", "none"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "hash-v1"),
        prompt_versions={"extraction": "v1", "verification": "v1", "chat": "v1", "research": "v1"},
        schema_versions={"evaluation": "v1"},
        provider_settings={"mode": "live" if args.live else "offline", "temperature": os.getenv("AI_TEMPERATURE") if args.live else None, "max_tokens": os.getenv("AI_MAX_TOKENS") if args.live else None},
        split=args.split,
        random_seed=args.seed,
        live=args.live,
    )


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, timeout=2).strip()
    except (OSError, subprocess.SubprocessError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
