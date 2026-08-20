"""Small JSONL import/export helpers for human benchmark annotations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .schemas import BenchmarkPaperAnnotation, HumanEvaluationRecord


def load_annotations(path: Path) -> list[BenchmarkPaperAnnotation]:
    records: list[BenchmarkPaperAnnotation] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(BenchmarkPaperAnnotation.model_validate(json.loads(line)))
    return records


def load_human_evaluations(path: Path) -> list[HumanEvaluationRecord]:
    records: list[HumanEvaluationRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(HumanEvaluationRecord.model_validate(json.loads(line)))
    return records


def export_human_evaluations(records: Iterable[HumanEvaluationRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(record.model_dump_json() for record in records) + "\n", encoding="utf-8")
