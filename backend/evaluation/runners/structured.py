"""Generic structured-output evaluators for parser and extraction predictions."""

from __future__ import annotations

from typing import Iterable, Sequence

from ..metrics import boundary_f1, claim_match_scores, ordered_accuracy, set_precision_recall_f1


def evaluate_sections(predicted_labels: Sequence[str], gold_labels: Sequence[str]) -> dict[str, float]:
    if len(predicted_labels) != len(gold_labels):
        # Classification metrics can still be computed, but order accuracy
        # makes the mismatch explicit rather than hiding split/merge errors.
        order = ordered_accuracy(predicted_labels, gold_labels)
    else:
        order = ordered_accuracy(predicted_labels, gold_labels)
    labels = sorted(set(predicted_labels) | set(gold_labels))
    scores = []
    for label in labels:
        scores.append(set_precision_recall_f1([index for index, value in enumerate(predicted_labels) if value == label], [index for index, value in enumerate(gold_labels) if value == label]))
    macro_f1 = sum(score["f1"] for score in scores) / len(scores) if scores else 0.0
    return {"accuracy": sum(left == right for left, right in zip(predicted_labels, gold_labels)) / max(len(gold_labels), 1), "macro_f1": macro_f1, "order_accuracy": order}


def evaluate_paragraph_boundaries(predicted_boundaries: Iterable[int], gold_boundaries: Iterable[int]) -> dict[str, float]:
    return boundary_f1(predicted_boundaries, gold_boundaries)


def evaluate_artifacts(predicted_ids: Iterable[str], gold_ids: Iterable[str]) -> dict[str, float]:
    return set_precision_recall_f1(predicted_ids, gold_ids)


def page_accuracy(predicted_pages: Sequence[int | None], gold_pages: Sequence[int | None]) -> float:
    if len(predicted_pages) != len(gold_pages):
        raise ValueError("predicted and gold page lists must have equal length")
    return sum(left == right for left, right in zip(predicted_pages, gold_pages)) / len(gold_pages) if gold_pages else 1.0


def exact_field_accuracy(predicted: Sequence[object], gold: Sequence[object]) -> float:
    if len(predicted) != len(gold):
        raise ValueError("predicted and gold fields must have equal length")
    return sum(left == right for left, right in zip(predicted, gold)) / len(gold) if gold else 1.0


def evaluate_claim_category(predicted_statements: Sequence[str], gold_statements: Sequence[str], *, threshold: float = 0.5) -> dict[str, float]:
    return claim_match_scores(predicted_statements, gold_statements, threshold)
