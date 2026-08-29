"""Pure, tested metrics used by the offline evaluation runners."""

from __future__ import annotations

import math
import re
from collections import Counter
from statistics import mean
from time import perf_counter
from typing import Any, Iterable, Mapping, Sequence


def _bounded_k(k: int) -> int:
    if k < 1:
        raise ValueError("k must be positive")
    return k


def _ranked(ranked: Sequence[str], k: int) -> list[str]:
    return list(ranked[: _bounded_k(k)])


def precision_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    items = _ranked(ranked, k)
    relevant_set = set(relevant)
    return sum(item in relevant_set for item in items) / k


def recall_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    relevant_set = set(relevant)
    return sum(item in relevant_set for item in _ranked(ranked, k)) / max(len(relevant_set), 1)


def hit_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    relevant_set = set(relevant)
    return float(any(item in relevant_set for item in _ranked(ranked, k)))


def reciprocal_rank(ranked: Sequence[str], relevant: Iterable[str]) -> float:
    relevant_set = set(relevant)
    for index, item in enumerate(ranked, start=1):
        if item in relevant_set:
            return 1.0 / index
    return 0.0


def mean_reciprocal_rank(rankings: Iterable[Sequence[str]], relevants: Iterable[Iterable[str]]) -> float:
    ranking_list, relevant_list = list(rankings), list(relevants)
    if len(ranking_list) != len(relevant_list):
        raise ValueError("rankings and relevants must have equal length")
    pairs = list(zip(ranking_list, relevant_list))
    return mean([reciprocal_rank(ranked, relevant) for ranked, relevant in pairs]) if pairs else 0.0


def ndcg_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    items = _ranked(ranked, k)
    relevant_set = set(relevant)
    dcg = sum((1.0 / math.log2(index + 2)) for index, item in enumerate(items) if item in relevant_set)
    ideal_hits = min(len(relevant_set), k)
    idcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
    return dcg / idcg if idcg else 0.0


