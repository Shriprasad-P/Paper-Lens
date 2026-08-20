"""Load and expand the versioned benchmark fixtures without network access."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..schemas import BenchmarkManifest, ChatBenchmarkCase, DiscoveryBenchmarkCase, RetrievalBenchmarkCase, SynthesisBenchmarkCase, VerificationBenchmarkCase

DATASET_DIR = Path(__file__).parents[1] / "datasets"


def load_manifest() -> dict[str, Any]:
    return json.loads((DATASET_DIR / "manifest.json").read_text(encoding="utf-8"))


def load_manifest_model() -> BenchmarkManifest:
    return BenchmarkManifest.model_validate(load_manifest())


def load_smoke_cases() -> dict[str, list[Any]]:
    raw = json.loads((DATASET_DIR / "smoke_cases.json").read_text(encoding="utf-8"))
    return {
        "retrieval": _retrieval_cases(raw["retrieval"]),
        "verification": _verification_cases(raw["verification"]),
        "chat": _chat_cases(raw["chat"]),
        "research_agent": [DiscoveryBenchmarkCase.model_validate(item) for item in raw["research_agent"]],
        "synthesis": [SynthesisBenchmarkCase.model_validate(item) for item in raw["synthesis"]],
    }


def _retrieval_cases(seed: list[dict[str, Any]], minimum: int = 50) -> list[RetrievalBenchmarkCase]:
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


def _chat_cases(seed: list[dict[str, Any]], minimum: int = 30) -> list[ChatBenchmarkCase]:
    cases: list[ChatBenchmarkCase] = []
    for index in range(minimum):
        item = dict(seed[index % len(seed)])
        item["case_id"] = f"{item['case_id']}_{index + 1:03d}"
        item["paper_id"] = f"fixture_paper_{index % 5 + 1}"
        if item["relevant_evidence_ids"]:
            item["relevant_evidence_ids"] = [f"{evidence}_{index % 5 + 1}" for evidence in item["relevant_evidence_ids"]]
        cases.append(ChatBenchmarkCase.model_validate(item))
    return cases
