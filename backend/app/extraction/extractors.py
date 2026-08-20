"""Focused, schema-constrained research extractors."""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from ..ai.provider import AIProvider
from ..models.document import StatementOrigin, Evidence

P = TypeVar("P", bound=BaseModel)


class NoEvidenceError(ValueError):
    """No relevant paragraph evidence was available for a stage."""


class ClaimPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    origin: StatementOrigin
    confidence: float | None = Field(default=None, ge=0, le=1)


class ProblemPayload(ClaimPayload):
    context: str | None = None


class ClaimListPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ClaimPayload] = Field(default_factory=list)


class MethodStepPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    order: int = Field(ge=0)
    evidence_ids: list[str] = Field(default_factory=list)
    origin: StatementOrigin


class MethodRelationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_step_index: int = Field(ge=0)
    target_step_index: int = Field(ge=0)
    relationship: str = Field(min_length=1)


class MethodPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    origin: StatementOrigin
    steps: list[MethodStepPayload] = Field(default_factory=list)
    relations: list[MethodRelationPayload] = Field(default_factory=list)


class EquationVariablePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1)
    meaning: str | None = None


class EquationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equation_id: str | None = None
    expression: str = Field(min_length=1)
    explanation: str | None = None
    role: str | None = None
    variables: list[EquationVariablePayload] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    origin: StatementOrigin


class EquationListPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[EquationPayload] = Field(default_factory=list)


class ExperimentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    datasets: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    baselines: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    setup: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    origin: StatementOrigin


class ExperimentListPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ExperimentPayload] = Field(default_factory=list)


class ResultPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1)
    metric: str | None = None
    value: float | str | None = None
    unit: str | None = None
    comparison_target: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    origin: StatementOrigin


class ResultListPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ResultPayload] = Field(default_factory=list)


class FocusedExtractor(Generic[P]):
    schema: ClassVar[type[P]]
    prompt_name: ClassVar[str]
    name: ClassVar[str]

    def __init__(self, provider: AIProvider, *, prompt_dir: Path | None = None) -> None:
        self.provider = provider
        self.prompt_dir = prompt_dir or Path(__file__).parents[1] / "prompts"

    async def extract(self, evidence: list[Evidence]) -> P:
        if not evidence:
            raise NoEvidenceError(f"No evidence is available for {self.name}.")
        prompt = self._prompt(evidence)
        return await self.provider.generate_structured(prompt, self.schema)

    def _prompt(self, evidence: list[Evidence]) -> str:
        instructions = (self.prompt_dir / self.prompt_name).read_text(encoding="utf-8")
        source = [
            {
                "evidence_id": item.id,
                "page": item.page,
                "section_id": item.section_id,
                "source_text": item.source_text,
            }
            for item in evidence
        ]
        return f"{instructions}\n\nSOURCE EVIDENCE JSON\n{json.dumps(source, ensure_ascii=False)}"


class ProblemExtractor(FocusedExtractor[ProblemPayload]):
    schema = ProblemPayload
    prompt_name = "problem_extractor.md"
    name = "problem"


class MotivationExtractor(FocusedExtractor[ClaimPayload]):
    schema = ClaimPayload
    prompt_name = "motivation_extractor.md"
    name = "motivation"


class ResearchGapExtractor(FocusedExtractor[ClaimListPayload]):
    schema = ClaimListPayload
    prompt_name = "gap_extractor.md"
    name = "research_gap"


class ContributionExtractor(FocusedExtractor[ClaimListPayload]):
    schema = ClaimListPayload
    prompt_name = "contribution_extractor.md"
    name = "contributions"


class MethodExtractor(FocusedExtractor[MethodPayload]):
    schema = MethodPayload
    prompt_name = "method_extractor.md"
    name = "method"


class EquationExtractor(FocusedExtractor[EquationListPayload]):
    schema = EquationListPayload
    prompt_name = "equation_extractor.md"
    name = "equations"


class ExperimentExtractor(FocusedExtractor[ExperimentListPayload]):
    schema = ExperimentListPayload
    prompt_name = "experiment_extractor.md"
    name = "experiments"


class ResultExtractor(FocusedExtractor[ResultListPayload]):
    schema = ResultListPayload
    prompt_name = "result_extractor.md"
    name = "results"


class LimitationExtractor(FocusedExtractor[ClaimListPayload]):
    schema = ClaimListPayload
    prompt_name = "limitation_extractor.md"
    name = "limitations"


class FutureWorkExtractor(FocusedExtractor[ClaimListPayload]):
    schema = ClaimListPayload
    prompt_name = "future_work_extractor.md"
    name = "future_work"
