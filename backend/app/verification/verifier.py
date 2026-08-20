"""Focused faithfulness verification for one claim and its linked evidence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from pydantic import ValidationError

from ..ai.provider import AIProvider, AIProviderError
from ..core.config import Settings
from ..models.document import Evidence
from ..models.verification import VerificationOutput, VerificationResult, VerificationStatus
from .claims import VerifiableClaim


class FaithfulnessVerifier:
    """Verify one claim without loading or re-analyzing the whole paper."""

    PROMPT_VERSION = "v1"
    SCHEMA_VERSION = "v1"

    def __init__(
        self,
        provider: AIProvider,
        *,
        settings: Settings | None = None,
        prompt_dir: Path | None = None,
    ) -> None:
        self.provider = provider
        self.settings = settings or Settings.from_env()
        self.prompt_dir = prompt_dir or Path(__file__).parents[1] / "prompts"

    async def verify_claim(
        self,
        claim: VerifiableClaim,
        evidence: list[Evidence],
        *,
        claim_hash: str,
        evidence_hash: str,
        cache_key: str,
    ) -> VerificationResult:
        """Validate the evidence boundary, then call the structured verifier."""

        provider_name = self.settings.ai_provider
        model_name = getattr(self.provider, "model", self.settings.ai_model)
        invalid_reason = _deterministic_validation_error(claim, evidence)
        if invalid_reason is None:
            invalid_reason = _numeric_fidelity_error(claim, evidence)
        if invalid_reason is not None:
            return self._result(
                claim,
                VerificationStatus.UNVERIFIED,
                invalid_reason,
                claim_hash=claim_hash,
                evidence_hash=evidence_hash,
                cache_key=cache_key,
                provider_name=provider_name,
                model_name=model_name,
            )

        try:
            output = await self.provider.generate_structured(self._prompt(claim, evidence), VerificationOutput)
            return self._result(
                claim,
                output.status,
                output.rationale,
                confidence=output.confidence,
                claim_hash=claim_hash,
                evidence_hash=evidence_hash,
                cache_key=cache_key,
                provider_name=provider_name,
                model_name=model_name,
            )
        except (AIProviderError, ValidationError, ValueError, TypeError) as exc:
            return self._result(
                claim,
                VerificationStatus.UNVERIFIED,
                _safe_error(exc),
                claim_hash=claim_hash,
                evidence_hash=evidence_hash,
                cache_key=cache_key,
                provider_name=provider_name,
                model_name=model_name,
            )
        except Exception:
            return self._result(
                claim,
                VerificationStatus.UNVERIFIED,
                "The faithfulness verifier failed unexpectedly.",
                claim_hash=claim_hash,
                evidence_hash=evidence_hash,
                cache_key=cache_key,
                provider_name=provider_name,
                model_name=model_name,
            )

    def _prompt(self, claim: VerifiableClaim, evidence: list[Evidence]) -> str:
        instructions = (self.prompt_dir / "faithfulness_verifier.md").read_text(encoding="utf-8")
        claim_payload = {
            "claim_id": claim.claim_id,
            "kind": claim.kind,
            "statement": claim.statement,
            "origin": claim.origin.value,
            "structured": claim.structured,
        }
        evidence_payload = [
            {
                "evidence_id": item.id,
                "page": item.page,
                "section_id": item.section_id,
                "evidence_type": item.evidence_type.value,
                "source_text": item.source_text,
            }
            for item in evidence
        ]
        return (
            f"{instructions}\n\nCLAIM JSON\n{json.dumps(claim_payload, ensure_ascii=False)}"
            f"\n\nSOURCE EVIDENCE JSON\n{json.dumps(evidence_payload, ensure_ascii=False)}"
        )

    def _result(
        self,
        claim: VerifiableClaim,
        status: VerificationStatus,
        rationale: str,
        *,
        claim_hash: str,
        evidence_hash: str,
        cache_key: str,
        provider_name: str,
        model_name: str,
        confidence: float | None = None,
    ) -> VerificationResult:
        return VerificationResult(
            claim_id=claim.claim_id,
            status=status,
            evidence_ids=list(claim.evidence_ids),
            rationale=rationale[:600],
            confidence=confidence,
            verified_at=datetime.now(timezone.utc),
            verifier_provider=provider_name,
            verifier_model=model_name,
            prompt_version=self.PROMPT_VERSION,
            schema_version=self.SCHEMA_VERSION,
            document_hash=claim.document_hash,
            claim_hash=claim_hash,
            evidence_hash=evidence_hash,
            cache_key=cache_key,
        )


def _deterministic_validation_error(claim: VerifiableClaim, evidence: list[Evidence]) -> str | None:
    if not claim.claim_id or not claim.statement.strip():
        return "The claim is missing a stable ID or statement."
    if not claim.evidence_ids:
        return "The claim has no linked evidence IDs."
    expected = list(dict.fromkeys(claim.evidence_ids))
    actual = {item.id: item for item in evidence}
    missing = [evidence_id for evidence_id in expected if evidence_id not in actual]
    if missing:
        return f"Linked evidence could not be resolved: {', '.join(missing)}."
    for item in evidence:
        if item.paper_id != claim.paper_id:
            return "Linked evidence belongs to a different paper."
        if item.document_id != claim.document_id:
            return "Linked evidence belongs to a different document version."
        if not item.source_text.strip():
            return f"Evidence {item.id} has no source text."
    return None


def _numeric_fidelity_error(claim: VerifiableClaim, evidence: list[Evidence]) -> str | None:
    value = claim.structured.get("value")
    if value is None or isinstance(value, bool):
        return None
    value_text = str(value)
    source_text = " ".join(item.source_text for item in evidence)
    if value_text in source_text:
        return None
    return (
        f"The structured numeric value {value_text!r} was not found verbatim in the linked evidence; "
        "numeric verification remains unverified."
    )


def _safe_error(error: Exception) -> str:
    text = str(error).strip()
    if not text:
        return "The faithfulness verifier returned invalid structured output."
    return text[:600]
