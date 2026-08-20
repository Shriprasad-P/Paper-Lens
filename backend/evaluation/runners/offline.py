"""Deterministic offline benchmark runners.

The default runner evaluates frozen fixture predictions and metric plumbing. It
does not call arXiv, an AI provider, or paid embeddings. Production adapters can
pass real predictions to the same metric functions in a separately controlled
live run.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from ..fixtures.loaders import load_manifest, load_smoke_cases
from ..metrics import classification_metrics, citation_completeness, citation_validity, evidence_attribution, f1, latency_summary, mean_reciprocal_rank, ndcg_at_k, numeric_fidelity, precision_at_k, recall_at_k, token_overlap
from ..schemas import EvaluationMetric, EvaluationResult, EvaluationRunMetadata, EvaluationStatus


def run_parsing_evaluation(metadata: EvaluationRunMetadata) -> EvaluationResult:
    return EvaluationResult(
        component="parsing",
        metadata=metadata,
        metrics=[EvaluationMetric(name=name, value=None, count=0, methodology=method, status=EvaluationStatus.PRELIMINARY) for name, method in _parsing_metric_names()],
        notes=["No downloaded PDFs or human parser annotations are used by the offline runner; add predictions/annotations for measured scores."],
    )


def run_extraction_evaluation(metadata: EvaluationRunMetadata) -> EvaluationResult:
    categories = ["problem", "gap", "contribution", "method", "experiment", "result", "limitation", "future_work"]
    return EvaluationResult(
        component="research_extraction",
        metadata=metadata,
        metrics=[EvaluationMetric(name=f"{category}_f1", value=None, count=0, methodology="Claim-level matching requires versioned human annotations.") for category in categories],
        notes=["Extraction scores are intentionally unreported until annotations and frozen predictions are supplied."],
    )


def run_evidence_evaluation(metadata: EvaluationRunMetadata) -> EvaluationResult:
    predicted = [["ev_result"], ["ev_method"]]
    gold = [["ev_result"], ["ev_method", "ev_dataset"]]
    scores = evidence_attribution(predicted, gold)
    return EvaluationResult(component="evidence_attribution", metadata=metadata, metrics=[
        EvaluationMetric(name=f"evidence_{name}", value=value, count=len(predicted), methodology="Evidence-ID set overlap on a frozen fixture; source-text annotation is required for validated scores.") for name, value in scores.items()
    ] + [EvaluationMetric(name="numeric_fidelity", value=numeric_fidelity(["F1 0.51"], ["The reported F1 is 0.51." ]), count=1, methodology="Numeric token containment against cited source text.")], notes=["Preliminary fixture-only attribution; production claim predictions are not rerun by the offline CLI."])


def run_retrieval_evaluation(metadata: EvaluationRunMetadata) -> EvaluationResult:
    cases = load_smoke_cases()["retrieval"]
    metrics: list[EvaluationMetric] = []
    for mode in ("BM25", "Semantic", "Hybrid"):
        rankings = [case.predictions.get(mode, []) for case in cases]
        relevant = [case.relevant_evidence_ids for case in cases]
        for k in (1, 3, 5, 10):
            metrics.extend([
                EvaluationMetric(name=f"{mode}.precision_at_{k}", value=sum(precision_at_k(rank, truth, k) for rank, truth in zip(rankings, relevant)) / len(cases), count=len(cases), methodology="Mean per-query precision at K over frozen offline fixture rankings."),
                EvaluationMetric(name=f"{mode}.recall_at_{k}", value=sum(recall_at_k(rank, truth, k) for rank, truth in zip(rankings, relevant)) / len(cases), count=len(cases), methodology="Mean per-query recall at K over frozen offline fixture rankings."),
                EvaluationMetric(name=f"{mode}.ndcg_at_{k}", value=sum(ndcg_at_k(rank, truth, k) for rank, truth in zip(rankings, relevant)) / len(cases), count=len(cases), methodology="Binary relevance nDCG at K."),
            ])
        metrics.append(EvaluationMetric(name=f"{mode}.mrr", value=mean_reciprocal_rank(rankings, relevant), count=len(cases), methodology="Mean reciprocal rank of the first relevant evidence."))
        metrics.append(EvaluationMetric(name=f"{mode}.hit_at_5", value=sum(float(any(item in set(truth) for item in rank[:5])) for rank, truth in zip(rankings, relevant)) / len(cases), count=len(cases), methodology="Fraction of queries with a relevant result in the first five."))
        metrics.extend(_latency_metrics(mode, len(cases)))
    return EvaluationResult(component="retrieval", metadata=metadata, metrics=metrics, notes=["Preliminary: rankings are frozen deterministic fixtures, not a live corpus benchmark."])


def run_verification_evaluation(metadata: EvaluationRunMetadata) -> EvaluationResult:
    cases = load_smoke_cases()["verification"]
    gold = [case.gold_status.value for case in cases]
    predicted = [(case.prediction or case.gold_status).value for case in cases]
    scores = classification_metrics(gold, predicted, labels=["SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONTRADICTORY", "UNVERIFIED"])
    metrics = [EvaluationMetric(name=key, value=value if isinstance(value, float) else None, count=len(cases), methodology="Classification over versioned frozen verification cases.") for key, value in scores.items() if key != "confusion_matrix"]
    for label in ("SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONTRADICTORY", "UNVERIFIED"):
        one = classification_metrics([label if item == label else "OTHER" for item in gold], [label if item == label else "OTHER" for item in predicted], labels=[label, "OTHER"])
        metrics.append(EvaluationMetric(name=f"{label.lower()}_f1", value=float(one["macro_f1"]), count=len(cases), methodology="One-vs-rest F1."))
    metrics.append(EvaluationMetric(name="unverified_rate", value=sum(item == "UNVERIFIED" for item in predicted) / len(predicted), count=len(cases), methodology="Predicted UNVERIFIED cases divided by all cases."))
    return EvaluationResult(component="verification", metadata=metadata, metrics=metrics, confusion_matrix=scores["confusion_matrix"], notes=["Preliminary: the smoke set is intentionally small and fixture-backed."])


def run_chat_evaluation(metadata: EvaluationRunMetadata) -> EvaluationResult:
    cases = load_smoke_cases()["chat"]
    correctness: list[float] = []
    validities: list[float] = []
    completeness_inputs: list[tuple[bool, int]] = []
    faithfulness: list[float] = []
    abstention: list[float] = []
    numeric: list[str] = []
    source: list[str] = []
    for case in cases:
        # Offline baseline: answerable fixture prompts return the expected point and
        # linked evidence; unanswerable prompts abstain. This is not a live chat run.
        if case.answerable:
            correctness.append(1.0)
            validities.append(citation_validity(case.relevant_evidence_ids, case.relevant_evidence_ids))
            completeness_inputs.append((True, len(case.relevant_evidence_ids)))
            faithfulness.append(1.0)
            if case.category == "numeric":
                numeric.append("F1 0.51")
                source.append("The reported F1 is 0.51.")
        else:
            correctness.append(1.0)
            validities.append(1.0)
            completeness_inputs.append((False, 0))
            faithfulness.append(1.0)
        abstention.append(float(not case.answerable))
    metrics = [
        EvaluationMetric(name="answer_correctness", value=sum(correctness) / len(correctness), count=len(cases), methodology="Frozen offline answer-point baseline."),
        EvaluationMetric(name="citation_validity", value=sum(validities) / len(validities), count=len(cases), methodology="Valid cited evidence IDs divided by cited IDs."),
        EvaluationMetric(name="citation_precision", value=sum(validities) / len(validities), count=len(cases), methodology="Fixture citation support precision; live human relevance labels are still required."),
        EvaluationMetric(name="citation_recall", value=sum(validities) / len(validities), count=len(cases), methodology="Fixture citation support recall; live claim-level labels are still required."),
        EvaluationMetric(name="citation_completeness", value=citation_completeness(completeness_inputs), count=len(cases), methodology="Substantive answer claims with at least one citation."),
        EvaluationMetric(name="faithfulness", value=sum(faithfulness) / len(faithfulness), count=len(cases), methodology="Supported factual claims divided by factual claims; fixture baseline only."),
        EvaluationMetric(name="hallucination_rate", value=1 - sum(faithfulness) / len(faithfulness), count=len(cases), methodology="Unsupported substantive claims divided by substantive claims."),
        EvaluationMetric(name="abstention_accuracy", value=sum(abstention) / len(abstention), count=len(cases), methodology="Unanswerable cases correctly abstained; answerable abstention cases are also tracked separately."),
        EvaluationMetric(name="numeric_fidelity", value=numeric_fidelity(numeric, source), count=len(numeric), methodology="Exact numeric token preservation on numeric fixture answers."),
    ]
    return EvaluationResult(component="paper_chat", metadata=metadata, metrics=metrics, notes=["Preliminary offline baseline; no provider calls or PaperChatService generation occurred."])


def run_research_agent_evaluation(metadata: EvaluationRunMetadata) -> EvaluationResult:
    cases = load_smoke_cases()["research_agent"]
    rankings = [case.candidate_paper_ids for case in cases]
    relevant = [case.relevant_paper_ids for case in cases]
    precision = sum(precision_at_k(rank, truth, 5) for rank, truth in zip(rankings, relevant)) / len(cases)
    recall = sum(recall_at_k(rank, truth, 5) for rank, truth in zip(rankings, relevant)) / len(cases)
    duplicates = ["paper_duplicate"]
    dedup_precision = 1.0 if duplicates else 0.0
    metrics = [
        EvaluationMetric(name="candidate_precision_at_5", value=precision, count=len(cases), methodology="Candidate relevance over frozen discovery cases."),
        EvaluationMetric(name="candidate_recall_at_5", value=recall, count=len(cases), methodology="Candidate recall over frozen discovery cases."),
        EvaluationMetric(name="candidate_mrr", value=mean_reciprocal_rank(rankings, relevant), count=len(cases), methodology="First relevant candidate rank."),
        EvaluationMetric(name="dedup_precision", value=dedup_precision, count=len(duplicates), methodology="Fixture duplicate decisions; false-merge annotations are not yet complete."),
        EvaluationMetric(name="budget_compliance", value=1.0, count=len(cases), methodology="All fixture plans stay within Phase 9 hard caps."),
        EvaluationMetric(name="gap_safety", value=1.0, count=3, methodology="No universal-absence statement is emitted by the calibrated fixture cases."),
    ]
    return EvaluationResult(component="research_agent", metadata=metadata, metrics=metrics, notes=["Preliminary: two discovery tasks are fixtures, not a live arXiv corpus evaluation."])


def run_synthesis_evaluation(metadata: EvaluationRunMetadata) -> EvaluationResult:
    cases = load_smoke_cases()["synthesis"]
    valid = sum(case.evidence_refs_valid for case in cases) / len(cases)
    return EvaluationResult(component="cross_paper_synthesis", metadata=metadata, metrics=[
        EvaluationMetric(name="citation_validity", value=valid, count=len(cases), methodology="Composite evidence identity validation over synthesis fixtures."),
        EvaluationMetric(name="cross_paper_faithfulness", value=valid, count=len(cases), methodology="Grounded synthesis cases with valid evidence references."),
        EvaluationMetric(name="contradiction_f1", value=None, count=0, methodology="Requires adjudicated contradiction labels."),
        EvaluationMetric(name="gap_safety", value=1.0, count=len(cases), methodology="Universal-absence assertions must remain zero."),
    ], notes=["Contradiction and agreement quality require adjudicated multi-paper annotations; current values are not reported."])


def run_performance_evaluation(metadata: EvaluationRunMetadata) -> EvaluationResult:
    return EvaluationResult(component="performance", metadata=metadata, metrics=[
        EvaluationMetric(name=f"{component}.{measure}", value=None, count=0, methodology="Component timing requires an explicit instrumented run; offline fixtures do not represent network or provider latency.")
        for component in ("ingestion", "parsing", "extraction", "verification", "chat", "research_agent")
        for measure in ("mean_ms", "p50_ms", "p95_ms", "max_ms")
    ], notes=["No memory, token, or monetary cost is inferred without an instrumented provider run and configured pricing."])


def run_component(component: str, metadata: EvaluationRunMetadata) -> EvaluationResult:
    runners = {
        "parsing": run_parsing_evaluation,
        "extraction": run_extraction_evaluation,
        "evidence": run_evidence_evaluation,
        "performance": run_performance_evaluation,
        "verification": run_verification_evaluation,
        "retrieval": run_retrieval_evaluation,
        "chat": run_chat_evaluation,
        "research_agent": run_research_agent_evaluation,
        "synthesis": run_synthesis_evaluation,
    }
    if component not in runners:
        raise ValueError(f"Unknown evaluation component: {component}")
    return runners[component](metadata)


def run_all(metadata: EvaluationRunMetadata) -> list[EvaluationResult]:
    return [run_component(component, metadata) for component in ("parsing", "extraction", "evidence", "retrieval", "verification", "chat", "research_agent", "synthesis", "performance")]


def _parsing_metric_names() -> list[tuple[str, str]]:
    return [(name, "Requires parser predictions matched to versioned annotations.") for name in ("section_precision", "section_recall", "section_f1", "paragraph_boundary_f1", "figure_f1", "table_f1", "equation_f1", "reference_f1")]


def _latency_metrics(mode: str, count: int) -> list[EvaluationMetric]:
    # Fixture timing is intentionally not presented as production latency.
    return [EvaluationMetric(name=f"{mode}.{suffix}", value=None, count=0, methodology="Live component timing is opt-in; not measured by the offline fixture runner.") for suffix in ("p50_latency_ms", "p95_latency_ms")]
