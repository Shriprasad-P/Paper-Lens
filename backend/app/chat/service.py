"""Orchestration for persisted, evidence-grounded paper chat."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from ..ai.provider import AIProvider, AIProviderError
from ..core.config import Settings
from ..db.database import SQLDatabase
from ..models.chat import (
    GENERATION_FAILURE_MESSAGE,
    INSUFFICIENT_EVIDENCE_MESSAGE,
    ChatAnswerClaim,
    ChatAnswerOutput,
    ChatCitation,
    ChatMessage,
    ChatMessageStatus,
    ChatRole,
    ChatSession,
    RetrievedEvidence,
)
from ..models.document import Evidence
from .retrieval import BM25EvidenceRetriever, EvidenceRetriever, normalize_query
from ..retrieval.embeddings import create_embedding_provider
from ..retrieval.hybrid import HybridEvidenceRetriever, SemanticEvidenceRetriever
from ..retrieval import RetrievalMethod


class PaperChatError(Exception):
    """Expected chat boundary failure."""


class ChatSessionNotFound(PaperChatError):
    pass


class ChatDocumentChanged(PaperChatError):
    pass


class ChatGenerationUnavailable(PaperChatError):
    pass


class PaperChatService:
    PROMPT_VERSION = "v1"
    SCHEMA_VERSION = "v1"
    INSUFFICIENT_THRESHOLD = 0.1

    def __init__(
        self,
        database: SQLDatabase,
        provider: AIProvider,
        *,
        settings: Settings | None = None,
        retriever: EvidenceRetriever | None = None,
        prompt_dir: Path | None = None,
    ) -> None:
        self.database = database
        self.provider = provider
        self.settings = settings or Settings.from_env()
        if retriever is not None:
            self.retriever = retriever
        elif self.settings.hybrid_retrieval_enabled or self.settings.retrieval_mode == RetrievalMethod.HYBRID.value:
            semantic = SemanticEvidenceRetriever(
                database,
                create_embedding_provider(self.settings),
                top_k=self.settings.semantic_retrieval_top_k,
            )
            self.retriever = HybridEvidenceRetriever(database, semantic)
        elif self.settings.retrieval_mode == RetrievalMethod.SEMANTIC.value:
            self.retriever = SemanticEvidenceRetriever(
                database,
                create_embedding_provider(self.settings),
                top_k=self.settings.semantic_retrieval_top_k,
            )
        else:
            self.retriever = BM25EvidenceRetriever(database)
        self.prompt_dir = prompt_dir or Path(__file__).parents[1] / "prompts"

    def create_session(self, paper_id: str, owner_id: str = "user_legacy_local") -> ChatSession:
        paper = self.database.get_by_id(paper_id, owner_id)
        document = self.database.get_document(paper_id, owner_id)
        if paper is None or document is None:
            raise ChatSessionNotFound("Paper or structured document not found.")
        now = datetime.now(timezone.utc)
        session = ChatSession(
            id=f"chat_{uuid4().hex}",
            paper_id=paper_id,
            document_id=document.id,
            document_hash=document.document_hash,
            created_at=now,
            updated_at=now,
        )
        return self.database.create_chat_session(session, owner_id)

    def get_session(self, paper_id: str, session_id: str, owner_id: str = "user_legacy_local") -> tuple[ChatSession, list[ChatMessage]]:
        session = self.database.get_chat_session(session_id, owner_id)
        if session is None or session.paper_id != paper_id:
            raise ChatSessionNotFound("Chat session not found for this paper.")
        return session, self.database.get_chat_messages(session_id, owner_id)

    async def answer(self, paper_id: str, session_id: str, question: str, owner_id: str = "user_legacy_local") -> ChatMessage:
        session, history = self.get_session(paper_id, session_id, owner_id)
        question = question.strip()
        if not question:
            raise PaperChatError("Question must not be empty.")
        if len(question) > self.settings.chat_max_question_chars:
            raise PaperChatError("Question is too long.")
        document = self.database.get_document(paper_id, owner_id)
        if document is None:
            raise ChatSessionNotFound("Structured document not found.")
        if session.document_id != document.id or session.document_hash != document.document_hash:
            raise ChatDocumentChanged(
                "This chat is bound to an older document version. Start a new chat for the current paper."
            )

        retrieval_query = self._resolve_query(question, history)
        if hasattr(self.retriever, "retrieve_async"):
            try:
                retrieved = await self.retriever.retrieve_async(
                    paper_id,
                    retrieval_query,
                    limit=self.settings.chat_retrieval_top_k,
                    owner_id=owner_id,
                )
            except AIProviderError:
                # Semantic credentials are optional; lexical retrieval remains the safe baseline.
                retrieved = BM25EvidenceRetriever(self.database).retrieve(
                    paper_id,
                    retrieval_query,
                    limit=self.settings.chat_retrieval_top_k,
                    owner_id=owner_id,
                )
        else:
            try:
                retrieved = self.retriever.retrieve(
                    paper_id,
                    retrieval_query,
                    limit=self.settings.chat_retrieval_top_k,
                    owner_id=owner_id,
                )
            except TypeError:
                retrieved = self.retriever.retrieve(paper_id, retrieval_query, limit=self.settings.chat_retrieval_top_k)
        user_message = self._message(
            session,
            ChatRole.USER,
            question,
            status=None,
            sufficient_evidence=None,
            retrieval_query=retrieval_query,
            retrieved_evidence_ids=[item.evidence_id for item in retrieved],
            retrieval_scores={item.evidence_id: item.score for item in retrieved},
        )
        self.database.save_chat_message(user_message, owner_id)

        context = _assemble_context(retrieved, self.settings.chat_max_context_chars)
        # RRF scores are rank-fusion weights (roughly 1 / 60), not cosine
        # relevance scores.  Applying the semantic/lexical threshold to them
        # would make every HYBRID chat turn abstain before local generation.
        # Ranking is unchanged; the evidence-grounded output validator still
        # decides whether the model can answer and which citations are valid.
        score_is_rrf = bool(retrieved and retrieved[0].retrieval_method == "hybrid-rrf-v1")
        relevance_ok = bool(retrieved) and (score_is_rrf or retrieved[0].score >= max(self.settings.chat_min_relevance, self.INSUFFICIENT_THRESHOLD))
        if not relevance_ok or not context:
            assistant = self._message(
                session,
                ChatRole.ASSISTANT,
                INSUFFICIENT_EVIDENCE_MESSAGE,
                status=ChatMessageStatus.INSUFFICIENT_EVIDENCE,
                sufficient_evidence=False,
                retrieval_query=retrieval_query,
                retrieved_evidence_ids=[item.evidence_id for item in retrieved],
                retrieval_scores={item.evidence_id: item.score for item in retrieved},
            )
            self.database.save_chat_message(assistant, owner_id)
            return assistant

        try:
            output = await self.provider.generate_structured(
                self._prompt(question, history, context),
                ChatAnswerOutput,
            )
            if not output.sufficient_evidence:
                assistant = self._message(
                    session,
                    ChatRole.ASSISTANT,
                    INSUFFICIENT_EVIDENCE_MESSAGE,
                    status=ChatMessageStatus.INSUFFICIENT_EVIDENCE,
                    sufficient_evidence=False,
                    retrieval_query=retrieval_query,
                    retrieved_evidence_ids=[item.evidence_id for item in retrieved],
                    retrieval_scores={item.evidence_id: item.score for item in retrieved},
                )
                self.database.save_chat_message(assistant, owner_id)
                return assistant
            answer, citations = self._validate_output(output, retrieved, paper_id, document.id, owner_id)
        except (AIProviderError, ValidationError, ValueError, TypeError) as exc:
            failure = self._message(
                session,
                ChatRole.ASSISTANT,
                GENERATION_FAILURE_MESSAGE,
                status=ChatMessageStatus.GENERATION_FAILED,
                sufficient_evidence=False,
                retrieval_query=retrieval_query,
                retrieved_evidence_ids=[item.evidence_id for item in retrieved],
                retrieval_scores={item.evidence_id: item.score for item in retrieved},
            )
            self.database.save_chat_message(failure, owner_id)
            raise ChatGenerationUnavailable(_safe_error(exc)) from exc

        assistant = self._message(
            session,
            ChatRole.ASSISTANT,
            answer,
            status=ChatMessageStatus.ANSWERED,
            citations=citations,
            sufficient_evidence=True,
            retrieval_query=retrieval_query,
            retrieved_evidence_ids=[item.evidence_id for item in retrieved],
            retrieval_scores={item.evidence_id: item.score for item in retrieved},
        )
        self.database.save_chat_message(assistant, owner_id)
        return assistant

    def _resolve_query(self, question: str, history: list[ChatMessage]) -> str:
        normalized = normalize_query(question)
        if not history or not _needs_history_context(question):
            return normalized
        previous_user = next((item.content for item in reversed(history) if item.role is ChatRole.USER), "")
        previous_answer = next((item.content for item in reversed(history) if item.role is ChatRole.ASSISTANT), "")
        # History is only a reference-resolution hint; it is never placed in the evidence corpus.
        return normalize_query(f"{question} {previous_user} {previous_answer[:240]}")

    def _prompt(self, question: str, history: list[ChatMessage], context: str) -> str:
        instructions = (self.prompt_dir / "paper_chat.md").read_text(encoding="utf-8")
        history_payload = [
            {"role": item.role.value.lower(), "content": item.content}
            for item in history[-6:]
        ]
        return (
            f"{instructions}\n\nCONVERSATION HISTORY (context only; not evidence)\n"
            f"{json.dumps(history_payload, ensure_ascii=False)}\n\nQUESTION\n{question}\n\n"
            f"SUPPLIED SOURCE EVIDENCE\n{context}\n\n"
            "Return only JSON matching the requested schema. Every factual claim must cite supplied evidence IDs."
        )

    def _validate_output(
        self,
        output: ChatAnswerOutput,
        retrieved: list[RetrievedEvidence],
        paper_id: str,
        document_id: str,
        owner_id: str,
    ) -> tuple[str, list[ChatCitation]]:
        claims = list(output.claims)
        if not claims and output.answer:
            claims = [ChatAnswerClaim(text=output.answer, evidence_ids=output.citation_ids)]
        if not claims:
            raise ValueError("The provider returned no grounded answer.")
        supplied_ids = {item.evidence_id for item in retrieved}
        if any(
            (item.paper_id is not None and item.paper_id != paper_id)
            or (item.document_id is not None and item.document_id != document_id)
            for item in retrieved
        ):
            raise ValueError("The retrieved context belongs to a different paper or document version.")
        cited_ids: list[str] = []
        for claim in claims:
            if not claim.evidence_ids:
                raise ValueError("A substantive chat claim is missing citations.")
            for evidence_id in claim.evidence_ids:
                if evidence_id not in supplied_ids:
                    raise ValueError("The provider cited evidence outside the supplied context.")
                if evidence_id not in cited_ids:
                    cited_ids.append(evidence_id)
        evidence = self.database.get_evidence_many(paper_id, cited_ids, owner_id)
        if set(evidence) != set(cited_ids) or any(item.document_id != document_id or item.paper_id != paper_id for item in evidence.values()):
            raise ValueError("The provider cited evidence from the wrong paper or document version.")
        supplied_by_id = {item.evidence_id: item for item in retrieved}
        if any(supplied_by_id[item].source_text.strip() != evidence[item].source_text.strip() for item in cited_ids):
            raise ValueError("The supplied evidence text does not match the current paper registry.")
        answer = output.summary.strip() if output.summary and output.summary.strip() else ""
        answer = "\n\n".join(part for part in [answer, *[claim.text.strip() for claim in claims]] if part)
        if not answer or _numeric_fidelity_error(answer, [evidence[item] for item in cited_ids]):
            raise ValueError("The generated answer was not numerically faithful to its evidence.")
        citations = [
            ChatCitation(evidence_id=item, page=evidence[item].page, section_id=evidence[item].section_id)
            for item in cited_ids
        ]
        return answer, citations

    def _message(
        self,
        session: ChatSession,
        role: ChatRole,
        content: str,
        *,
        status: ChatMessageStatus | None,
        sufficient_evidence: bool | None,
        citations: list[ChatCitation] | None = None,
        retrieval_query: str | None = None,
        retrieved_evidence_ids: list[str] | None = None,
        retrieval_scores: dict[str, float] | None = None,
    ) -> ChatMessage:
        return ChatMessage(
            id=f"msg_{uuid4().hex}",
            session_id=session.id,
            role=role,
            content=content,
            status=status,
            citations=citations or [],
            sufficient_evidence=sufficient_evidence,
            document_id=session.document_id,
            retrieval_query=retrieval_query,
            retrieved_evidence_ids=retrieved_evidence_ids or [],
            retrieval_scores=retrieval_scores or {},
            retriever_version=getattr(self.retriever, "version", None),
            provider=self.settings.ai_provider,
            model=getattr(self.provider, "model", self.settings.ai_model),
            created_at=datetime.now(timezone.utc),
        )


def _assemble_context(items: list[RetrievedEvidence], max_chars: int) -> str:
    chunks: list[str] = []
    total = 0
    for item in items:
        text = item.source_text.strip()
        chunk = (
            f"[EVIDENCE {item.evidence_id}]\nSection: {item.section_id or 'Unavailable'}\n"
            f"Page: {item.page if item.page is not None else 'Unavailable'}\n"
            f"Type: {item.evidence_type}\nText:\n{text}"
        )
        separator = "\n\n" if chunks else ""
        if total + len(separator) + len(chunk) > max_chars:
            remaining = max_chars - total - len(separator)
            if remaining > 80:
                chunks.append(separator + chunk[:remaining].rstrip() + "…")
            break
        chunks.append(separator + chunk)
        total += len(separator) + len(chunk)
    return "".join(chunks)


def _needs_history_context(question: str) -> bool:
    return bool(re.search(r"\b(it|they|them|this|that|these|those|the same|how is it|why did they)\b", question.lower()))


_NUMBER_RE = re.compile(r"(?<![A-Za-z])[+-]?(?:\d+(?:\.\d+)?(?:e[+-]?\d+)?|\.\d+)(?:%|[A-Za-z]+)?", re.IGNORECASE)


def _numeric_fidelity_error(answer: str, evidence: list[Evidence]) -> bool:
    source = " ".join(item.source_text for item in evidence)
    source_numbers = {token.lower() for token in _NUMBER_RE.findall(source)}
    answer_numbers = {token.lower() for token in _NUMBER_RE.findall(answer)}
    return any(token not in source_numbers for token in answer_numbers)


def _safe_error(error: Exception) -> str:
    text = str(error).strip()
    return text[:240] if text else "The AI provider request failed."
