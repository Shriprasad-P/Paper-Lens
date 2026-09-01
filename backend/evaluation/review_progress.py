"""Read-only Phase 15D human-review progress report.

The report counts only explicit ``REVIEWED``/``ADJUDICATED`` decisions and
explicit ``EXCLUDED`` decisions.  It never promotes a draft row and never
changes an annotation ledger.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .provenance import real_corpus_hash
from .review_cli import EXCLUDED_STATUS, KIND_FILES, REVIEWED_STATUSES
from .validation import validate_real_corpus_manifest


RESOLVED_STATUSES = REVIEWED_STATUSES | {EXCLUDED_STATUS}
CHECKPOINTS = (25, 50, 75, 100)


def summarize_review_progress(
    annotation_dir: Path,
    *,
    corpus_dir: Path | None = None,
    baseline_commit: str | None = None,
) -> dict[str, Any]:
    """Summarize review progress without mutating any source files."""

    suites: dict[str, dict[str, Any]] = {}
    total = 0
    resolved = 0
    reviewer_ids: set[str] = set()
    for suite, filename in KIND_FILES.items():
        rows = [json.loads(line) for line in (annotation_dir / filename).read_text(encoding="utf-8").splitlines() if line.strip()]
        counts: dict[str, int] = {}
        for row in rows:
            status = str(row.get("annotation_status", "DRAFT"))
            counts[status] = counts.get(status, 0) + 1
            reviewer = str(row.get("reviewer_id", "")).strip()
            if reviewer:
                reviewer_ids.add(reviewer)
        suite_resolved = sum(counts.get(status, 0) for status in RESOLVED_STATUSES)
        total += len(rows)
        resolved += suite_resolved
        suites[suite] = {
            "total": len(rows),
            "reviewed": sum(counts.get(status, 0) for status in REVIEWED_STATUSES),
            "excluded": counts.get(EXCLUDED_STATUS, 0),
            "remaining_draft": len(rows) - suite_resolved,
            "status_counts": counts,
        }
    change_log = annotation_dir / "change_log.jsonl"
    changes: list[dict[str, Any]] = []
    if change_log.is_file():
        changes = [json.loads(line) for line in change_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    evidence_fields = {"relevant_evidence_ids", "secondary_evidence_ids", "required_evidence_ids", "allowed_evidence_ids"}
    label_fields = {"gold_status", "category", "answerable"}
    evidence_changes = sum(1 for record in changes for item in record.get("changes", []) if item.get("field") in evidence_fields)
    label_changes = sum(1 for record in changes for item in record.get("changes", []) if item.get("field") in label_fields)
    progress = (100.0 * resolved / total) if total else 0.0
    checkpoints = {
        str(checkpoint): {
            "status": "REACHED" if progress >= checkpoint else "PENDING",
            "required_resolved": (total * checkpoint + 99) // 100,
            "resolved_at_generation": progress >= checkpoint,
        }
        for checkpoint in CHECKPOINTS
    }
    corpus_result: dict[str, Any] = {"status": "NOT_CHECKED"}
    if corpus_dir:
        manifest_path = corpus_dir / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            validation = validate_real_corpus_manifest(manifest, corpus_root=corpus_dir)
            corpus_result = {
                "status": "PASS" if validation.valid else "DRIFT_OR_INVALID",
                "corpus_hash": real_corpus_hash(manifest),
                "checked": validation.checked,
                "errors": list(validation.errors),
            }
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            corpus_result = {"status": "DRIFT_OR_INVALID", "errors": [str(exc)]}
    return {
        "schema_version": "1.0",
        "phase": "15D",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "COMPLETE" if total and resolved == total else "IN_PROGRESS" if resolved else "NOT_STARTED",
        "baseline_commit": baseline_commit or _git_commit(),
        "reviewer_count": len(reviewer_ids),
        "reviewer_ids": sorted(reviewer_ids),
        "review_type": "single-reviewer" if len(reviewer_ids) == 1 else "multi-reviewer" if reviewer_ids else "unassigned",
        "total_cases": total,
        "resolved_cases": resolved,
        "remaining_draft": total - resolved,
        "progress_percent": progress,
        "suites": suites,
        "checkpoints": checkpoints,
        "annotation_changes": {
            "change_records": len(changes),
            "field_changes": sum(len(record.get("changes", [])) for record in changes),
            "evidence_bindings_changed": evidence_changes,
            "label_changes": label_changes,
        },
        "corpus_drift": corpus_result,
        "notes": [
            "Progress is an annotation-workflow report, not a benchmark output.",
            "Provider-backed runs and FINAL evaluation are intentionally not started in Phase 15D.",
        ],
    }


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, timeout=2).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# PaperLens Phase 15D Review Progress",
        "",
        f"Status: **{summary['status']}** ({summary['progress_percent']:.1f}% resolved)",
        "",
        f"Resolved: {summary['resolved_cases']}/{summary['total_cases']}  ",
        f"Remaining DRAFT: {summary['remaining_draft']}  ",
        f"Reviewer count: {summary['reviewer_count']} ({summary['review_type']})",
        "",
        "| Suite | Reviewed | Excluded | Remaining DRAFT |",
        "|---|---:|---:|---:|",
    ]
    for suite, values in summary["suites"].items():
        lines.append(f"| {suite} | {values['reviewed']} | {values['excluded']} | {values['remaining_draft']} |")
    lines.extend(["", "## Checkpoints", ""])
    for checkpoint, values in summary["checkpoints"].items():
        lines.append(f"- {checkpoint}%: **{values['status']}** ({values['required_resolved']} resolved required)")
    lines.extend(["", f"Corpus drift validation: **{summary['corpus_drift']['status']}**", ""])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, default=Path("backend/evaluation/datasets/real_annotations"))
    parser.add_argument("--corpus", type=Path, default=Path("backend/evaluation/datasets/corpus"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    summary = summarize_review_progress(args.annotations, corpus_dir=args.corpus)
    encoded = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown(summary), encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
