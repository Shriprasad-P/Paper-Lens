"""Orchestrate focused, evidence-grounded extraction stages."""

from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel

from ..ai.provider import AIProvider, AIProviderError
from ..core.config import Settings
from ..db.database import SQLDatabase
from ..models.document import (
    ContributionIR,
    EquationIR,
    EquationVariableIR,
    ExperimentIR,
    ExtractionState,
    ExtractionStatus,
    FutureWorkIR,
    LimitationIR,
    MethodIR,
    MethodRelationIR,
    MethodStepIR,
    MotivationIR,
    PaperIR,
    ProblemIR,
    ResearchClaim,
    ResearchGapIR,
    ResultIR,
)
from .classifier import SectionClassifier
from .extractors import (
    ClaimListPayload,
    ContributionExtractor,
    EquationExtractor,
    ExperimentExtractor,
    ExperimentListPayload,
    FutureWorkExtractor,
    FocusedExtractor,
    LimitationExtractor,
    MethodExtractor,
    MethodPayload,
    MotivationExtractor,
    NoEvidenceError,
    ProblemExtractor,
    ProblemPayload,
    ResearchGapExtractor,
    ResultExtractor,
    ResultListPayload,
)
from .grounding import EvidenceGroundingError, validate_payload_grounding
from .selector import EvidenceSelector


class ResearchExtractionError(Exception):
    """Expected extraction orchestration failure."""


