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
        return records

    def get(self, evidence_id: str) -> Evidence | None:
        return self._records.get(evidence_id)

    def get_many(self, evidence_ids: list[str]) -> list[Evidence]:
        return [record for evidence_id in evidence_ids if (record := self.get(evidence_id)) is not None]
