from __future__ import annotations

import re
import unittest

from fastapi.testclient import TestClient

from backend.app.ai.provider import AIProvider, AIProviderError, UnavailableAIProvider
from backend.app.chat.retrieval import BM25EvidenceRetriever, normalize_query
from backend.app.chat.service import PaperChatService
from backend.app.core.config import Settings
from backend.app.db.database import DocumentRecord
from backend.app.main import create_app
from backend.app.models.chat import ChatAnswerOutput, RetrievedEvidence
from backend.tests.test_extraction import _document_fixture


class ChatFixtureProvider(AIProvider):
    model = "chat-fixture"

    def __init__(self, *, mode: str = "answer") -> None:
        self.mode = mode
        self.calls = 0
        self.prompts: list[str] = []

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        raise AssertionError("chat tests use structured output")

    async def generate_structured(self, prompt: str, schema: type[ChatAnswerOutput]) -> ChatAnswerOutput:
        self.calls += 1
        self.prompts.append(prompt)
        if self.mode == "failure":
            raise AIProviderError("fixture provider unavailable", retryable=False)
        if self.mode == "hallucinated":
            return schema(answer="The method uses CNNs.", citation_ids=["ev_9999"], sufficient_evidence=True)
        if self.mode == "missing":
            return schema(answer="The method is described.", citation_ids=[], sufficient_evidence=True)
        evidence_ids = re.findall(r"\[EVIDENCE (ev_[0-9]+)\]", prompt)
        if self.mode == "numeric":
            return schema(claims=[{"text": "F1 = 51 ± 2.", "evidence_ids": evidence_ids[:1]}], sufficient_evidence=True)
        return schema(
            claims=[{"text": "The method is described in the supplied paper evidence.", "evidence_ids": evidence_ids[:1]}],
            sufficient_evidence=True,
        )


class SpyRetriever:
    version = "spy-v1"

    def __init__(self, database, paper_id: str, *, source_text: str | None = None) -> None:
        self.database = database
        self.paper_id = paper_id
        self.queries: list[str] = []
        evidence = database.get_evidence(paper_id, "ev_0003")
        assert evidence is not None
        self.item = RetrievedEvidence(
            evidence_id=evidence.id,
            score=1.0,
            section_id=evidence.section_id,
            page=evidence.page,
            source_text=source_text or evidence.source_text,
            retrieval_method=self.version,
            rank=1,
        )

    def retrieve(self, paper_id: str, query: str, limit: int = 8, section_hint: str | None = None):
        self.queries.append(query)
        return [self.item]


