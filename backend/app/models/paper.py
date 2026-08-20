"""Normalized paper and ingestion request models.

These models cover the ingestion boundary. Structured documents and semantic
PaperIR components are defined in ``document.py`` so their provenance contracts
remain together.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PaperMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arxiv_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    published_at: datetime | None = None
    updated_at: datetime | None = None
    categories: list[str] = Field(default_factory=list)
    source_url: str
    pdf_url: str


class ParsedSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    order: int = Field(ge=0)
    text: str


class IngestedPaper(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    status: str
    metadata: PaperMetadata
    sections: list[ParsedSection] = Field(default_factory=list)


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=500)
