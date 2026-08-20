"""Deterministic section classification with an optional AI fallback."""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ..ai.provider import AIProvider
from ..models.document import StructuredDocument


class SectionType(str, Enum):
    ABSTRACT = "ABSTRACT"
    INTRODUCTION = "INTRODUCTION"
    BACKGROUND = "BACKGROUND"
    RELATED_WORK = "RELATED_WORK"
    METHOD = "METHOD"
    EXPERIMENTS = "EXPERIMENTS"
    RESULTS = "RESULTS"
    DISCUSSION = "DISCUSSION"
    LIMITATIONS = "LIMITATIONS"
    CONCLUSION = "CONCLUSION"
    REFERENCES = "REFERENCES"
    UNKNOWN = "UNKNOWN"


class SectionClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str
    classification: SectionType
    confidence: float | None = Field(default=None, ge=0, le=1)


_HEADING_MAP: dict[str, SectionType] = {
    "abstract": SectionType.ABSTRACT,
    "introduction": SectionType.INTRODUCTION,
    "background": SectionType.BACKGROUND,
    "related work": SectionType.RELATED_WORK,
    "related works": SectionType.RELATED_WORK,
    "method": SectionType.METHOD,
    "methods": SectionType.METHOD,
    "methodology": SectionType.METHOD,
    "approach": SectionType.METHOD,
    "experiments": SectionType.EXPERIMENTS,
    "experimental setup": SectionType.EXPERIMENTS,
    "results": SectionType.RESULTS,
    "experimental results": SectionType.RESULTS,
    "discussion": SectionType.DISCUSSION,
    "limitations": SectionType.LIMITATIONS,
    "limitation": SectionType.LIMITATIONS,
    "conclusion": SectionType.CONCLUSION,
    "conclusions": SectionType.CONCLUSION,
    "references": SectionType.REFERENCES,
}


class SectionClassifier:
    def __init__(self, provider: AIProvider | None = None) -> None:
        self.provider = provider

    async def classify(self, document: StructuredDocument) -> list[SectionClassification]:
        classifications: list[SectionClassification] = []
        for section in document.sections:
            classification = _deterministic_classification(section.title)
            if classification is not SectionType.UNKNOWN or self.provider is None:
                classifications.append(
                    SectionClassification(
                        section_id=section.id,
                        classification=classification,
                        confidence=1.0 if classification is not SectionType.UNKNOWN else None,
                    )
                )
                continue
            prompt = _classification_prompt(section.title, section.paragraphs[0].text if section.paragraphs else "")
            try:
                result = await self.provider.generate_structured(prompt, SectionClassification)
                if result.section_id != section.id:
                    result.section_id = section.id
                classifications.append(result)
            except Exception:
                classifications.append(SectionClassification(section_id=section.id, classification=SectionType.UNKNOWN))
        return classifications


def _deterministic_classification(title: str) -> SectionType:
    normalized = re.sub(r"^[\d\s.)-]+", "", title.lower()).rstrip(": ").strip()
    return _HEADING_MAP.get(normalized, SectionType.UNKNOWN)


def _classification_prompt(title: str, sample: str) -> str:
    prompt_path = Path(__file__).parents[1] / "prompts" / "section_classifier.md"
    instructions = prompt_path.read_text(encoding="utf-8")
    return f"{instructions}\n\nHEADING\n{title}\n\nSOURCE SAMPLE\n{sample}"
