"""Deterministic evidence registry for normalized document paragraphs."""

from __future__ import annotations

from ..models.document import Evidence, EvidenceType, StructuredDocument


class EvidenceRegistry:
    """Build and query evidence without coupling routes to document traversal."""

    def __init__(self) -> None:
        self._records: dict[str, Evidence] = {}

    def build_for_document(self, document: StructuredDocument) -> list[Evidence]:
        records: list[Evidence] = []
        self._records = {}
        for section in document.sections:
            for paragraph in section.paragraphs:
                evidence_id = paragraph.evidence_id or f"ev_{len(records) + 1:04d}"
                paragraph.evidence_id = evidence_id
                evidence = Evidence(
                    id=evidence_id,
                    paper_id=document.paper_id,
                    document_id=document.id,
                    evidence_type=EvidenceType.PARAGRAPH,
                    source_text=paragraph.text,
                    page=paragraph.page,
                    section_id=section.id,
                    paragraph_id=paragraph.id,
                    source_region=paragraph.source_region,
                )
                records.append(evidence)
                self._records[evidence.id] = evidence
        for figure in document.figures:
            evidence_id = f"ev_{len(records) + 1:04d}"
            figure.evidence_ids = [evidence_id]
            evidence = Evidence(
                id=evidence_id,
                paper_id=document.paper_id,
                document_id=document.id,
                evidence_type=EvidenceType.FIGURE_CAPTION,
                source_text=figure.caption or figure.label or "",
                page=figure.page,
                figure_id=figure.id,
                source_region=figure.source_region,
            )
            records.append(evidence)
            self._records[evidence.id] = evidence
        for table in document.tables:
            evidence_id = f"ev_{len(records) + 1:04d}"
            table.evidence_ids = [evidence_id]
            evidence = Evidence(
                id=evidence_id,
                paper_id=document.paper_id,
                document_id=document.id,
                evidence_type=EvidenceType.TABLE,
                source_text=table.raw_text or table.caption or table.label or "",
                page=table.page,
                table_id=table.id,
                source_region=table.source_region,
            )
            records.append(evidence)
            self._records[evidence.id] = evidence
        for equation in document.equations:
            evidence_id = f"ev_{len(records) + 1:04d}"
            equation.evidence_ids = [evidence_id]
            evidence = Evidence(
                id=evidence_id,
                paper_id=document.paper_id,
                document_id=document.id,
                evidence_type=EvidenceType.EQUATION,
                source_text=equation.raw_text,
                page=equation.page,
                equation_id=equation.id,
                source_region=equation.source_region,
            )
            records.append(evidence)
            self._records[evidence.id] = evidence
        for reference in document.references:
            evidence_id = f"ev_{len(records) + 1:04d}"
            reference.evidence_ids = [evidence_id]
            evidence = Evidence(
                id=evidence_id,
                paper_id=document.paper_id,
                document_id=document.id,
                evidence_type=EvidenceType.REFERENCE,
                source_text=reference.raw_text,
                page=None,
                source_region=None,
            )
            records.append(evidence)
            self._records[evidence.id] = evidence
        return records

    def get(self, evidence_id: str) -> Evidence | None:
        return self._records.get(evidence_id)

    def get_many(self, evidence_ids: list[str]) -> list[Evidence]:
        return [record for evidence_id in evidence_ids if (record := self.get(evidence_id)) is not None]
