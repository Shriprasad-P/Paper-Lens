"""Verification orchestration, cache keys, persistence coordination, and summaries."""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from ..ai.provider import AIProvider
from ..core.config import Settings
from ..db.database import SQLDatabase
from ..models.document import Evidence, PaperIR, StructuredDocument
from ..models.verification import (
    PaperVerificationResponse,
    VerificationResult,
    VerificationStatus,
    VerificationSummary,
)
from .claims import VerifiableClaim, collect_verifiable_claims
from .verifier import FaithfulnessVerifier


class PaperVerificationError(Exception):
    """Expected verification orchestration failure."""


class PaperVerificationService:
    """Verify persisted PaperIR claims independently and reuse valid results."""

    def __init__(
        self,
        database: SQLDatabase,
        provider: AIProvider,
        *,
        settings: Settings | None = None,
        verifier: FaithfulnessVerifier | None = None,
    ) -> None:
        self.database = database
        self.provider = provider
        self.settings = settings or Settings.from_env()
        self.verifier = verifier or FaithfulnessVerifier(provider, settings=self.settings)

    async def verify(self, paper_id: str) -> PaperVerificationResponse:
        analysis, document = self._load_analysis_and_document(paper_id)
        claims = collect_verifiable_claims(analysis)
        provider_name = self.settings.ai_provider
        model_name = getattr(self.provider, "model", self.settings.ai_model)
        prepared = self._prepare_claims(claims, paper_id, document.document_hash, provider_name, model_name)
        cached = self.database.get_verification_by_cache_keys(
            paper_id,
            [item["cache_key"] for item in prepared],
        )

        results: list[VerificationResult] = []
        fresh: list[VerificationResult] = []
        for item in prepared:
            cached_result = cached.get(item["cache_key"])
            if cached_result is not None:
                results.append(cached_result)
                continue
            result = await self.verifier.verify_claim(
                item["claim"],
                item["evidence"],
                claim_hash=item["claim_hash"],
                evidence_hash=item["evidence_hash"],
                cache_key=item["cache_key"],
            )
            results.append(result)
            fresh.append(result)

        if fresh:
            self.database.save_verification_results(paper_id, document.id, fresh)
        return _response(
            paper_id=paper_id,
            document_id=document.id,
            document_hash=document.document_hash,
            results=results,
            total_claims=len(claims),
            available=True,
        )

    def current(self, paper_id: str) -> PaperVerificationResponse:
        """Return only results matching the current analysis/document cache keys."""

        document = self.database.get_document(paper_id)
        if document is None:
            return PaperVerificationResponse(
                paper_id=paper_id,
                available=False,
                error="Structured document not found.",
                summary=_summary([], total_claims=0),
            )
        analysis_record = self.database.get_analysis_record(paper_id)
        if analysis_record is None:
            return PaperVerificationResponse(
                paper_id=paper_id,
                document_id=document.id,
                document_hash=document.document_hash,
                available=False,
                error="Paper analysis not found.",
                summary=_summary([], total_claims=0),
            )
        analysis = analysis_record[0]
        claims = collect_verifiable_claims(analysis)
        provider_name = self.settings.ai_provider
        model_name = getattr(self.provider, "model", self.settings.ai_model)
        prepared = self._prepare_claims(claims, paper_id, document.document_hash, provider_name, model_name)
        cached = self.database.get_verification_by_cache_keys(
            paper_id,
            [item["cache_key"] for item in prepared],
        )
        results = [cached[item["cache_key"]] for item in prepared if item["cache_key"] in cached]
        return _response(
            paper_id=paper_id,
            document_id=document.id,
            document_hash=document.document_hash,
            results=results,
            total_claims=len(claims),
            available=bool(results),
        )

    def _load_analysis_and_document(self, paper_id: str) -> tuple[PaperIR, StructuredDocument]:
        analysis_record = self.database.get_analysis_record(paper_id)
        if analysis_record is None:
            raise PaperVerificationError("Paper analysis not found.")
        document = self.database.get_document(paper_id)
        if document is None:
            raise PaperVerificationError("Structured document not found.")
        return analysis_record[0], document

    def _prepare_claims(
        self,
        claims: list[VerifiableClaim],
        paper_id: str,
        document_hash: str | None,
        provider_name: str,
        model_name: str,
    ) -> list[dict[str, object]]:
        prepared: list[dict[str, object]] = []
        for claim in claims:
            evidence_by_id = self.database.get_evidence_many(paper_id, claim.evidence_ids)
            evidence = [evidence_by_id[evidence_id] for evidence_id in claim.evidence_ids if evidence_id in evidence_by_id]
            claim_hash = _hash_payload(claim.model_dump(mode="json"))
            evidence_hash = _evidence_hash(claim.evidence_ids, evidence_by_id)
            cache_key = _cache_key(
                document_hash,
                claim_hash,
                evidence_hash,
                provider_name,
                model_name,
                self.verifier.PROMPT_VERSION,
                self.verifier.SCHEMA_VERSION,
            )
            prepared.append(
                {
                    "claim": claim,
                    "evidence": evidence,
                    "claim_hash": claim_hash,
                    "evidence_hash": evidence_hash,
                    "cache_key": cache_key,
                }
            )
        return prepared


def _response(
    *,
    paper_id: str,
    document_id: str,
    document_hash: str | None,
    results: list[VerificationResult],
    total_claims: int,
    available: bool,
) -> PaperVerificationResponse:
    return PaperVerificationResponse(
        paper_id=paper_id,
        document_id=document_id,
        document_hash=document_hash,
        available=available,
        summary=_summary(results, total_claims=total_claims),
        results=results,
    )


def _summary(results: list[VerificationResult], *, total_claims: int) -> VerificationSummary:
    counts = Counter(result.status for result in results)
    latest = max((result.verified_at for result in results), default=None)
    return VerificationSummary(
        total_claims=total_claims,
        supported=counts[VerificationStatus.SUPPORTED],
        partially_supported=counts[VerificationStatus.PARTIALLY_SUPPORTED],
        unsupported=counts[VerificationStatus.UNSUPPORTED],
        contradictory=counts[VerificationStatus.CONTRADICTORY],
        unverified=counts[VerificationStatus.UNVERIFIED],
        verified_at=latest,
    )


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _evidence_hash(evidence_ids: list[str], evidence_by_id: dict[str, Evidence]) -> str:
    payload = []
    for evidence_id in evidence_ids:
        item = evidence_by_id.get(evidence_id)
        payload.append(
            {
                "id": evidence_id,
                "paper_id": item.paper_id if item else None,
                "document_id": item.document_id if item else None,
                "source_text": item.source_text if item else None,
                "page": item.page if item else None,
                "section_id": item.section_id if item else None,
                "evidence_type": item.evidence_type.value if item else None,
            }
        )
    return _hash_payload(payload)


def _cache_key(*parts: str | None) -> str:
    return _hash_payload([part or "" for part in parts])
