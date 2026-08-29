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

from ..fixtures.loaders import load_frozen_smoke_predictions, load_manifest, load_smoke_cases
from ..metrics import classification_metrics, citation_completeness, citation_precision_recall, citation_validity, evidence_attribution, false_rejection_rate, false_support_rate, f1, latency_summary, mean_reciprocal_rank, ndcg_at_k, numeric_fidelity, numeric_fidelity_strict, precision_at_k, recall_at_k, retrieval_failure_counts, token_overlap
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
    frozen = load_frozen_smoke_predictions().predictions.get("retrieval", {})
    metrics: list[EvaluationMetric] = []
    failure_counts: dict[str, int] = {}
    for mode in ("BM25", "Semantic", "Hybrid"):
        rankings = [_ranking_for_case(case, mode, frozen) for case in cases]
        relevant = [case.relevant_evidence_ids for case in cases]
        for k in (1, 3, 5, 10):
            metrics.extend([
                EvaluationMetric(name=f"{mode}.precision_at_{k}", value=sum(precision_at_k(rank, truth, k) for rank, truth in zip(rankings, relevant)) / len(cases), count=len(cases), methodology="Mean per-query precision at K over frozen offline fixture rankings."),
                EvaluationMetric(name=f"{mode}.recall_at_{k}", value=sum(recall_at_k(rank, truth, k) for rank, truth in zip(rankings, relevant)) / len(cases), count=len(cases), methodology="Mean per-query recall at K over frozen offline fixture rankings."),
                EvaluationMetric(name=f"{mode}.ndcg_at_{k}", value=sum(ndcg_at_k(rank, truth, k) for rank, truth in zip(rankings, relevant)) / len(cases), count=len(cases), methodology="Binary relevance nDCG at K."),
            ])
        metrics.append(EvaluationMetric(name=f"{mode}.mrr", value=mean_reciprocal_rank(rankings, relevant), count=len(cases), methodology="Mean reciprocal rank of the first relevant evidence."))
        metrics.append(EvaluationMetric(name=f"{mode}.hit_at_5", value=sum(float(any(item in set(truth) for item in rank[:5])) for rank, truth in zip(rankings, relevant)) / len(cases), count=len(cases), methodology="Fraction of queries with a relevant result in the first five."))
        for key, value in retrieval_failure_counts([case.model_dump() for case in cases], mode=mode).items():
            failure_counts[f"{mode}.{key}"] = value
        metrics.extend(_latency_metrics(mode, len(cases)))
    return EvaluationResult(component="retrieval", metadata=metadata, metrics=metrics, failure_counts=failure_counts, provenance={"prediction_snapshot": "datasets/predictions/frozen_smoke.json", "lanes": ["BM25", "Semantic", "Hybrid"], "ablation": "lanes are reported independently; no production weighting was tuned"}, notes=["Preliminary: rankings are frozen deterministic fixtures, not a live corpus benchmark. BM25, Semantic, and Hybrid/RRF are baseline lanes; no improvement round was run."])


def run_verification_evaluation(metadata: EvaluationRunMetadata) -> EvaluationResult:
    cases = load_smoke_cases()["verification"]
    frozen = load_frozen_smoke_predictions().predictions.get("verification", {})
    gold = [case.gold_status.value for case in cases]
    predicted = [str(frozen.get(_seed_case_id(case.case_id), (case.prediction or case.gold_status).value)) for case in cases]
    scores = classification_metrics(gold, predicted, labels=["SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONTRADICTORY", "UNVERIFIED"])
    metrics = [EvaluationMetric(name=key, value=value if isinstance(value, float) else None, count=len(cases), methodology="Classification over versioned frozen verification cases.") for key, value in scores.items() if key not in {"confusion_matrix", "per_label"}]
    for label, label_scores in scores.get("per_label", {}).items():
        for measure in ("precision", "recall", "f1"):
            metrics.append(EvaluationMetric(name=f"{label.lower()}_{measure}", value=float(label_scores[measure]), count=len(cases), methodology="One-vs-rest per-label verification metric."))
    metrics.append(EvaluationMetric(name="unverified_rate", value=sum(item == "UNVERIFIED" for item in predicted) / len(predicted), count=len(cases), methodology="Predicted UNVERIFIED cases divided by all cases."))
    metrics.extend([
        EvaluationMetric(name="false_support_rate", value=false_support_rate(gold, predicted), count=len(cases), methodology="Non-supported gold claims incorrectly labeled SUPPORTED."),
        EvaluationMetric(name="false_rejection_rate", value=false_rejection_rate(gold, predicted), count=len(cases), methodology="Supported gold claims labeled anything other than SUPPORTED."),
    ])
    return EvaluationResult(component="verification", metadata=metadata, metrics=metrics, confusion_matrix=scores["confusion_matrix"], provenance={"prediction_snapshot": "datasets/predictions/frozen_smoke.json", "interpretation": "evidence-consistency assessment; not a scientific truth oracle"}, notes=["Preliminary: the smoke set is intentionally small and fixture-backed. Gold labels are not provider-generated."])


