"""Minimal local reviewer for the real PaperLens evaluation ledgers.

The reviewer edits one JSONL item at a time and records reviewer identity,
timestamp, notes, and an explicit ``REVIEWED`` state.  It intentionally has no
network, model, or web-application dependency.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .provenance import EvaluationDataError, annotation_file_hashes, combined_annotation_hash, sha256_json
from .schemas import AnnotationStatus, VerificationStatus
from .validation import require_reviewed_cases


KIND_FILES = {
    "retrieval": "retrieval.jsonl",
    "verification": "verification.jsonl",
    "chat": "chat.jsonl",
    "agent": "agent.jsonl",
}

REVIEWED_STATUSES = {AnnotationStatus.REVIEWED.value, AnnotationStatus.ADJUDICATED.value}
VERIFICATION_LABELS = {status.value for status in VerificationStatus}


def load_case(path: Path, case_id: str) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for index, row in enumerate(rows):
        if row.get("case_id") == case_id:
            return rows, index, row
    raise ValueError(f"case not found: {case_id}")


def apply_review(
    path: Path,
    case_id: str,
    *,
    reviewer_id: str,
    notes: str,
    evidence_ids: list[str] | None = None,
    label: str | None = None,
    answerable: bool | None = None,
    numeric_facts: list[str] | None = None,
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    """Apply one explicit human review and atomically rewrite the JSONL ledger."""

    _ensure_annotation_ledger_editable(path)
    rows, index, row = load_case(path, case_id)
    if not reviewer_id.strip():
        raise ValueError("reviewer_id is required")
    if not notes.strip():
        raise ValueError("a reviewer note is required")
    now = reviewed_at or datetime.now(timezone.utc).isoformat()
    try:
        timestamp = datetime.fromisoformat(now.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("reviewed_at must be an ISO-8601 timestamp") from exc
    if timestamp.tzinfo is None:
        raise ValueError("reviewed_at must include a timezone")
    row["annotation_status"] = "REVIEWED"
    row["reviewer_id"] = reviewer_id.strip()
    row["reviewed_at"] = now
    existing_notes = row.get("reviewer_notes", [])
    if isinstance(existing_notes, str):
        existing_notes = [existing_notes]
    if not isinstance(existing_notes, list):
        existing_notes = []
    row["reviewer_notes"] = [*existing_notes, notes.strip()]
    if evidence_ids is not None:
        if "relevant_evidence_ids" in row:
            row["relevant_evidence_ids"] = list(dict.fromkeys(evidence_ids))
        if "required_evidence_ids" in row:
            row["required_evidence_ids"] = list(dict.fromkeys(evidence_ids))
        if "allowed_evidence_ids" in row:
            row["allowed_evidence_ids"] = list(dict.fromkeys(evidence_ids))
    if label is not None:
        if "gold_status" in row:
            normalized_label = label.strip().upper()
            if normalized_label not in VERIFICATION_LABELS:
                raise ValueError("label must be one of: " + ", ".join(sorted(VERIFICATION_LABELS)))
            row["gold_status"] = normalized_label
        else:
            row["category"] = label.strip()
    if answerable is not None and "answerable" in row:
        row["answerable"] = answerable
        if not answerable:
            # An unanswerable item must not retain stale gold answer/evidence
            # requirements from its programmatic draft.
            row["expected_answer_points"] = []
            row["relevant_evidence_ids"] = []
            row["required_evidence_ids"] = []
    if numeric_facts is not None and "numeric_facts" in row:
        row["numeric_facts"] = list(dict.fromkeys(item.strip() for item in numeric_facts if item.strip()))
    rows[index] = row
    temporary = path.with_name(path.name + ".reviewing")
    temporary.write_text("".join(json.dumps(item, separators=(",", ":"), ensure_ascii=False) + "\n" for item in rows), encoding="utf-8")
    os.replace(temporary, path)
    return row


def _ensure_annotation_ledger_editable(path: Path) -> None:
    """Refuse edits after a reviewed manifest has been explicitly frozen."""

    manifest_path = path.parent / "manifest.json"
    if not manifest_path.is_file():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationDataError("Cannot read annotation manifest before review") from exc
    freeze = manifest.get("freeze") if isinstance(manifest, dict) else None
    if manifest.get("status") == "VALIDATED" or (isinstance(freeze, dict) and freeze.get("status") == "FROZEN"):
        raise EvaluationDataError("Annotation manifest is frozen; create a new benchmark version before editing")


def _evidence_context(evidence_path: Path, case: dict[str, Any], *, radius: int = 2) -> list[dict[str, Any]]:
    wanted = set(case.get("relevant_evidence_ids", [])) | set(case.get("allowed_evidence_ids", [])) | set(case.get("required_evidence_ids", []))
    evidence = [json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    selected_indices = [index for index, item in enumerate(evidence) if item.get("id") in wanted]
    if not selected_indices:
        return [item for item in evidence if item.get("document_id") == case.get("document_id")][:5]
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index in selected_indices:
        target = evidence[index]
        section_id = target.get("section_id")
        document_id = target.get("document_id")
        lower = max(0, index - radius)
        upper = min(len(evidence), index + radius + 1)
        for neighbor in evidence[lower:upper]:
            if neighbor.get("document_id") != document_id:
                continue
            if section_id and neighbor.get("section_id") != section_id:
                continue
            evidence_id = str(neighbor.get("id", ""))
            if evidence_id and evidence_id not in seen:
                seen.add(evidence_id)
                selected.append(neighbor)
    return selected


def interactive_review(annotation_dir: Path, kind: str, case_id: str, reviewer_id: str) -> dict[str, Any] | None:
    path = annotation_dir / KIND_FILES[kind]
    _, _, case = load_case(path, case_id)
    print(json.dumps(case, indent=2, ensure_ascii=False))
    evidence_path = annotation_dir.parent / "corpus" / "evidence.jsonl"
    if evidence_path.is_file():
        for item in _evidence_context(evidence_path, case):
            print(f"\n[{item.get('id')}] page={item.get('page')} type={item.get('evidence_type')}\n{item.get('source_text', '')[:3000]}")
    action = input("Action [r=review, s=skip, q=quit]: ").strip().lower()
    if action == "q":
        return None
    if action != "r":
        return case
    raw_ids = input("Gold evidence IDs (comma-separated; blank keeps current): ").strip()
    notes = input("Reviewer note (required): ").strip()
    label = None
    if kind == "verification":
        label = input("Gold label [SUPPORTED/PARTIALLY_SUPPORTED/UNSUPPORTED/CONTRADICTORY/UNVERIFIED] (blank keeps current): ").strip() or None
    answerable = None
    if kind == "chat":
        raw_answerable = input("Answerable from this paper? [y/n/blank keeps current]: ").strip().lower()
        answerable = {"y": True, "n": False}.get(raw_answerable)
    numeric_facts = None
    if kind in {"verification", "chat"}:
        raw_numbers = input("Canonical numeric facts (comma-separated; blank keeps current): ").strip()
        numeric_facts = [item.strip() for item in raw_numbers.split(",") if item.strip()] if raw_numbers else None
    ids = [item.strip() for item in raw_ids.split(",") if item.strip()] if raw_ids else None
    return apply_review(path, case_id, reviewer_id=reviewer_id, notes=notes, evidence_ids=ids, label=label, answerable=answerable, numeric_facts=numeric_facts)


def refresh_annotation_manifest(
    annotation_dir: Path,
    *,
    corpus_hash: str | None = None,
    freeze: bool = False,
) -> dict[str, Any]:
    """Refresh review counts/hashes, optionally creating an explicit freeze.

    This is deliberately a local operation.  It never infers review from file
    presence: every case must carry a reviewed state, reviewer ID, timestamp,
    and non-empty reviewer note before ``freeze=True`` succeeds.
    """

    manifest_path = annotation_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationDataError("Cannot read annotation manifest") from exc
    hashes = annotation_file_hashes(annotation_dir)
    case_counts: dict[str, int] = {}
    reviewed_counts: dict[str, int] = {}
    statuses: list[str] = []
    reviewer_ids: set[str] = set()
    reviewed_timestamps: list[str] = []
    all_rows: list[dict[str, Any]] = []
    for kind, filename in KIND_FILES.items():
        path = annotation_dir / filename
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        all_rows.extend(rows)
        case_counts[kind] = len(rows)
        reviewed = 0
        for row in rows:
            status = str(row.get("annotation_status", "DRAFT"))
            statuses.append(status)
            if status in REVIEWED_STATUSES:
                reviewed += 1
                reviewer = str(row.get("reviewer_id", "")).strip()
                if reviewer:
                    reviewer_ids.add(reviewer)
                if row.get("reviewed_at"):
                    reviewed_timestamps.append(str(row["reviewed_at"]))
        reviewed_counts[kind] = reviewed
    all_reviewed = bool(statuses) and all(status in REVIEWED_STATUSES for status in statuses)
    if freeze and not all_reviewed:
        pending = sum(1 for status in statuses if status not in REVIEWED_STATUSES)
        raise EvaluationDataError(f"Cannot freeze annotations; {pending} case(s) remain unreviewed")
    if freeze:
        try:
            require_reviewed_cases(all_rows)
        except ValueError as exc:
            raise EvaluationDataError("Cannot freeze annotations; reviewer metadata/notes are incomplete") from exc
    manifest["annotation_hashes"] = hashes
    manifest["annotation_hash"] = combined_annotation_hash(annotation_dir)
    manifest["benchmark_hash"] = sha256_json(
        {
            "benchmark_version": manifest.get("benchmark_version"),
            "corpus_hash": manifest.get("corpus_hash"),
            "annotation_hash": manifest["annotation_hash"],
            "annotation_hashes": hashes,
            "schema_version": manifest.get("schema_version", "1.0"),
        }
    )
    manifest["counts"] = case_counts
    manifest["reviewed_counts"] = reviewed_counts
    manifest["human_reviewed"] = all_reviewed
    manifest["reviewer_count"] = len(reviewer_ids)
    manifest["reviewer_ids"] = sorted(reviewer_ids)
    manifest["review_type"] = "single-reviewer" if len(reviewer_ids) == 1 else "multi-reviewer" if reviewer_ids else "unassigned"
    manifest["review_status"] = "REVIEWED" if all_reviewed else "IN_PROGRESS" if any(status in REVIEWED_STATUSES for status in statuses) else "NOT_REVIEWED"
    if corpus_hash:
        manifest["corpus_hash"] = corpus_hash
    if freeze:
        frozen_at = datetime.now(timezone.utc).isoformat()
        manifest["status"] = "VALIDATED"
        manifest["frozen_at"] = frozen_at
        manifest["freeze"] = {"status": "FROZEN", "frozen_at": frozen_at, "annotation_hash": manifest["annotation_hash"]}
    else:
        manifest["status"] = "DRAFT"
    temporary = manifest_path.with_name(manifest_path.name + ".reviewing")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, manifest_path)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=sorted(KIND_FILES))
    parser.add_argument("case_id")
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument("--annotations", type=Path, default=Path("backend/evaluation/datasets/real_annotations"))
    parser.add_argument("--refresh-manifest", action="store_true", help="Refresh review counts and annotation hashes after the review.")
    parser.add_argument("--freeze", action="store_true", help="Freeze the manifest; requires every case to be reviewed.")
    parser.add_argument("--show-only", action="store_true", help="Display the case/evidence without changing the ledger.")
    args = parser.parse_args()
    if args.show_only:
        path = args.annotations / KIND_FILES[args.kind]
        _, _, case = load_case(path, args.case_id)
        print(json.dumps(case, indent=2, ensure_ascii=False))
        evidence_path = args.annotations.parent / "corpus" / "evidence.jsonl"
        if evidence_path.is_file():
            for item in _evidence_context(evidence_path, case):
                print(f"\n[{item.get('id')}] page={item.get('page')} type={item.get('evidence_type')}\n{item.get('source_text', '')[:3000]}")
        return
    reviewed = interactive_review(args.annotations, args.kind, args.case_id, args.reviewer_id)
    if reviewed is not None and (args.refresh_manifest or args.freeze):
        refresh_annotation_manifest(args.annotations, corpus_hash=None, freeze=args.freeze)


if __name__ == "__main__":  # pragma: no cover
    main()
