"""Convert parser-neutral source data into stable StructuredDocument models."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from ..ingestion.raw import ParsedPaper
from ..models.document import (
    PaperParagraph,
    PaperSection,
    StructuredDocument,
)
from ..models.paper import PaperMetadata


class DocumentNormalizer:
    """Normalize source structure without interpreting or rewriting it."""

    def normalize(
        self,
        parsed_paper: ParsedPaper,
        *,
        paper_id: str,
        metadata: PaperMetadata,
        source_hash: str | None = None,
    ) -> StructuredDocument:
        source_hash = source_hash or _hash_parsed_paper(parsed_paper)
        document_id = f"doc_{_digest(f'{paper_id}:{source_hash}')[:16]}"
        sections: list[PaperSection] = []
        paragraph_number = 0
        previous_by_level: dict[int, str] = {}

        for section_number, raw_section in enumerate(parsed_paper.sections, start=1):
            section_id = f"sec_{section_number:03d}"
            parent_id = _parent_id(raw_section.level, previous_by_level)
            previous_by_level[raw_section.level] = section_id
            for level in list(previous_by_level):
                if level > raw_section.level:
                    previous_by_level.pop(level)

            paragraphs: list[PaperParagraph] = []
            for paragraph_order, raw_paragraph in enumerate(raw_section.paragraphs):
                paragraph_number += 1
                paragraph_id = f"para_{paragraph_number:04d}"
                evidence_id = f"ev_{paragraph_number:04d}"
                paragraphs.append(
                    PaperParagraph(
                        id=paragraph_id,
                        section_id=section_id,
                        order=paragraph_order,
                        text=raw_paragraph.text,
                        page=raw_paragraph.page,
                        source_region=raw_paragraph.source_region,
                        content_hash=_digest(raw_paragraph.text),
                        evidence_id=evidence_id,
                    )
                )

            page_values = [paragraph.page for paragraph in paragraphs if paragraph.page is not None]
            sections.append(
                PaperSection(
                    id=section_id,
                    title=raw_section.title,
                    level=raw_section.level,
                    order=section_number - 1,
                    parent_id=parent_id,
                    page_start=raw_section.page_start or (min(page_values) if page_values else None),
                    page_end=raw_section.page_end or (max(page_values) if page_values else None),
                    paragraphs=paragraphs,
                )
            )

        document = StructuredDocument(
            id=document_id,
            paper_id=paper_id,
            metadata=metadata,
            sections=sections,
            page_count=parsed_paper.page_count,
            parser_name=parsed_paper.parser_name,
            parser_version=parsed_paper.parser_version,
            source_hash=source_hash,
            created_at=datetime.now(timezone.utc),
        )
        canonical = document.model_dump(mode="json", exclude={"document_hash", "created_at"})
        document.document_hash = _digest(json.dumps(canonical, sort_keys=True, separators=(",", ":")))
        return document


def _parent_id(level: int, previous_by_level: dict[int, str]) -> str | None:
    if level <= 1:
        return None
    for candidate in range(level - 1, 0, -1):
        if candidate in previous_by_level:
            return previous_by_level[candidate]
    return None


def _hash_parsed_paper(parsed_paper: ParsedPaper) -> str:
    payload = parsed_paper.model_dump(mode="json")
    return _digest(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
