"""Application-level validation that semantic output cites supplied evidence."""

from __future__ import annotations

from typing import Iterable

from pydantic import BaseModel


class EvidenceGroundingError(ValueError):
    """Structured output referenced missing or empty evidence."""


def validate_evidence_ids(evidence_ids: Iterable[str], available_ids: set[str]) -> None:
    ids = list(evidence_ids)
    if not ids:
        raise EvidenceGroundingError("Every semantic statement must cite at least one evidence ID.")
    invalid = sorted(set(ids) - available_ids)
    if invalid:
        raise EvidenceGroundingError(f"Unknown evidence IDs: {', '.join(invalid)}")


def validate_payload_grounding(payload: BaseModel, available_ids: set[str]) -> None:
    """Validate every evidence_ids field in a nested structured response."""

    def walk(value: object) -> None:
        if isinstance(value, BaseModel):
            for field_name, field_value in value.model_dump().items():
                if field_name == "evidence_ids":
                    validate_evidence_ids(field_value, available_ids)
                else:
                    walk(getattr(value, field_name, field_value))
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
