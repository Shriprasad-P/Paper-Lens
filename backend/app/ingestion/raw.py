"""Parser-neutral raw representation consumed by the document normalizer."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ..models.document import PaperEquation, PaperFigure, PaperReference, PaperTable, SourceRegion


class RawParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    page: int | None = None
    source_region: SourceRegion | None = None


class RawSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    level: int = Field(ge=1)
    order: int = Field(ge=0)
    page_start: int | None = None
    page_end: int | None = None
    paragraphs: list[RawParagraph] = Field(default_factory=list)


class ParsedPaper(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sections: list[RawSection] = Field(default_factory=list)
    page_count: int | None = None
    parser_name: str
    parser_version: str | None = None
    figures: list[PaperFigure] = Field(default_factory=list)
    tables: list[PaperTable] = Field(default_factory=list)
    equations: list[PaperEquation] = Field(default_factory=list)
    references: list[PaperReference] = Field(default_factory=list)

    @classmethod
    def from_legacy_sections(cls, sections: list[object], *, parser_name: str) -> "ParsedPaper":
        """Wrap Phase 2 parser output while preserving a stable normalizer boundary."""

        raw_sections = [
            RawSection(
                title=getattr(section, "title"),
                level=1,
                order=getattr(section, "order", index),
                paragraphs=[RawParagraph(text=getattr(section, "text"))],
            )
            for index, section in enumerate(sections)
        ]
        return cls(sections=raw_sections, parser_name=parser_name)