def graded_ndcg_at_k(ranked: Sequence[str], relevance: Mapping[str, int], k: int) -> float:
    """nDCG for optional 0--3 graded evidence relevance labels."""

    items = _ranked(ranked, k)
    grades = {str(item): max(0, int(score)) for item, score in relevance.items()}

    def gain(score: int) -> float:
        return float((2**score) - 1)

    dcg = sum(gain(grades.get(item, 0)) / math.log2(index + 2) for index, item in enumerate(items))
    ideal = sorted(grades.values(), reverse=True)[:k]
    idcg = sum(gain(score) / math.log2(index + 2) for index, score in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def classification_metrics(gold: Sequence[str], predicted: Sequence[str], labels: Sequence[str] | None = None) -> dict[str, float | dict[str, dict[str, int]] | dict[str, dict[str, float]]]:
    if len(gold) != len(predicted):
        raise ValueError("gold and predicted must have equal length")
    classes = list(dict.fromkeys(labels or [*gold, *predicted]))
    matrix = {actual: {guess: 0 for guess in classes} for actual in classes}
    for actual, guess in zip(gold, predicted):
        matrix.setdefault(actual, {label: 0 for label in classes})
        matrix[actual].setdefault(guess, 0)
        matrix[actual][guess] += 1
    per_class: list[float] = []
    per_label: dict[str, dict[str, float]] = {}
    for label in classes:
        tp = matrix.get(label, {}).get(label, 0)
        fp = sum(matrix.get(actual, {}).get(label, 0) for actual in classes if actual != label)
        fn = sum(matrix.get(label, {}).get(guess, 0) for guess in classes if guess != label)
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        per_class.append(f1(p, r))
        per_label[label] = {"precision": p, "recall": r, "f1": f1(p, r), "support": float(tp + fn)}
    accuracy = sum(actual == guess for actual, guess in zip(gold, predicted)) / len(gold) if gold else 0.0
    return {"accuracy": accuracy, "macro_f1": mean(per_class) if per_class else 0.0, "per_label": per_label, "confusion_matrix": matrix}


def false_support_rate(gold: Sequence[str], predicted: Sequence[str], *, supported_label: str = "SUPPORTED") -> float:
    """Fraction of non-supported gold claims incorrectly marked supported."""

    if len(gold) != len(predicted):
        raise ValueError("gold and predicted must have equal length")
    negatives = sum(actual != supported_label for actual in gold)
    return sum(actual != supported_label and guess == supported_label for actual, guess in zip(gold, predicted)) / negatives if negatives else 0.0


def false_rejection_rate(gold: Sequence[str], predicted: Sequence[str], *, supported_label: str = "SUPPORTED") -> float:
    """Fraction of supported gold claims rejected or left unverified."""

    if len(gold) != len(predicted):
        raise ValueError("gold and predicted must have equal length")
    positives = sum(actual == supported_label for actual in gold)
    return sum(actual == supported_label and guess != supported_label for actual, guess in zip(gold, predicted)) / positives if positives else 0.0


def citation_validity(cited_ids: Iterable[str], valid_ids: Iterable[str]) -> float:
    cited = list(cited_ids)
    valid = set(valid_ids)
    return sum(item in valid for item in cited) / len(cited) if cited else 1.0


def citation_precision_recall(cited_ids: Iterable[str], required_ids: Iterable[str]) -> dict[str, float]:
    """Precision/recall of citations against required evidence IDs."""

    cited, required = set(cited_ids), set(required_ids)
    precision = len(cited & required) / len(cited) if cited else (1.0 if not required else 0.0)
    recall = len(cited & required) / len(required) if required else float(not cited)
    return {"precision": precision, "recall": recall, "f1": f1(precision, recall)}


def citation_completeness(claim_evidence_counts: Sequence[tuple[bool, int]]) -> float:
    """Fraction of substantive claims with at least one supporting citation."""

    substantive = [has_claim for has_claim, _ in claim_evidence_counts if has_claim]
    if not substantive:
        return 1.0
    return sum(count > 0 for has_claim, count in claim_evidence_counts if has_claim) / len(substantive)


def numeric_fidelity(predicted: Sequence[str], source_texts: Sequence[str]) -> float:
    if len(predicted) != len(source_texts):
        raise ValueError("predicted and source_texts must have equal length")
    if not predicted:
        return 1.0
    scores = []
    for statement, source in zip(predicted, source_texts):
        numbers = set(_numbers(statement))
        source_numbers = set(_numbers(source))
        scores.append(float(numbers.issubset(source_numbers)))
    return mean(scores)


def numeric_fidelity_strict(predicted: Sequence[str], source_texts: Sequence[str]) -> float:
    """Require the complete numeric multiset to be preserved, not merely a subset."""

    if len(predicted) != len(source_texts):
        raise ValueError("predicted and source_texts must have equal length")
    if not predicted:
        return 1.0
    return mean(float(Counter(_numbers(statement)) == Counter(_numbers(source))) for statement, source in zip(predicted, source_texts))


def aggregate_retrieval_metrics(
    rankings: Sequence[Sequence[str]],
    relevants: Sequence[Iterable[str]],
    *,
    graded: Sequence[Mapping[str, int]] | None = None,
    ks: Sequence[int] = (1, 3, 5),
) -> dict[str, float]:
    """Compute a consistent retrieval metric bundle for one lane."""

    if len(rankings) != len(relevants) or (graded is not None and len(rankings) != len(graded)):
        raise ValueError("rankings, relevants, and graded labels must have equal length")
    if not rankings:
        return {name: 0.0 for k in ks for name in (f"recall_at_{k}", f"ndcg_at_{k}")} | {"mrr": 0.0}
    metrics: dict[str, float] = {}
    for k in ks:
        metrics[f"recall_at_{k}"] = mean(recall_at_k(rank, truth, k) for rank, truth in zip(rankings, relevants))
        if graded is None:
            metrics[f"ndcg_at_{k}"] = mean(ndcg_at_k(rank, truth, k) for rank, truth in zip(rankings, relevants))
        else:
            metrics[f"ndcg_at_{k}"] = mean(graded_ndcg_at_k(rank, labels, k) for rank, labels in zip(rankings, graded))
    metrics["mrr"] = mean_reciprocal_rank(rankings, relevants)
    return metrics


def retrieval_failure_category(
    *,
    query_category: str,
    ranked: Sequence[str],
    relevant: Iterable[str],
    has_table_or_equation: bool = False,
    multiple_passages: bool = False,
) -> str | None:
    """Assign one review category to a retrieval miss for error analysis."""

    relevant_set = set(relevant)
    if any(item in relevant_set for item in ranked[:5]):
        return None
    category = query_category.lower().replace(" ", "_")
    if multiple_passages:
        return "multiple_passages"
    if has_table_or_equation or category in {"table", "equation", "numeric"}:
        return "table_or_equation_evidence"
    if category in {"ambiguous", "terminology"}:
        return category
    if category in {"section", "method", "results", "limitation"}:
        return "section_or_chunk_boundary"
    return "lexical_or_embedding_miss"


def retrieval_failure_counts(cases: Iterable[Mapping[str, Any]], *, mode: str = "BM25") -> dict[str, int]:
    """Count deterministic review categories from case dictionaries."""

    counts: Counter[str] = Counter()
    for case in cases:
        category = retrieval_failure_category(
            query_category=str(case.get("category", "unknown")),
            ranked=list((case.get("predictions") or {}).get(mode, case.get("ranking", []))),
            relevant=case.get("relevant_evidence_ids", []),
            has_table_or_equation=bool(case.get("has_table_or_equation", False)),
            multiple_passages=bool(case.get("multiple_passages", False)),
        )
        if category:
            counts[category] += 1
    return dict(counts)


def evidence_attribution(predicted: Sequence[Iterable[str]], gold: Sequence[Iterable[str]]) -> dict[str, float]:
    if len(predicted) != len(gold):
        raise ValueError("predicted and gold must have equal length")
    precision_values: list[float] = []
    recall_values: list[float] = []
    for pred, truth in zip(predicted, gold):
        pred_set, truth_set = set(pred), set(truth)
        precision_values.append(len(pred_set & truth_set) / len(pred_set) if pred_set else 0.0)
        recall_values.append(len(pred_set & truth_set) / len(truth_set) if truth_set else float(not pred_set))
    p, r = mean(precision_values) if precision_values else 0.0, mean(recall_values) if recall_values else 0.0
    return {"precision": p, "recall": r, "f1": f1(p, r)}


def set_precision_recall_f1(predicted: Iterable[str], gold: Iterable[str]) -> dict[str, float]:
    """Precision/recall/F1 for detections such as artifacts or claims."""

    predicted_set, gold_set = set(predicted), set(gold)
    precision = len(predicted_set & gold_set) / len(predicted_set) if predicted_set else 0.0
    recall = len(predicted_set & gold_set) / len(gold_set) if gold_set else float(not predicted_set)
    return {"precision": precision, "recall": recall, "f1": f1(precision, recall)}


def boundary_f1(predicted_boundaries: Iterable[int], gold_boundaries: Iterable[int]) -> dict[str, float]:
    """Boundary F1 for paragraph segmentation (not paragraph-count equality)."""

    return set_precision_recall_f1(predicted_boundaries, gold_boundaries)


def ordered_accuracy(predicted: Sequence[str], gold: Sequence[str]) -> float:
    """Position-wise section-order accuracy with an explicit length penalty."""

    if not gold:
        return float(not predicted)
    return sum(index < len(predicted) and predicted[index] == label for index, label in enumerate(gold)) / len(gold)


def claim_match_scores(predicted: Sequence[str], gold: Sequence[str], threshold: float = 0.5) -> dict[str, float]:
    """Defensible lexical claim matching; semantic/AI judges are intentionally separate."""

    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")
    remaining = list(gold)
    matched = 0
    for statement in predicted:
        best_index, best_score = None, 0.0
        for index, target in enumerate(remaining):
            score = token_overlap(statement, target)
            if score > best_score:
                best_index, best_score = index, score
        if best_index is not None and best_score >= threshold:
            matched += 1
            remaining.pop(best_index)
    precision = matched / len(predicted) if predicted else 0.0
    recall = matched / len(gold) if gold else float(not predicted)
    return {"precision": precision, "recall": recall, "f1": f1(precision, recall)}


def dedup_scores(predicted_groups: Sequence[Iterable[str]], gold_groups: Sequence[Iterable[str]]) -> dict[str, float]:
    """Evaluate pairwise duplicate decisions, where false merges are costly."""

    def pairs(groups: Sequence[Iterable[str]]) -> set[frozenset[str]]:
        output: set[frozenset[str]] = set()
        for group in groups:
            values = list(dict.fromkeys(group))
            for index, left in enumerate(values):
                for right in values[index + 1:]:
                    output.add(frozenset((left, right)))
        return output
    return set_precision_recall_f1(pairs(predicted_groups), pairs(gold_groups))


def budget_compliance(observed: dict[str, int], limits: dict[str, int]) -> float:
    """Fraction of configured hard caps respected by an evaluation/run."""

    if not limits:
        return 1.0
    return sum(observed.get(name, 0) <= limit for name, limit in limits.items()) / len(limits)


def latency_summary(samples_ms: Sequence[float]) -> dict[str, float | int]:
    if any(not math.isfinite(value) or value < 0 for value in samples_ms):
        raise ValueError("latency samples must be finite and non-negative")
    if not samples_ms:
        return {"count": 0, "mean_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
    values = sorted(samples_ms)
    def percentile(fraction: float) -> float:
        index = min(len(values) - 1, max(0, math.ceil(fraction * len(values)) - 1))
        return values[index]
    return {"count": len(values), "mean_ms": mean(values), "p50_ms": percentile(0.50), "p95_ms": percentile(0.95), "max_ms": values[-1]}


def timed_call(callable_, *args, **kwargs):
    start = perf_counter()
    result = callable_(*args, **kwargs)
    return result, (perf_counter() - start) * 1000


def token_overlap(left: str, right: str) -> float:
    left_tokens = set(re.findall(r"[a-z0-9][a-z0-9_-]*", left.lower()))
    right_tokens = set(re.findall(r"[a-z0-9][a-z0-9_-]*", right.lower()))
    return len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)


def _numbers(value: str) -> list[str]:
    return re.findall(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?%?", value.lower())
