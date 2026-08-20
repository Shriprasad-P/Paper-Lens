"""Command-line entry point for reproducible PaperLens evaluation runs."""

from __future__ import annotations

import argparse
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .fixtures.loaders import load_manifest, load_smoke_cases
from .reports.writer import write_report
from .runners.offline import run_all, run_component
from .schemas import EvaluationReport, EvaluationRunMetadata, EvaluationStatus


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run PaperLens offline evaluation benchmarks.")
    parser.add_argument("component", choices=["smoke", "parsing", "extraction", "evidence", "verification", "retrieval", "chat", "research_agent", "synthesis", "performance", "all"])
    parser.add_argument("--output-dir", type=Path, default=Path("evaluation-results"))
    parser.add_argument("--retrieval-mode", default=os.getenv("RETRIEVAL_MODE", "LEXICAL"))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--live", action="store_true", help="Mark an explicitly controlled live run; ordinary commands never call external providers.")
    args = parser.parse_args(argv)
    metadata = build_metadata(args)
    manifest = load_manifest()
    cases = load_smoke_cases()
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
        ],
    )
    output_dir = args.output_dir / datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    json_path, markdown_path = write_report(report, output_dir)
    (output_dir / "manifest-summary.json").write_text(__import__("json").dumps({"benchmark_version": manifest["benchmark_version"], "dataset_version": manifest["dataset_version"], "paper_count": len(manifest["papers"]), "retrieval_query_count": len(cases["retrieval"]), "verification_case_count": len(cases["verification"]), "chat_question_count": len(cases["chat"])}, indent=2), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")
    return 0


def build_metadata(args: argparse.Namespace) -> EvaluationRunMetadata:
    manifest = load_manifest()
    return EvaluationRunMetadata(
        benchmark_version=manifest["benchmark_version"],
        dataset_version=manifest["dataset_version"],
        annotation_version="v1",
        metric_version="v1",
        git_commit=_git_commit(),
        retrieval_mode=args.retrieval_mode,
        ai_provider=os.getenv("AI_PROVIDER", "none") if not args.live else os.getenv("AI_PROVIDER", "configured-live"),
        ai_model=os.getenv("AI_MODEL") if args.live else None,
        embedding_provider=os.getenv("EMBEDDING_PROVIDER", "none"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "hash-v1"),
        prompt_versions={"extraction": "v1", "verification": "v1", "chat": "v1", "research": "v1"},
        schema_versions={"evaluation": "v1"},
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
