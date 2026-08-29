"""Load and expand the versioned benchmark fixtures without network access."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..annotations import load_annotations
from ..provenance import EvaluationDataError, load_prediction_envelope, sha256_paths
from ..schemas import BenchmarkManifest, ChatBenchmarkCase, DiscoveryBenchmarkCase, RetrievalBenchmarkCase, SynthesisBenchmarkCase, VerificationBenchmarkCase

DATASET_DIR = Path(__file__).parents[1] / "datasets"
PREDICTIONS_DIR = DATASET_DIR / "predictions"


def load_manifest() -> dict[str, Any]:
    return json.loads((DATASET_DIR / "manifest.json").read_text(encoding="utf-8"))


def load_manifest_model() -> BenchmarkManifest:
    return BenchmarkManifest.model_validate(load_manifest())


def load_paper_annotations():
    """Load the human annotation ledger without mixing it into predictions."""

    return load_annotations(DATASET_DIR / "annotations.jsonl")


def dataset_hash() -> str:
    """Hash all committed benchmark inputs in a stable path order."""

    return sha256_paths(
        [DATASET_DIR / name for name in ("manifest.json", "annotations.jsonl", "smoke_cases.json")],
        root=DATASET_DIR,
    )


def load_frozen_smoke_predictions():
    """Load the checked-in prediction snapshot used by the fixture runner."""

    envelope = load_prediction_envelope(PREDICTIONS_DIR / "frozen_smoke.json")
    expected = dataset_hash()
    if envelope.dataset_hash != expected:
        raise EvaluationDataError("Frozen predictions reference a different dataset hash")
    return envelope


def load_failure_examples() -> list[dict[str, Any]]:
    """Load preserved examples without treating them as gold labels."""

    path = DATASET_DIR / "failures.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_smoke_cases() -> dict[str, list[Any]]:
    raw = json.loads((DATASET_DIR / "smoke_cases.json").read_text(encoding="utf-8"))
    return {
        "retrieval": _retrieval_cases(raw["retrieval"]),
        "verification": _verification_cases(raw["verification"]),
        "chat": _chat_cases(raw["chat"]),
        "research_agent": [DiscoveryBenchmarkCase.model_validate(item) for item in raw["research_agent"]],
        "synthesis": [SynthesisBenchmarkCase.model_validate(item) for item in raw["synthesis"]],
    }


def _retrieval_cases(seed: list[dict[str, Any]], minimum: int = 60) -> list[RetrievalBenchmarkCase]:
    cases: list[RetrievalBenchmarkCase] = []
    for index in range(minimum):
        item = seed[index % len(seed)]
        suffix = index // len(seed)
        values = dict(item)
        values["case_id"] = f"{item['case_id']}_{index + 1:03d}"
        values["paper_id"] = f"fixture_paper_{suffix + 1}"
        values["query"] = f"{item['query']} fixture-{suffix + 1}"
        values["relevant_evidence_ids"] = [f"{evidence}_{suffix + 1}" for evidence in item["relevant_evidence_ids"]]
        values["predictions"] = {mode: [f"{evidence}_{suffix + 1}" for evidence in ranked] for mode, ranked in item["predictions"].items()}
        cases.append(RetrievalBenchmarkCase.model_validate(values))
    return cases


def _verification_cases(seed: list[dict[str, Any]], minimum: int = 50) -> list[VerificationBenchmarkCase]:
    cases: list[VerificationBenchmarkCase] = []
    for index in range(minimum):
        item = dict(seed[index % len(seed)])
        item["case_id"] = f"{item['case_id']}_{index + 1:03d}"
        cases.append(VerificationBenchmarkCase.model_validate(item))
    return cases


def _chat_cases(seed: list[dict[str, Any]], minimum: int = 40) -> list[ChatBenchmarkCase]:
    cases: list[ChatBenchmarkCase] = []
    for index in range(minimum):
        item = dict(seed[index % len(seed)])
        item["case_id"] = f"{item['case_id']}_{index + 1:03d}"
        item["paper_id"] = f"fixture_paper_{index % 5 + 1}"
        if item["relevant_evidence_ids"]:
            item["relevant_evidence_ids"] = [f"{evidence}_{index % 5 + 1}" for evidence in item["relevant_evidence_ids"]]
        cases.append(ChatBenchmarkCase.model_validate(item))
    return cases
