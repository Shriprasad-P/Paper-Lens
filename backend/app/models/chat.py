"""Typed models for single-paper, evidence-grounded chat."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ChatRole(str, Enum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"


class ChatMessageStatus(str, Enum):
    ANSWERED = "ANSWERED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    GENERATION_FAILED = "GENERATION_FAILED"


class ChatCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    page: int | None = None
    section_id: str | None = None


class ChatAnswerClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)


class ChatAnswerOutput(BaseModel):
    """Provider schema; answer/citation fields keep compatibility with simple fixtures."""

    model_config = ConfigDict(extra="forbid")

    claims: list[ChatAnswerClaim] = Field(default_factory=list)
    summary: str | None = None
    sufficient_evidence: bool = False
    answer: str | None = None
    citation_ids: list[str] = Field(default_factory=list)


class RetrievedEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    paper_id: str | None = None
    document_id: str | None = None
    score: float = Field(ge=0)
    section_id: str | None = None
    page: int | None = None
    evidence_type: str = "PARAGRAPH"
    source_text: str
    retrieval_method: str = "bm25"
    rank: int = Field(ge=1)


class ChatSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    paper_id: str
    document_id: str
    document_hash: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    session_id: str
    role: ChatRole
    content: str
    status: ChatMessageStatus | None = None
    citations: list[ChatCitation] = Field(default_factory=list)
    sufficient_evidence: bool | None = None
    document_id: str
    retrieval_query: str | None = None
    retrieved_evidence_ids: list[str] = Field(default_factory=list)
    retrieval_scores: dict[str, float] = Field(default_factory=dict)
    retriever_version: str | None = None
    provider: str | None = None
    model: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChatSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session: ChatSession
    messages: list[ChatMessage] = Field(default_factory=list)


class ChatSessionCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    paper_id: str
    document_id: str
    document_hash: str | None = None
    created_at: datetime
    updated_at: datetime


class ChatQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4_000)


class ChatMessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: ChatMessage


class ChatAnswerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str
    answer: str
    status: ChatMessageStatus
    sufficient_evidence: bool
    citations: list[ChatCitation] = Field(default_factory=list)


INSUFFICIENT_EVIDENCE_MESSAGE = "The paper does not contain enough retrieved evidence to answer this reliably."
GENERATION_FAILURE_MESSAGE = "The grounded answer could not be generated. Please try again."
