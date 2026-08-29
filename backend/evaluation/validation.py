"""Fail-closed validation for benchmark inputs.

Validation is intentionally separate from metric calculation.  A metric can
be mathematically correct while still being invalid evidence if an annotation
references the wrong paper, a duplicate case, or a mutable prediction file.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .provenance import EvaluationDataError, real_corpus_hash, sha256_file
from .schemas import (
    AnnotationStatus,
    BenchmarkManifest,
    BenchmarkPaperAnnotation,
    ChatBenchmarkCase,
    DiscoveryBenchmarkCase,
    RetrievalBenchmarkCase,
    VerificationBenchmarkCase,
)


@dataclass(frozen=True)
class ValidationReport:
    """Structured result suitable for a machine-readable evaluation report."""

    checked: int
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    counts: Mapping[str, int] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return not self.errors

    def raise_if_invalid(self) -> "ValidationReport":
        if self.errors:
            raise EvaluationDataError("; ".join(self.errors))
        return self


def validate_reviewed_cases(cases: Sequence[object]) -> ValidationReport:
    """Require explicit human review before a case can feed publishable metrics."""

    errors: list[str] = []
    counts: Counter[str] = Counter()
    for case in cases:
        def field(name: str, default: object | None = None) -> object | None:
            if isinstance(case, Mapping):
                return case.get(name, default)
            return getattr(case, name, default)

        status = field("annotation_status")
        status_value = getattr(status, "value", status)
        counts[str(status_value or "MISSING")] += 1
        if status_value not in {AnnotationStatus.REVIEWED.value, AnnotationStatus.ADJUDICATED.value}:
            errors.append(f"{value_for_id(case)}: annotation is not human-reviewed")
        reviewer_id = field("reviewer_id")
        reviewed_at = field("reviewed_at")
        if not isinstance(reviewer_id, str) or not reviewer_id.strip() or not reviewed_at:
            errors.append(f"{value_for_id(case)}: reviewer metadata is missing")
        reviewer_notes = field("reviewer_notes", [])
        if not isinstance(reviewer_notes, Sequence) or isinstance(reviewer_notes, (str, bytes)) or not any(str(note).strip() for note in reviewer_notes):
            errors.append(f"{value_for_id(case)}: reviewer notes are missing")
    return ValidationReport(len(cases), tuple(errors), counts=counts)


def require_reviewed_cases(cases: Sequence[object]) -> list[object]:
    """Return cases safe for publishable metrics, or fail closed.

    Metric runners should call this at their input boundary instead of
    interpreting a partially reviewed ledger as a valid denominator.
    """

    report = validate_reviewed_cases(cases)
    report.raise_if_invalid()
    return list(cases)


def validate_frozen_rankings(
    rankings_by_case: Mapping[str, Sequence[str]],
    expected_case_ids: Iterable[str],
) -> ValidationReport:
    """Validate the shape of a frozen ranking artifact before scoring it."""

    expected = {str(case_id) for case_id in expected_case_ids}
    errors: list[str] = []
    actual = set(rankings_by_case)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        errors.append("frozen rankings are missing cases: " + ", ".join(missing))
    if extra:
        errors.append("frozen rankings contain unknown cases: " + ", ".join(extra))
    for case_id, ranking in rankings_by_case.items():
        if not isinstance(ranking, Sequence) or isinstance(ranking, (str, bytes)):
            errors.append(f"{case_id}: frozen ranking must be a sequence")
            continue
        if any(not isinstance(item, str) or not item.strip() for item in ranking):
            errors.append(f"{case_id}: frozen ranking contains an invalid evidence ID")
        if len(set(ranking)) != len(ranking):
            errors.append(f"{case_id}: frozen ranking contains duplicate evidence IDs")
    return ValidationReport(len(rankings_by_case), tuple(errors), counts={"cases": len(rankings_by_case)})


def value_for_id(case: object) -> str:
    """Return a safe case identifier for validation diagnostics."""

    if isinstance(case, Mapping):
        return str(case.get("case_id", "<unknown>"))
    return str(getattr(case, "case_id", "<unknown>"))


def validate_real_corpus_manifest(
    manifest: Mapping[str, object],
    *,
    corpus_root: Path | None = None,
) -> ValidationReport:
    """Fail closed on real-paper snapshot and production-ingestion drift."""

    errors: list[str] = []
    warnings: list[str] = []
    papers = manifest.get("papers") if isinstance(manifest, Mapping) else None
    if not isinstance(papers, list) or not papers:
        return ValidationReport(0, ("real corpus manifest must contain papers",))
    splits = manifest.get("splits", {})
    if not isinstance(splits, Mapping) or not splits.get("dev") or not splits.get("final"):
        errors.append("real corpus requires non-empty paper-separated dev and final splits")
    elif set(splits.get("dev", [])) & set(splits.get("final", [])):
        errors.append("real corpus dev and final splits must be disjoint")
    paper_ids: set[str] = set()
    versions: set[str] = set()
    split_ids: set[str] = set()
    for raw in papers:
        if not isinstance(raw, Mapping):
            errors.append("real corpus paper record must be an object")
            continue
        paper_id = str(raw.get("paper_id", ""))
        versioned = str(raw.get("versioned_identifier", ""))
        paper_ids.add(paper_id)
        if not paper_id or paper_id in split_ids:
            errors.append(f"duplicate or missing paper_id: {paper_id or '<missing>'}")
        split = str(raw.get("split", ""))
        if split not in {"dev", "final"}:
            errors.append(f"{paper_id}: split must be dev or final")
        split_ids.add(paper_id)
        if versioned in versions:
            errors.append(f"duplicate versioned source: {versioned}")
        versions.add(versioned)
        digest = str(raw.get("source_pdf_sha256", ""))
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower()):
            errors.append(f"{paper_id}: source_pdf_sha256 must be SHA-256")
        normalized = str(raw.get("normalized_document_hash", ""))
        if len(normalized) != 64:
            errors.append(f"{paper_id}: normalized_document_hash is missing or malformed")
        if raw.get("ingestion_status") != "COMPLETED":
            errors.append(f"{paper_id}: production ingestion is not COMPLETED")
        if not raw.get("paperlens_source_id") or not raw.get("paperlens_document_id"):
            errors.append(f"{paper_id}: PaperLens source/document IDs are required")
        if int(raw.get("evidence_count", 0) or 0) < 1:
            errors.append(f"{paper_id}: evidence registry is empty")
        if int(raw.get("page_count", 0) or 0) < 1:
            errors.append(f"{paper_id}: page_count must be positive")
        if corpus_root and raw.get("pdf_path"):
            pdf_path = corpus_root / str(raw["pdf_path"])
            if not pdf_path.is_file():
                errors.append(f"{paper_id}: PDF snapshot is missing")
            elif sha256_file(pdf_path) != digest:
                errors.append(f"{paper_id}: PDF snapshot hash drifted")
    listed = {str(value) for values in splits.values() if isinstance(values, list) for value in values}
    if listed != paper_ids:
        errors.append("split lists do not exactly cover the corpus paper IDs")
    # When the canonical exports are present, resolve the durable IDs and every
    # Evidence Registry row rather than trusting string presence in the manifest.
    if corpus_root and str(manifest.get("corpus_kind", "")).startswith("real_"):
        documents_path = corpus_root / "documents.json"
        evidence_path = corpus_root / "evidence.jsonl"
        if not documents_path.is_file():
            errors.append("real corpus documents.json export is missing")
        else:
            try:
                document_rows = json.loads(documents_path.read_text(encoding="utf-8")).get("documents", [])
            except (OSError, json.JSONDecodeError, AttributeError):
                document_rows = []
                errors.append("real corpus documents.json export is malformed")
            by_document = {str(row.get("document_id")): row for row in document_rows if isinstance(row, Mapping)}
            expected_documents = {str(raw.get("paperlens_document_id")): raw for raw in papers if isinstance(raw, Mapping)}
            for document_id, raw in expected_documents.items():
                resolved = by_document.get(document_id)
                if resolved is None:
                    errors.append(f"{raw.get('paper_id')}: document ID does not resolve: {document_id}")
                elif resolved.get("document_hash") != raw.get("normalized_document_hash"):
                    errors.append(f"{raw.get('paper_id')}: resolved document hash differs from manifest")
        if not evidence_path.is_file():
            errors.append("real corpus evidence.jsonl export is missing")
        else:
            evidence_counts: Counter[str] = Counter()
            seen_evidence: set[str] = set()
            try:
                evidence_lines = evidence_path.read_text(encoding="utf-8").splitlines()
                for line in evidence_lines:
                    evidence = json.loads(line)
                    evidence_id = str(evidence.get("id", ""))
                    document_id = str(evidence.get("document_id", ""))
                    if not evidence_id or evidence_id in seen_evidence:
                        errors.append(f"duplicate or missing evidence ID: {evidence_id or '<missing>'}")
                    seen_evidence.add(evidence_id)
                    evidence_counts[document_id] += 1
            except (OSError, json.JSONDecodeError, TypeError, AttributeError):
                errors.append("real corpus evidence.jsonl export is malformed")
                evidence_counts = Counter()
            for raw in papers:
                if isinstance(raw, Mapping):
                    document_id = str(raw.get("paperlens_document_id", ""))
                    if evidence_counts.get(document_id, 0) != int(raw.get("evidence_count", 0) or 0):
                        errors.append(f"{raw.get('paper_id')}: evidence export count differs from manifest")
    expected_hash = real_corpus_hash(manifest)
    if manifest.get("corpus_hash") and manifest.get("corpus_hash") != expected_hash:
        errors.append("corpus_hash does not match immutable corpus identity")
    if manifest.get("status") == "VALIDATED" and (errors or any(raw.get("annotation_status") != "REVIEWED" for raw in papers if isinstance(raw, Mapping))):
        errors.append("validated real corpus cannot contain incomplete or unreviewed records")
    return ValidationReport(len(papers), tuple(errors), tuple(warnings), {"papers": len(papers), "dev": len(splits.get("dev", [])) if isinstance(splits, Mapping) else 0, "final": len(splits.get("final", [])) if isinstance(splits, Mapping) else 0})


# Short alias for callers that use the generic corpus terminology.
validate_corpus_manifest = validate_real_corpus_manifest


def validate_manifest(manifest: BenchmarkManifest) -> ValidationReport:
    errors: list[str] = []
    warnings: list[str] = []
    if not manifest.papers:
        errors.append("manifest must contain at least one paper")
    for paper in manifest.papers:
        if not paper.source_url and not paper.acquisition_url:
            warnings.append(f"{paper.paper_id}: source URL is not recorded")
        if manifest.status.value == "VALIDATED" and not paper.document_hash:
            errors.append(f"{paper.paper_id}: validated corpus requires document_hash")
        if paper.document_hash and len(paper.document_hash) != 64:
            errors.append(f"{paper.paper_id}: document_hash must be a SHA-256 hex digest")
    if manifest.corpus_kind == "identifier_only":
        warnings.append("corpus is identifier-only; no publishable paper-level score may be claimed")
    return ValidationReport(len(manifest.papers), tuple(errors), tuple(warnings), Counter(p.domain for p in manifest.papers))


def validate_paper_annotations(
    manifest: BenchmarkManifest,
    annotations: Sequence[BenchmarkPaperAnnotation],
) -> ValidationReport:
    errors: list[str] = []
    warnings: list[str] = []
    paper_ids = {paper.paper_id for paper in manifest.papers}
    seen: set[str] = set()
    for annotation in annotations:
        if annotation.paper_id not in paper_ids:
            errors.append(f"annotation {annotation.paper_id}: paper does not exist in manifest")
        if annotation.paper_id in seen:
            errors.append(f"duplicate annotation for paper {annotation.paper_id}")
        seen.add(annotation.paper_id)
        if annotation.annotation_status in {AnnotationStatus.REVIEWED, AnnotationStatus.ADJUDICATED}:
            if not annotation.annotator_ids:
                errors.append(f"annotation {annotation.paper_id}: reviewed record has no annotator ID")
            if not annotation.document_id or not annotation.document_hash:
                errors.append(f"annotation {annotation.paper_id}: reviewed record must bind to a document hash")
        elif not annotation.annotator_ids:
            warnings.append(f"annotation {annotation.paper_id}: draft has no human reviewer")
    return ValidationReport(len(annotations), tuple(errors), tuple(warnings), Counter(annotation.annotation_status.value for annotation in annotations))


def validate_retrieval_cases(
    cases: Sequence[RetrievalBenchmarkCase],
    *,
    paper_ids: Iterable[str] | None = None,
    evidence_ids_by_paper: Mapping[str, Iterable[str]] | None = None,
) -> ValidationReport:
    errors: list[str] = []
    seen: set[str] = set()
    known_papers = set(paper_ids or ())
    for case in cases:
        if case.case_id in seen:
            errors.append(f"duplicate retrieval case_id {case.case_id}")
        seen.add(case.case_id)
        if known_papers and case.paper_id not in known_papers:
            errors.append(f"{case.case_id}: unknown paper_id {case.paper_id}")
        if evidence_ids_by_paper is not None:
            allowed = set(evidence_ids_by_paper.get(case.paper_id, ()))
            unknown = sorted(set(case.relevant_evidence_ids) - allowed)
            if unknown:
                errors.append(f"{case.case_id}: unknown evidence IDs {unknown}")
        if case.annotation_status in {AnnotationStatus.REVIEWED, AnnotationStatus.ADJUDICATED}:
            if not case.reviewer_notes:
                errors.append(f"{case.case_id}: reviewed retrieval annotation requires reviewer notes")
            if not case.reviewer_id or case.reviewed_at is None:
                errors.append(f"{case.case_id}: reviewed retrieval annotation requires reviewer metadata")
    return ValidationReport(len(cases), tuple(errors), counts=Counter(case.category for case in cases))


def validate_real_retrieval_annotations(
    cases: Sequence[RetrievalBenchmarkCase],
    *,
    manifest: Mapping[str, object],
    corpus_root: Path,
) -> ValidationReport:
    """Bind reviewed retrieval annotations to the frozen real evidence export."""

    errors: list[str] = []
    papers = [paper for paper in manifest.get("papers", []) if isinstance(paper, Mapping)]
    paper_by_id = {str(paper.get("paper_id")): paper for paper in papers}
    evidence_by_document: dict[str, set[str]] = {}
    evidence_path = corpus_root / "evidence.jsonl"
    try:
        for line in evidence_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            document_id = str(row.get("document_id", ""))
            evidence_id = str(row.get("id", ""))
            if document_id and evidence_id:
                evidence_by_document.setdefault(document_id, set()).add(evidence_id)
    except (OSError, json.JSONDecodeError, TypeError, AttributeError) as exc:
        return ValidationReport(len(cases), ("real corpus evidence export is unreadable",))
    evidence_by_paper = {
        paper_id: evidence_by_document.get(str(paper.get("paperlens_document_id")), set())
        for paper_id, paper in paper_by_id.items()
    }
    report = validate_retrieval_cases(cases, paper_ids=paper_by_id, evidence_ids_by_paper=evidence_by_paper)
    errors.extend(report.errors)
    for case in cases:
        paper = paper_by_id.get(case.paper_id)
        if paper and case.document_id and case.document_id != paper.get("paperlens_document_id"):
            errors.append(f"{case.case_id}: document_id does not match the manifest version")
    return ValidationReport(report.checked, tuple(errors), report.warnings, report.counts)


def validate_verification_cases(
    cases: Sequence[VerificationBenchmarkCase],
    *,
    paper_ids: Iterable[str] | None = None,
    evidence_ids_by_paper: Mapping[str, Iterable[str]] | None = None,
) -> ValidationReport:
    errors: list[str] = []
    seen: set[str] = set()
    known_papers = set(paper_ids or ())
    for case in cases:
        if case.case_id in seen:
            errors.append(f"duplicate verification case_id {case.case_id}")
        seen.add(case.case_id)
        if case.paper_id and known_papers and case.paper_id not in known_papers:
            errors.append(f"{case.case_id}: unknown paper_id {case.paper_id}")
        if evidence_ids_by_paper is not None and case.paper_id:
            allowed = set(evidence_ids_by_paper.get(case.paper_id, ()))
            unknown = sorted(set(case.allowed_evidence_ids) - allowed)
            if unknown:
                errors.append(f"{case.case_id}: unknown evidence IDs {unknown}")
        if case.annotation_status in {AnnotationStatus.REVIEWED, AnnotationStatus.ADJUDICATED}:
            if not case.rationale:
                errors.append(f"{case.case_id}: reviewed verification item requires rationale")
            if not case.reviewer_notes:
                errors.append(f"{case.case_id}: reviewed verification item requires reviewer notes")
            if not case.allowed_evidence_ids and case.gold_status.value != "UNVERIFIED":
                errors.append(f"{case.case_id}: supported/contradictory item requires allowed evidence IDs")
            if not case.reviewer_id or case.reviewed_at is None:
                errors.append(f"{case.case_id}: reviewed verification item requires reviewer metadata")
    return ValidationReport(len(cases), tuple(errors), counts=Counter(case.gold_status.value for case in cases))


def validate_chat_cases(cases: Sequence[ChatBenchmarkCase]) -> ValidationReport:
    seen: set[str] = set()
    errors: list[str] = []
    for case in cases:
        if case.case_id in seen:
            errors.append(f"duplicate chat case_id {case.case_id}")
        seen.add(case.case_id)
        if case.answerable and not case.expected_answer_points:
            errors.append(f"{case.case_id}: answerable case requires expected answer points")
        if not case.answerable and case.required_evidence_ids:
            errors.append(f"{case.case_id}: unanswerable case cannot require evidence")
        if case.annotation_status in {AnnotationStatus.REVIEWED, AnnotationStatus.ADJUDICATED}:
            if not case.reviewer_id or case.reviewed_at is None or not case.reviewer_notes:
                errors.append(f"{case.case_id}: reviewed chat case requires reviewer metadata and notes")
    return ValidationReport(
        len(cases),
        tuple(errors),
        counts=Counter(f"{case.category}:{'answerable' if case.answerable else 'unanswerable'}" for case in cases),
    )


def validate_agent_tasks(cases: Sequence[DiscoveryBenchmarkCase]) -> ValidationReport:
    seen: set[str] = set()
    errors: list[str] = []
    for case in cases:
        if case.case_id in seen:
            errors.append(f"duplicate agent case_id {case.case_id}")
        seen.add(case.case_id)
        if case.split != "SMOKE" and not case.success_criteria:
            errors.append(f"{case.case_id}: bounded task requires success_criteria")
        if case.max_iterations < 1 or case.search_budget < 1:
            errors.append(f"{case.case_id}: budgets must be positive")
        if case.annotation_status in {AnnotationStatus.REVIEWED, AnnotationStatus.ADJUDICATED}:
            if not case.reviewer_id or case.reviewed_at is None or not case.reviewer_notes:
                errors.append(f"{case.case_id}: reviewed agent task requires reviewer metadata and notes")
    return ValidationReport(len(cases), tuple(errors), counts={"tasks": len(cases)})
