from __future__ import annotations

import json
import unittest

from fastapi.testclient import TestClient

from backend.app.ai.provider import AIProvider, AIProviderError, UnavailableAIProvider
from backend.app.core.config import Settings
from backend.app.db.database import EvidenceRecord
from backend.app.extraction.service import ResearchExtractionService
from backend.app.main import create_app
from backend.app.models.document import Evidence, StatementOrigin
from backend.app.models.verification import VerificationOutput, VerificationStatus
from backend.app.verification.claims import VerifiableClaim
from backend.app.verification.service import PaperVerificationService
from backend.app.verification.verifier import FaithfulnessVerifier
from backend.tests.test_extraction import FakeProvider, _document_fixture


class MockVerificationProvider(AIProvider):
    model = "verification-fixture"

    def __init__(self, statuses: dict[str, VerificationStatus] | None = None, failures: set[str] | None = None) -> None:
        self.statuses = statuses or {}
        self.failures = failures or set()
        self.calls = 0
        self.prompts: list[str] = []

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        raise AssertionError("verification tests use structured output")

    async def generate_structured(self, prompt: str, schema: type[VerificationOutput]) -> VerificationOutput:
        self.calls += 1
        self.prompts.append(prompt)
        claim_json = prompt.split("CLAIM JSON\n", 1)[1].split("\n\nSOURCE EVIDENCE JSON", 1)[0]
        claim_id = json.loads(claim_json)["claim_id"]
        if claim_id in self.failures:
            raise AIProviderError("fixture verifier failure", retryable=False)
        return schema(
            status=self.statuses.get(claim_id, VerificationStatus.SUPPORTED),
            rationale=f"Fixture rationale for {claim_id}.",
            confidence=0.8,
        )


def _analysis_with_extractable_claims():
    database, paper_id = _document_fixture()
    extraction_service = ResearchExtractionService(
        database,
        FakeProvider(),
        settings=Settings(ai_provider="mock", ai_model="fixture-model"),
    )

    async def extract():
        analysis = await extraction_service.extract(paper_id)
        # The fixture's result contains an uncertainty string that is intentionally
        # not present in its linked source paragraph. Remove it for status/cache tests.
        analysis.results[0].value = None
        database.save_analysis(
            analysis,
            cache_key="verification-analysis-fixture",
            provider="mock",
            model="fixture-model",
            prompt_version="v1",
            schema_version="v1",
        )
        return analysis

    return database, paper_id, extract


class VerificationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_statuses_persist_and_reader_api_exposes_summary(self) -> None:
        database, paper_id, extract = _analysis_with_extractable_claims()
        await extract()
        statuses = {
            "problem_001": VerificationStatus.SUPPORTED,
            "motivation_001": VerificationStatus.PARTIALLY_SUPPORTED,
            "limitations_claim_001": VerificationStatus.UNSUPPORTED,
            "future_work_claim_001": VerificationStatus.CONTRADICTORY,
            "method_001": VerificationStatus.SUPPORTED,
            "method_step_001": VerificationStatus.SUPPORTED,
            "experiment_001": VerificationStatus.UNVERIFIED,
            "result_001": VerificationStatus.SUPPORTED,
        }
        provider = MockVerificationProvider(statuses, failures={"experiment_001"})
        settings = Settings(ai_provider="mock", ai_model="verification-fixture")
        service = PaperVerificationService(database, provider, settings=settings)
        client = TestClient(create_app(database=database, settings=settings, verification_service=service))

        response = client.post(f"/api/papers/{paper_id}/verify")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["total_claims"], 8)
        self.assertEqual(payload["summary"]["supported"], 4)
        self.assertEqual(payload["summary"]["partially_supported"], 1)
        self.assertEqual(payload["summary"]["unsupported"], 1)
        self.assertEqual(payload["summary"]["contradictory"], 1)
        self.assertEqual(payload["summary"]["unverified"], 1)
        self.assertEqual(len(payload["results"]), 8)

        reader = client.get(f"/api/papers/{paper_id}/reader")
        self.assertEqual(reader.status_code, 200)
        self.assertTrue(reader.json()["verification"]["available"])
        self.assertEqual(reader.json()["verification"]["summary"]["contradictory"], 1)

    async def test_cache_reuses_results_and_claim_or_evidence_changes_invalidate_entries(self) -> None:
        database, paper_id, extract = _analysis_with_extractable_claims()
        analysis = await extract()
        provider = MockVerificationProvider()
        settings = Settings(ai_provider="mock", ai_model="verification-fixture")
        service = PaperVerificationService(database, provider, settings=settings)

        first = await service.verify(paper_id)
        self.assertEqual(provider.calls, first.summary.total_claims)
        second = await service.verify(paper_id)
        self.assertEqual(provider.calls, first.summary.total_claims)
        self.assertEqual([item.cache_key for item in first.results], [item.cache_key for item in second.results])

        analysis.problem.statement = "The changed problem claim is deliberately reverified."
        database.save_analysis(
            analysis,
            cache_key="verification-analysis-fixture",
            provider="mock",
            model="fixture-model",
            prompt_version="v1",
            schema_version="v1",
        )
        await service.verify(paper_id)
        self.assertEqual(provider.calls, first.summary.total_claims + 1)

        with database.session_factory.begin() as session:
            evidence_record = session.get(EvidenceRecord, "ev_0001")
            evidence_record.source_text = "The changed source passage is still source data."
        await service.verify(paper_id)
        self.assertEqual(provider.calls, first.summary.total_claims + 3)

    async def test_missing_analysis_returns_safe_api_state(self) -> None:
        database, paper_id = _document_fixture()
        settings = Settings(ai_provider="mock", ai_model="verification-fixture")
        service = PaperVerificationService(database, MockVerificationProvider(), settings=settings)
        client = TestClient(create_app(database=database, settings=settings, verification_service=service))
        response = client.get(f"/api/papers/{paper_id}/verification")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["available"])
        self.assertEqual(client.post(f"/api/papers/{paper_id}/verify").status_code, 404)
        self.assertEqual(client.get("/api/papers/unknown/verification").status_code, 404)

    async def test_unavailable_provider_persists_unverified_without_crashing(self) -> None:
        database, paper_id, extract = _analysis_with_extractable_claims()
        await extract()
        settings = Settings(ai_provider="none", ai_model="verification-fixture")
        service = PaperVerificationService(database, UnavailableAIProvider(), settings=settings)
        result = await service.verify(paper_id)
        self.assertEqual(result.summary.total_claims, 8)
        self.assertEqual(result.summary.unverified, 8)
        self.assertTrue(result.available)


