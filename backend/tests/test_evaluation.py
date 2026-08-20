from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.evaluation.fixtures.loaders import load_manifest, load_manifest_model, load_smoke_cases
from backend.evaluation.metrics import boundary_f1, budget_compliance, citation_validity, classification_metrics, dedup_scores, ndcg_at_k, precision_at_k, recall_at_k, set_precision_recall_f1
from backend.evaluation.reports.writer import write_report
from backend.evaluation.runners.offline import run_all
from backend.evaluation.runners.structured import evaluate_artifacts, evaluate_claim_category, evaluate_sections, page_accuracy
from backend.evaluation.schemas import EvaluationReport, EvaluationRunMetadata, EvaluationStatus


class EvaluationMetricTests(unittest.TestCase):
    def test_rank_metrics_known_example(self) -> None:
        ranked = ["a", "x", "b"]
        self.assertAlmostEqual(precision_at_k(ranked, {"a", "b"}, 3), 2 / 3)
        self.assertEqual(recall_at_k(ranked, {"a", "b"}, 2), 0.5)
        self.assertAlmostEqual(ndcg_at_k(ranked, {"a", "b"}, 3), 0.9197207891)
        self.assertEqual(citation_validity(["ev_1", "fake"], ["ev_1"]), 0.5)

    def test_classification_and_structured_metrics(self) -> None:
        scores = classification_metrics(["A", "B", "A"], ["A", "A", "A"], labels=["A", "B"])
        self.assertAlmostEqual(scores["accuracy"], 2 / 3)
        self.assertEqual(boundary_f1([1, 4], [1, 5])["precision"], 0.5)
        self.assertEqual(set_precision_recall_f1(["a"], ["a", "b"])["recall"], 0.5)
        self.assertEqual(evaluate_sections(["METHOD", "RESULTS"], ["METHOD", "RESULTS"])["order_accuracy"], 1.0)
        self.assertEqual(evaluate_artifacts(["figure_1"], ["figure_1"])["f1"], 1.0)
        self.assertEqual(page_accuracy([1, 2], [1, 3]), 0.5)
        self.assertEqual(evaluate_claim_category(["F1 improves on Dataset A"], ["F1 improves on Dataset A"])["f1"], 1.0)
        self.assertEqual(dedup_scores([["a", "b"]], [["a", "b"]])["f1"], 1.0)
        self.assertEqual(budget_compliance({"queries": 2, "papers": 1}, {"queries": 3, "papers": 1}), 1.0)

    def test_invalid_metric_values_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            from backend.evaluation.schemas import EvaluationMetric
            EvaluationMetric(name="bad", value=float("nan"))


class EvaluationFixtureTests(unittest.TestCase):
    def test_manifest_and_minimum_offline_fixture_sizes(self) -> None:
        manifest = load_manifest()
        self.assertEqual(len(load_manifest_model().papers), len(manifest["papers"]))
        cases = load_smoke_cases()
        self.assertGreaterEqual(len(manifest["papers"]), 30)
        self.assertGreaterEqual(len(cases["retrieval"]), 50)
        self.assertGreaterEqual(len(cases["verification"]), 50)
        self.assertGreaterEqual(len(cases["chat"]), 30)

    def test_offline_runner_and_report_persistence(self) -> None:
        metadata = EvaluationRunMetadata(git_commit="fixture")
        results = run_all(metadata)
        self.assertEqual({result.component for result in results}, {"parsing", "research_extraction", "evidence_attribution", "retrieval", "verification", "paper_chat", "research_agent", "cross_paper_synthesis", "performance"})
        with tempfile.TemporaryDirectory() as directory:
            report = EvaluationReport(status=EvaluationStatus.PRELIMINARY, metadata=metadata, results=results)
            json_path, markdown_path = write_report(report, Path(directory))
            self.assertTrue(json_path.exists())
            self.assertTrue(markdown_path.exists())
            self.assertTrue((Path(directory) / "metadata.json").exists())
            self.assertEqual(json.loads(json_path.read_text())["status"], "PRELIMINARY")


if __name__ == "__main__":
    unittest.main()