class ResearchExtractionService:
    PROMPT_VERSION = "v1"
    SCHEMA_VERSION = "v1"

    def __init__(
        self,
        database: SQLDatabase,
        provider: AIProvider,
        *,
        settings: Settings | None = None,
        classifier: SectionClassifier | None = None,
        selector: EvidenceSelector | None = None,
    ) -> None:
        self.database = database
        self.provider = provider
        self.settings = settings or Settings.from_env()
        self.classifier = classifier or SectionClassifier(provider)
        self.selector = selector or EvidenceSelector()
        self.extractors: dict[str, FocusedExtractor[Any]] = {
            "problem": ProblemExtractor(provider),
            "motivation": MotivationExtractor(provider),
            "research_gap": ResearchGapExtractor(provider),
            "contributions": ContributionExtractor(provider),
            "method": MethodExtractor(provider),
            "equations": EquationExtractor(provider),
            "experiments": ExperimentExtractor(provider),
            "results": ResultExtractor(provider),
            "limitations": LimitationExtractor(provider),
            "future_work": FutureWorkExtractor(provider),
        }

    async def extract(self, paper_id: str, owner_id: str = "user_legacy_local") -> PaperIR:
        document = self.database.get_document(paper_id, owner_id)
        if document is None:
            raise ResearchExtractionError("Structured document not found.")

        provider_name = self.settings.ai_provider
        model_name = getattr(self.provider, "model", self.settings.ai_model)
        cache_key = _cache_key(
            owner_id,
            paper_id,
            document.document_hash,
            provider_name,
            model_name,
            self.PROMPT_VERSION,
            self.SCHEMA_VERSION,
        )
        cached = self.database.get_analysis_record(paper_id, owner_id)
        if cached is not None and cached[1] == cache_key:
            return cached[0]

        classifications = await self.classifier.classify(document)
        paper_ir = PaperIR(
            paper_id=paper_id,
            document_id=document.id,
            metadata=document.metadata,
            section_classifications=[item.model_dump(mode="json") for item in classifications],
            provider=provider_name,
            model=model_name,
            prompt_version=self.PROMPT_VERSION,
            schema_version=self.SCHEMA_VERSION,
            document_hash=document.document_hash,
        )
        for stage in self.extractors:
            paper_ir.extraction[stage] = ExtractionState(
                status=ExtractionStatus.NOT_STARTED,
                cache_key=cache_key,
                provider=provider_name,
                model=model_name,
                prompt_version=self.PROMPT_VERSION,
                schema_version=self.SCHEMA_VERSION,
            )

        for stage, extractor in self.extractors.items():
            evidence = self.selector.select(document, classifications, stage)
            state = paper_ir.extraction[stage]
            if not evidence:
                state.status = ExtractionStatus.NO_EVIDENCE
                continue
            state.status = ExtractionStatus.RUNNING
            try:
                payload = await extractor.extract(evidence)
                validate_payload_grounding(payload, {item.id for item in evidence})
                if not _has_semantic_content(payload):
                    state.status = ExtractionStatus.NO_EVIDENCE
                    continue
                self._apply(stage, paper_ir, payload)
                state.status = ExtractionStatus.COMPLETED
            except NoEvidenceError:
                state.status = ExtractionStatus.NO_EVIDENCE
            except (EvidenceGroundingError, AIProviderError, ValueError, TypeError) as exc:
                state.status = ExtractionStatus.FAILED
                state.error = _safe_error(exc)
            except Exception:
                state.status = ExtractionStatus.FAILED
                state.error = "The extractor failed unexpectedly."

        self.database.save_analysis(
            paper_ir,
            cache_key=cache_key,
            provider=provider_name,
            model=model_name,
            prompt_version=self.PROMPT_VERSION,
            schema_version=self.SCHEMA_VERSION,
            owner_id=owner_id,
        )
        return paper_ir

    def _apply(self, stage: str, paper_ir: PaperIR, payload: BaseModel) -> None:
        if stage == "problem":
            value = payload
            assert isinstance(value, ProblemPayload)
            paper_ir.problem = ProblemIR(
                id="problem_001",
                statement=value.statement,
                context=value.context,
                evidence_ids=value.evidence_ids,
                origin=value.origin,
                confidence=value.confidence,
            )
        elif stage == "motivation":
            value = payload
            paper_ir.motivation = MotivationIR(id="motivation_001", **value.model_dump())
        elif stage in {"research_gap", "contributions", "limitations", "future_work"}:
            value = payload
            assert isinstance(value, ClaimListPayload)
            claims = [
                _claim(stage, index, item)
                for index, item in enumerate(value.items, start=1)
            ]
            if stage == "research_gap":
                paper_ir.research_gap = [ResearchGapIR.model_validate(item.model_dump()) for item in claims]
            elif stage == "contributions":
                paper_ir.contributions = [ContributionIR.model_validate(item.model_dump()) for item in claims]
            elif stage == "limitations":
                paper_ir.limitations = [LimitationIR.model_validate(item.model_dump()) for item in claims]
            else:
                paper_ir.future_work = [FutureWorkIR.model_validate(item.model_dump()) for item in claims]
        elif stage == "method":
            value = payload
            assert isinstance(value, MethodPayload)
            steps = [
                MethodStepIR(
                    id=f"method_step_{index:03d}",
                    label=item.label,
                    description=item.description,
                    order=item.order,
                    evidence_ids=item.evidence_ids,
                    origin=item.origin,
                )
                for index, item in enumerate(value.steps, start=1)
            ]
            relations = [
                MethodRelationIR(
                    source_step_id=f"method_step_{item.source_step_index + 1:03d}",
                    target_step_id=f"method_step_{item.target_step_index + 1:03d}",
                    relationship=item.relationship,
                )
                for item in value.relations
                if 0 <= item.source_step_index < len(steps) and 0 <= item.target_step_index < len(steps)
            ]
            paper_ir.method = MethodIR(
                summary=value.summary,
                evidence_ids=value.evidence_ids,
                origin=value.origin,
                steps=steps,
                relations=relations,
            )
        elif stage == "equations":
            value = payload
            for index, item in enumerate(value.items, start=1):
                paper_ir.equations.append(
                    EquationIR(
                        id=f"equation_{index:03d}",
                        equation_id=item.equation_id,
                        expression=item.expression,
                        explanation=item.explanation,
                        interpretation=item.explanation,
                        role=item.role,
                        variables=[EquationVariableIR(**variable.model_dump()) for variable in item.variables],
                        evidence_ids=item.evidence_ids,
                        origin=item.origin,
                    )
                )
        elif stage == "experiments":
            value = payload
            for index, item in enumerate(value.items, start=1):
                paper_ir.experiments.append(ExperimentIR(id=f"experiment_{index:03d}", **item.model_dump()))
        elif stage == "results":
            value = payload
            for index, item in enumerate(value.items, start=1):
                paper_ir.results.append(ResultIR(id=f"result_{index:03d}", **item.model_dump()))


def _claim(stage: str, index: int, item: Any) -> ResearchClaim:
    return ResearchClaim(id=f"{stage}_claim_{index:03d}", **item.model_dump())


def _has_semantic_content(payload: BaseModel) -> bool:
    data = payload.model_dump()
    if "items" in data:
        return bool(data["items"])
    return True


def _cache_key(*parts: str | None) -> str:
    value = "|".join(part or "" for part in parts)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_error(error: Exception) -> str:
    text = str(error)
    return text if len(text) < 240 else text[:237] + "..."
