"""Focused evidence selection for independent extraction stages."""

from __future__ import annotations

from ..evidence.registry import EvidenceRegistry
from ..models.document import Evidence, StructuredDocument
from .classifier import SectionClassification, SectionType


class EvidenceSelector:
    TARGETS: dict[str, set[SectionType]] = {
        "problem": {SectionType.ABSTRACT, SectionType.INTRODUCTION},
        "motivation": {SectionType.ABSTRACT, SectionType.INTRODUCTION, SectionType.BACKGROUND},
        "research_gap": {SectionType.INTRODUCTION, SectionType.RELATED_WORK, SectionType.DISCUSSION},
        "contributions": {SectionType.ABSTRACT, SectionType.INTRODUCTION, SectionType.CONCLUSION},
        "method": {SectionType.METHOD, SectionType.BACKGROUND},
        "equations": {SectionType.METHOD},
        "experiments": {SectionType.EXPERIMENTS},
        "results": {SectionType.RESULTS, SectionType.EXPERIMENTS, SectionType.DISCUSSION},
        "limitations": {SectionType.LIMITATIONS, SectionType.DISCUSSION, SectionType.CONCLUSION},
        "future_work": {SectionType.LIMITATIONS, SectionType.DISCUSSION, SectionType.CONCLUSION},
    }

    def __init__(self, *, max_evidence: int = 80) -> None:
        self.max_evidence = max(1, max_evidence)

    def select(
        self,
        document: StructuredDocument,
        classifications: list[SectionClassification],
        target: str,
    ) -> list[Evidence]:
        allowed = self.TARGETS.get(target, set())
        by_section = {item.section_id: item.classification for item in classifications}
        registry = EvidenceRegistry()
        records = {record.id: record for record in registry.build_for_document(document)}
        selected: list[Evidence] = []
        for section in document.sections:
            if by_section.get(section.id, SectionType.UNKNOWN) not in allowed:
                continue
            for paragraph in section.paragraphs:
                if paragraph.evidence_id and paragraph.evidence_id in records:
                    selected.append(records[paragraph.evidence_id])
                    if len(selected) >= self.max_evidence:
                        return selected
        return selected