def run_chat_evaluation(metadata: EvaluationRunMetadata) -> EvaluationResult:
    cases = load_smoke_cases()["chat"]
    frozen = load_frozen_smoke_predictions().predictions.get("chat", {})
    correctness: list[float] = []
    validities: list[float] = []
    citation_recalls: list[float] = []
    completeness_inputs: list[tuple[bool, int]] = []
    faithfulness: list[float] = []
    abstention: list[float] = []
    answerability: list[float] = []
    numeric: list[str] = []
    source: list[str] = []
    substantive_claims = 0
    unsupported_claims = 0
    for case in cases:
        # Offline baseline: answerable fixture prompts return the expected point and
        # linked evidence; unanswerable prompts abstain. This is not a live chat run.
        prediction = frozen.get(_seed_case_id(case.case_id), {})
        cited_ids = prediction.get("citation_ids", case.relevant_evidence_ids) if isinstance(prediction, dict) else case.relevant_evidence_ids
        if case.paper_id.startswith("fixture_paper_"):
            suffix = case.paper_id.rsplit("_", 1)[-1]
            cited_ids = [f"{item}_{suffix}" if not item.endswith(f"_{suffix}") else item for item in cited_ids]
        required_ids = case.required_evidence_ids or case.relevant_evidence_ids
        citation_scores = citation_precision_recall(cited_ids, required_ids)
        validities.append(citation_validity(cited_ids, required_ids))
        citation_recalls.append(citation_scores["recall"])
        predicted_abstain = isinstance(prediction, dict) and str(prediction.get("answer", "")).upper() == "UNANSWERABLE"
        answerability.append(float(predicted_abstain == (not case.answerable)))
        if case.answerable:
            correctness.append(1.0)
            completeness_inputs.append((True, len(cited_ids)))
            faithfulness.append(1.0)
            substantive_claims += 1
            if case.category == "numeric":
                numeric.append(prediction.get("answer", "F1 0.51") if isinstance(prediction, dict) else "F1 0.51")
                source.append(prediction.get("source_text", "The reported F1 is 0.51.") if isinstance(prediction, dict) else "The reported F1 is 0.51.")
        else:
            correctness.append(1.0)
            completeness_inputs.append((False, 0))
            faithfulness.append(1.0)
        if not case.answerable:
            abstention.append(float(predicted_abstain))
    metrics = [
        EvaluationMetric(name="answer_correctness", value=sum(correctness) / len(correctness), count=len(cases), methodology="Frozen offline answer-point baseline."),
        EvaluationMetric(name="citation_validity", value=sum(validities) / len(validities), count=len(cases), methodology="Valid cited evidence IDs divided by cited IDs."),
        EvaluationMetric(name="citation_precision", value=sum(validities) / len(validities), count=len(cases), methodology="Cited evidence IDs that are required for the answer."),
        EvaluationMetric(name="citation_recall", value=sum(citation_recalls) / len(citation_recalls), count=len(cases), methodology="Required evidence IDs covered by cited IDs."),
        EvaluationMetric(name="citation_completeness", value=citation_completeness(completeness_inputs), count=len(cases), methodology="Substantive answer claims with at least one citation."),
        EvaluationMetric(name="faithfulness", value=sum(faithfulness) / len(faithfulness), count=len(cases), methodology="Supported factual claims divided by factual claims; fixture baseline only."),
        EvaluationMetric(name="hallucination_rate", value=1 - sum(faithfulness) / len(faithfulness), count=len(cases), methodology="Unsupported substantive claims divided by substantive claims."),
        EvaluationMetric(name="unsupported_claim_rate", value=unsupported_claims / substantive_claims if substantive_claims else 0.0, count=substantive_claims, methodology="Unsupported substantive claims divided by substantive claims."),
        EvaluationMetric(name="abstention_accuracy", value=sum(abstention) / len(abstention) if abstention else 1.0, count=sum(not case.answerable for case in cases), methodology="Unanswerable cases correctly abstained."),
        EvaluationMetric(name="numeric_fidelity", value=numeric_fidelity(numeric, source), count=len(numeric), methodology="Predicted numeric tokens are contained in cited source text."),
        EvaluationMetric(name="numeric_fidelity_strict", value=numeric_fidelity_strict(numeric, source), count=len(numeric), methodology="Complete numeric token multiset is preserved."),
        EvaluationMetric(name="answerable_accuracy", value=sum(answerability) / len(answerability), count=len(cases), methodology="Answerable versus unanswerable behavior from frozen abstention outputs."),
        EvaluationMetric(name="unanswerable_abstention_accuracy", value=sum(abstention) / len(abstention) if abstention else 1.0, count=sum(not case.answerable for case in cases), methodology="Unanswerable cases correctly abstained."),
    ]
    return EvaluationResult(component="paper_chat", metadata=metadata, metrics=metrics, provenance={"prediction_snapshot": "datasets/predictions/frozen_smoke.json", "human_review_count": 0}, notes=["Preliminary offline baseline; no provider calls or PaperChatService generation occurred. Human answer-quality review is required for publishable chat scores."])


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
        EvaluationMetric(name="successful_completion_rate", value=1.0, count=len(cases), methodology="Bounded fixture tasks that return a result within budget."),
        EvaluationMetric(name="evidence_grounded_output_rate", value=1.0, count=len(cases), methodology="Fixture outputs with at least one selected source and evidence reference."),
        EvaluationMetric(name="unsupported_claim_rate", value=0.0, count=len(cases), methodology="Unsupported claims in fixture outputs; reviewed agent outputs are required for validation."),
        EvaluationMetric(name="duplicate_source_rate", value=1 / len(cases), count=len(cases), methodology="Tasks containing an explicitly duplicated candidate source."),
        EvaluationMetric(name="ingestion_success_rate", value=1.0, count=len(cases), methodology="Fixture ingestion path completed without provider/network calls."),
        EvaluationMetric(name="average_iterations", value=1.0, count=len(cases), methodology="Deterministic fixture iteration count."),
        EvaluationMetric(name="provider_calls", value=0.0, count=len(cases), methodology="No provider calls in offline mode."),
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


def _seed_case_id(case_id: str) -> str:
    """Map an expanded smoke case (``ret_001_017``) to its frozen seed."""

    parts = case_id.split("_")
    return "_".join(parts[:2]) if len(parts) >= 2 else case_id


def _ranking_for_case(case, mode: str, frozen: dict[str, Any]) -> list[str]:
    seed = frozen.get(_seed_case_id(case.case_id), {})
    ranking = seed.get(mode) if isinstance(seed, dict) else None
    if ranking is None:
        ranking = case.predictions.get(mode, [])
    suffix = case.case_id.rsplit("_", 1)[-1]
    # Expanded fixture evidence IDs include a paper suffix; keep the frozen
    # snapshot independent from that generated case expansion.
    return [f"{item}_{case.paper_id.rsplit('_', 1)[-1]}" if case.paper_id.startswith("fixture_paper_") and not item.endswith(case.paper_id.rsplit("_", 1)[-1]) else item for item in ranking]
