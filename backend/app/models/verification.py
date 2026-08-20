"""Typed claim-verification models kept separate from extracted PaperIR."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class VerificationStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTORY = "CONTRADICTORY"
    UNVERIFIED = "UNVERIFIED"


class VerificationOutput(BaseModel):
    """The only provider-facing semantic output accepted by the verifier."""

    model_config = ConfigDict(extra="forbid")

    status: VerificationStatus
    rationale: str = Field(min_length=1, max_length=600)
    confidence: float | None = Field(default=None, ge=0, le=1)


class VerificationResult(BaseModel):
    """One auditable verification result for one stable semantic claim."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    status: VerificationStatus
    evidence_ids: list[str] = Field(default_factory=list)
    rationale: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    verified_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    verifier_provider: str | None = None
    verifier_model: str | None = None
    prompt_version: str
    schema_version: str
    document_hash: str | None = None
    claim_hash: str
    evidence_hash: str
    cache_key: str


class VerificationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_claims: int = Field(ge=0)
    supported: int = Field(ge=0)
    partially_supported: int = Field(ge=0)
    unsupported: int = Field(ge=0)
    contradictory: int = Field(ge=0)
    unverified: int = Field(ge=0)
    verified_at: datetime | None = None


class PaperVerificationResponse(BaseModel):
    """Current verification state for one persisted PaperIR."""

    model_config = ConfigDict(extra="forbid")

    paper_id: str
    document_id: str | None = None
    document_hash: str | None = None
    available: bool = False
    error: str | None = None
    summary: VerificationSummary
    results: list[VerificationResult] = Field(default_factory=list)