class ChatTests(unittest.IsolatedAsyncioTestCase):
    def test_query_normalization_preserves_scientific_tokens(self) -> None:
        self.assertEqual(normalize_query("  Explain ResNet-50, F1 and GPT-4.  "), "explain resnet-50 f1 gpt-4")

    def test_bm25_retrieval_is_bounded_and_section_aware(self) -> None:
        database, paper_id = _document_fixture()
        results = BM25EvidenceRetriever(database).retrieve(paper_id, "What are the limitations?", limit=2)
        self.assertLessEqual(len(results), 2)
        self.assertEqual(results[0].evidence_id, "ev_0006")
        self.assertEqual(results[0].retrieval_method, "bm25-v1")

    async def test_chat_persists_sessions_messages_and_valid_citations(self) -> None:
        database, paper_id = _document_fixture()
        provider = ChatFixtureProvider()
        settings = Settings(ai_provider="mock", ai_model="chat-fixture")
        service = PaperChatService(database, provider, settings=settings)
        session = service.create_session(paper_id)
        answer = await service.answer(paper_id, session.id, "What method is used?")
        self.assertEqual(answer.status.value, "ANSWERED")
        self.assertTrue(answer.citations)
        self.assertEqual(len(database.get_chat_messages(session.id)), 2)
        _, history = service.get_session(paper_id, session.id)
        self.assertEqual([item.role.value for item in history], ["USER", "ASSISTANT"])
        self.assertEqual(history[-1].citations[0].page, 2)

    async def test_hallucinated_and_missing_citations_are_not_valid_answers(self) -> None:
        database, paper_id = _document_fixture()
        settings = Settings(ai_provider="mock", ai_model="chat-fixture")
        for mode in ("hallucinated", "missing"):
            provider = ChatFixtureProvider(mode=mode)
            service = PaperChatService(database, provider, settings=settings)
            session = service.create_session(paper_id)
            with self.assertRaises(Exception):
                await service.answer(paper_id, session.id, "What method is used?")
            history = database.get_chat_messages(session.id)
            self.assertEqual(history[-1].status.value, "GENERATION_FAILED")

    async def test_wrong_source_text_and_numeric_rewrite_are_rejected(self) -> None:
        database, paper_id = _document_fixture()
        settings = Settings(ai_provider="mock", ai_model="chat-fixture")
        wrong_source = SpyRetriever(database, paper_id, source_text="Evidence from paper B.")
        wrong_service = PaperChatService(database, ChatFixtureProvider(), settings=settings, retriever=wrong_source)
        wrong_session = wrong_service.create_session(paper_id)
        with self.assertRaises(Exception):
            await wrong_service.answer(paper_id, wrong_session.id, "Explain the method.")

        numeric_retriever = SpyRetriever(database, paper_id)
        numeric_service = PaperChatService(database, ChatFixtureProvider(mode="numeric"), settings=settings, retriever=numeric_retriever)
        with self.assertRaises(Exception):
            await numeric_service.answer(paper_id, numeric_service.create_session(paper_id).id, "What is the F1 score?")

    async def test_follow_up_uses_history_only_to_expand_retrieval_query(self) -> None:
        database, paper_id = _document_fixture()
        retriever = SpyRetriever(database, paper_id)
        service = PaperChatService(database, ChatFixtureProvider(), settings=Settings(ai_provider="mock", ai_model="chat-fixture"), retriever=retriever)
        session = service.create_session(paper_id)
        await service.answer(paper_id, session.id, "What model is proposed?")
        await service.answer(paper_id, session.id, "How is it trained?")
        self.assertIn("model proposed", retriever.queries[1])

    async def test_unavailable_provider_and_document_change_are_safe(self) -> None:
        database, paper_id = _document_fixture()
        settings = Settings(ai_provider="none", ai_model="chat-fixture")
        service = PaperChatService(database, UnavailableAIProvider(), settings=settings)
        session = service.create_session(paper_id)
        with self.assertRaises(Exception):
            await service.answer(paper_id, session.id, "Explain the method.")
        self.assertEqual(database.get_chat_messages(session.id)[-1].status.value, "GENERATION_FAILED")

        changed_session = service.create_session(paper_id)
        with database.session_factory.begin() as db_session:
            document = db_session.get(DocumentRecord, changed_session.document_id)
            assert document is not None
            document.document_hash = "changed-document-hash"
        with self.assertRaises(Exception):
            await service.answer(paper_id, changed_session.id, "Explain the method.")
        self.assertEqual(database.get_chat_messages(changed_session.id), [])

    async def test_out_of_scope_question_returns_first_class_insufficient_state(self) -> None:
        database, paper_id = _document_fixture()
        provider = ChatFixtureProvider()
        service = PaperChatService(database, provider, settings=Settings(ai_provider="mock", ai_model="chat-fixture"))
        session = service.create_session(paper_id)
        answer = await service.answer(paper_id, session.id, "Who won the 2026 World Cup?")
        self.assertFalse(answer.sufficient_evidence)
        self.assertEqual(answer.status.value, "INSUFFICIENT_EVIDENCE")
        self.assertEqual(provider.calls, 0)

    def test_chat_api_session_and_history(self) -> None:
        database, paper_id = _document_fixture()
        settings = Settings(ai_provider="mock", ai_model="chat-fixture")
        client = TestClient(create_app(database=database, settings=settings, chat_service=PaperChatService(database, ChatFixtureProvider(), settings=settings)))
        created = client.post(f"/api/papers/{paper_id}/chat/sessions")
        self.assertEqual(created.status_code, 201)
        session_id = created.json()["session_id"]
        history = client.get(f"/api/papers/{paper_id}/chat/sessions/{session_id}")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()["messages"], [])


if __name__ == "__main__":
    unittest.main()
