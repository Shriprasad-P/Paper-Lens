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

    title: str
    arxiv_id: str = ""
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    published_at: datetime | None = None
    updated_at: datetime | None = None
    categories: list[str] = Field(default_factory=list)
    source_url: str = ""
    pdf_url: str = ""
    source_type: str = "arxiv"
    canonical_id: str | None = None
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    venue: str | None = None
    publisher_url: str | None = None
    open_access_pdf_url: str | None = None
    resolver_provenance: dict[str, object] = Field(default_factory=dict)
    metadata_raw_hash: str | None = None


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
    last_opened_at: datetime | None = None


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=500)