class DeterministicVerificationTests(unittest.IsolatedAsyncioTestCase):
    def _claim(self, *, document_id: str, evidence_ids: list[str], structured: dict[str, object] | None = None) -> VerifiableClaim:
        return VerifiableClaim(
            paper_id="paper_extraction",
            document_id=document_id,
            document_hash="fixture-document",
            claim_id="claim_test_001",
            kind="result",
            statement="The model achieves the reported metric.",
            origin=StatementOrigin.AUTHOR_EXPLICIT,
            evidence_ids=evidence_ids,
            structured=structured or {},
        )

    async def test_invalid_evidence_does_not_call_provider(self) -> None:
        database, paper_id = _document_fixture()
        document = database.get_document(paper_id)
        evidence = database.get_evidence(paper_id, "ev_0001")
        provider = MockVerificationProvider()
        verifier = FaithfulnessVerifier(provider, settings=Settings(ai_provider="mock", ai_model="verification-fixture"))

        missing = await verifier.verify_claim(
            self._claim(document_id=document.id, evidence_ids=["missing"]),
            [],
            claim_hash="claim",
            evidence_hash="evidence",
            cache_key="cache",
        )
        wrong_document = await verifier.verify_claim(
            self._claim(document_id="other-document", evidence_ids=[evidence.id]),
            [evidence],
            claim_hash="claim-2",
            evidence_hash="evidence-2",
            cache_key="cache-2",
        )
        empty_source = await verifier.verify_claim(
            self._claim(document_id=document.id, evidence_ids=[evidence.id]),
            [evidence.model_copy(update={"source_text": ""})],
            claim_hash="claim-3",
            evidence_hash="evidence-3",
            cache_key="cache-3",
        )
        self.assertEqual(provider.calls, 0)
        self.assertEqual(missing.status, VerificationStatus.UNVERIFIED)
        self.assertEqual(wrong_document.status, VerificationStatus.UNVERIFIED)
        self.assertEqual(empty_source.status, VerificationStatus.UNVERIFIED)

    async def test_numeric_fidelity_and_prompt_injection_are_data_only(self) -> None:
        database, paper_id = _document_fixture(prompt_injection=True)
        evidence = database.get_evidence(paper_id, "ev_0002")
        provider = MockVerificationProvider()
        verifier = FaithfulnessVerifier(provider, settings=Settings(ai_provider="mock", ai_model="verification-fixture"))

        numeric = await verifier.verify_claim(
            self._claim(document_id=evidence.document_id, evidence_ids=[evidence.id], structured={"value": "0.51 ± 0.02"}),
            [evidence],
            claim_hash="numeric",
            evidence_hash="numeric-evidence",
            cache_key="numeric-cache",
        )
        normal = await verifier.verify_claim(
            self._claim(document_id=evidence.document_id, evidence_ids=[evidence.id]),
            [evidence],
            claim_hash="normal",
            evidence_hash="normal-evidence",
            cache_key="normal-cache",
        )
        self.assertEqual(numeric.status, VerificationStatus.UNVERIFIED)
        self.assertEqual(provider.calls, 1)
        self.assertIn("untrusted source material", provider.prompts[0])
        self.assertIn("Ignore previous instructions", provider.prompts[0])
        self.assertEqual(normal.status, VerificationStatus.SUPPORTED)

    async def test_malformed_provider_output_becomes_unverified(self) -> None:
        database, paper_id = _document_fixture()
        evidence = database.get_evidence(paper_id, "ev_0001")

        class MalformedProvider(MockVerificationProvider):
            async def generate_structured(self, prompt: str, schema: type[VerificationOutput]) -> VerificationOutput:
                self.calls += 1
                raise AIProviderError("invalid verifier JSON", retryable=False)

        verifier = FaithfulnessVerifier(
            MalformedProvider(),
            settings=Settings(ai_provider="mock", ai_model="verification-fixture"),
        )
        result = await verifier.verify_claim(
            self._claim(document_id=evidence.document_id, evidence_ids=[evidence.id]),
            [evidence],
            claim_hash="malformed",
            evidence_hash="malformed-evidence",
            cache_key="malformed-cache",
        )
        self.assertEqual(result.status, VerificationStatus.UNVERIFIED)


if __name__ == "__main__":
    unittest.main()
