"""Persist compact JSON and Markdown evaluation reports."""

from __future__ import annotations

from pathlib import Path

from ..schemas import EvaluationReport, EvaluationResult


def write_report(report: EvaluationReport, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "report.json"
    markdown_path = output_dir / "report.md"
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    (output_dir / "metadata.json").write_text(report.metadata.model_dump_json(indent=2), encoding="utf-8")
    for result in report.results:
        (output_dir / f"{result.component}.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    markdown_path.write_text(to_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def to_markdown(report: EvaluationReport) -> str:
    lines = [
        f"# {report.title}",
        "",
        f"Status: **{report.status.value}**",
        "",
        "## Reproducibility",
        "",
        f"- Benchmark: `{report.metadata.benchmark_version}`",
        f"- Dataset: `{report.metadata.dataset_version}`",
        f"- Annotation: `{report.metadata.annotation_version}`",
        f"- Metrics: `{report.metadata.metric_version}`",
        f"- Git commit: `{report.metadata.git_commit or 'unknown'}`",
        f"- Retrieval mode: `{report.metadata.retrieval_mode or 'fixture/default'}`",
        f"- AI provider/model: `{report.metadata.ai_provider or 'none'}` / `{report.metadata.ai_model or 'none'}`",
        f"- Live mode: `{report.metadata.live}`",
        "",
        "## Results",
        "",
    ]
    for result in report.results:
        lines.extend([f"### {result.component}", "", "| Metric | Value | Count | Status |", "|---|---:|---:|---|"])
        for metric in result.metrics:
            value = "not measured" if metric.value is None else f"{metric.value:.6f}"
            lines.append(f"| `{metric.name}` | {value} | {metric.count} | {metric.status.value} |")
        if result.notes:
            lines.extend(["", *[f"> {note}" for note in result.notes], ""])
    lines.extend(["## Recommendations", "", *[f"- {item}" for item in report.recommendations]])
    return "\n".join(lines).rstrip() + "\n"
