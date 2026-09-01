from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.evaluation.fixtures.loaders import load_frozen_smoke_predictions, load_manifest_model, load_paper_annotations
from backend.evaluation.metrics import (
    aggregate_retrieval_metrics,
    citation_precision_recall,
    false_rejection_rate,
    false_support_rate,
    graded_ndcg_at_k,
    numeric_fidelity_strict,
)
from backend.evaluation.provenance import EvaluationDataError, annotation_file_hashes, build_prediction_envelope, combined_annotation_hash, config_hash, embedding_provenance, generation_provenance, load_prediction_envelope, real_corpus_hash, sha256_bytes, sha256_json
from backend.evaluation.provisional import PROVISIONAL_CONTRACT, build_provisional_dev_report, embedding_architecture_audit, embedding_runtime_audit, generation_provider_audit, local_runtime_audit, prompt_hashes, require_dev_rows, render_markdown
from backend.evaluation.reports.writer import write_report
from backend.evaluation.real_runner import retrieval_request
from backend.evaluation.review_cli import apply_review, refresh_annotation_manifest
from backend.evaluation.schemas import EvaluationMetric, EvaluationReport, EvaluationResult, EvaluationRunMetadata, EvaluationStatus, RetrievalBenchmarkCase, VerificationBenchmarkCase, VerificationStatus
from backend.evaluation.review_progress import summarize_review_progress
from backend.evaluation.validation import require_resolved_cases, require_reviewed_cases, validate_frozen_rankings, validate_manifest, validate_paper_annotations, validate_real_corpus_manifest, validate_real_retrieval_annotations, validate_retrieval_cases, validate_reviewed_cases, validate_verification_cases


class Phase15MetricTests(unittest.TestCase):
    def test_retrieval_bundle_and_graded_ndcg(self) -> None:
        bundle = aggregate_retrieval_metrics([["a", "b"], ["x", "b"]], [{"a"}, {"b"}], graded=[{"a": 3, "b": 1}, {"b": 3}], ks=(1, 3))
        self.assertEqual(bundle["recall_at_1"], 0.5)
        self.assertGreater(graded_ndcg_at_k(["b", "a"], {"a": 3, "b": 1}, 2), 0.0)

    def test_safety_metrics_and_strict_numeric_fidelity(self) -> None:
        self.assertEqual(false_support_rate(["SUPPORTED", "UNSUPPORTED"], ["SUPPORTED", "SUPPORTED"]), 1.0)
        self.assertEqual(false_rejection_rate(["SUPPORTED", "UNSUPPORTED"], ["UNVERIFIED", "UNSUPPORTED"]), 1.0)
        self.assertEqual(numeric_fidelity_strict(["0.51 F1"], ["F1 is 0.51"]), 1.0)
        self.assertEqual(numeric_fidelity_strict(["0.52 F1"], ["F1 is 0.51"]), 0.0)
        self.assertEqual(citation_precision_recall(["e1", "fake"], ["e1"])["precision"], 0.5)


class Phase15ProvenanceTests(unittest.TestCase):
    def test_checked_in_prediction_envelope_is_hash_valid(self) -> None:
        envelope = load_frozen_smoke_predictions()
        self.assertEqual(envelope.prediction_hash, sha256_json(envelope.predictions))

    def test_prediction_hash_tampering_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "predictions.json"
            envelope = build_prediction_envelope({"case": {"value": 1}}, dataset_hash="dataset")
            path.write_text(json.dumps({**envelope.as_dict(), "predictions": {"case": {"value": 2}}}), encoding="utf-8")
            with self.assertRaises(EvaluationDataError):
                load_prediction_envelope(path)

    def test_validated_report_requires_immutable_provenance(self) -> None:
        metadata = EvaluationRunMetadata(git_commit="abc", dataset_hash="d", annotation_hash="a", prediction_hash="p")
        with self.assertRaises(ValueError):
            EvaluationReport(status=EvaluationStatus.VALIDATED, metadata=metadata, results=[])
        result = EvaluationResult(component="retrieval", metadata=metadata, metrics=[EvaluationMetric(name="recall_at_5", value=1.0, count=1, status=EvaluationStatus.VALIDATED)])
        report = EvaluationReport(status=EvaluationStatus.VALIDATED, metadata=metadata, results=[result])
        self.assertEqual(report.status, EvaluationStatus.VALIDATED)

    def test_provider_and_embedding_provenance_are_stable(self) -> None:
        embedding = embedding_provenance(
            provider="local", model="e5-small", revision="rev-1", dimension=384,
            normalization="l2", distance_metric="cosine", chunk_strategy="evidence",
            document_hash="a" * 64, evidence_id="ev_1",
        )
        self.assertEqual(len(embedding["embedding_config_hash"]), 64)
        generation = generation_provenance(
            provider="openai-compatible", model="model", revision="rev-1",
            temperature=0, top_p=1, max_output_tokens=512,
            prompt_versions={"chat": "v1"}, retry_policy={"max_retries": 2}, validation_config={"strict": True},
        )
        self.assertEqual(generation["generation_config_hash"], config_hash(generation["generation_config"]))

    def test_annotation_hashes_cover_exact_ledger_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "retrieval.jsonl").write_bytes(b'{"case_id":"r1"}\n')
            (root / "verification.jsonl").write_bytes(b'{"case_id":"v1"}\n')
            (root / "chat.jsonl").write_bytes(b'{"case_id":"c1"}\n')
            (root / "agent.jsonl").write_bytes(b'{"case_id":"a1"}\n')
            hashes = annotation_file_hashes(root)
            self.assertEqual(set(hashes), {"retrieval.jsonl", "verification.jsonl", "chat.jsonl", "agent.jsonl"})
            self.assertEqual(combined_annotation_hash(root), sha256_bytes(b"".join((root / name).read_bytes() for name in ("retrieval.jsonl", "verification.jsonl", "chat.jsonl", "agent.jsonl"))))

    def test_retrieval_input_excludes_gold_annotations_and_ranking_shape_is_frozen(self) -> None:
        case = {
            "case_id": "r1", "paper_id": "p", "document_id": "d", "query": "method", "split": "dev",
            "relevant_evidence_ids": ["gold"], "graded_relevance": {"gold": 3}, "reviewer_notes": ["private"],
        }
        request = retrieval_request(case)
        self.assertNotIn("relevant_evidence_ids", request)
        self.assertNotIn("graded_relevance", request)
        self.assertTrue(validate_frozen_rankings({"r1": ["e1", "e2"]}, ["r1"]).valid)
        self.assertFalse(validate_frozen_rankings({"r1": ["e1", "e1"]}, ["r1"]).valid)


class Phase15ValidationTests(unittest.TestCase):
    def test_current_inputs_are_explicitly_preliminary(self) -> None:
        manifest = load_manifest_model()
        self.assertTrue(validate_manifest(manifest).valid)
        annotation_report = validate_paper_annotations(manifest, load_paper_annotations())
        self.assertTrue(annotation_report.valid)
        self.assertIn("DRAFT", annotation_report.counts)

    def test_duplicate_and_unknown_evidence_fail_closed(self) -> None:
        cases = [RetrievalBenchmarkCase(case_id="r1", paper_id="p", query="q", category="method", relevant_evidence_ids=["e1"], annotation_notes="review") , RetrievalBenchmarkCase(case_id="r1", paper_id="p", query="q", category="method", relevant_evidence_ids=["e2"])]
        report = validate_retrieval_cases(cases, paper_ids=["p"], evidence_ids_by_paper={"p": ["e1"]})
        self.assertFalse(report.valid)
        verification = [VerificationBenchmarkCase(case_id="v1", paper_id="p", claim="claim", allowed_evidence_ids=["bad"], gold_status=VerificationStatus.SUPPORTED)]
        self.assertFalse(validate_verification_cases(verification, paper_ids=["p"], evidence_ids_by_paper={"p": ["e1"]}).valid)

    def test_real_corpus_manifest_requires_paper_separated_splits_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "paper.pdf"
            body = b"%PDF-1.7\nreal snapshot"
            pdf.write_bytes(body)
            paper = {
                "paper_id": "p1", "source_identifier": "1234.5678", "version": 1,
                "versioned_identifier": "1234.5678v1", "source_pdf_sha256": sha256_bytes(body),
                "paperlens_source_id": "paper_1", "paperlens_document_id": "doc_1",
                "normalized_document_hash": "a" * 64, "parser_version": "1.0",
                "ingestion_version": "phase14-production", "evidence_registry_version": "v1",
                "evidence_count": 1, "ingestion_status": "COMPLETED", "page_count": 1,
                "pdf_path": "paper.pdf", "split": "dev",
            }
            manifest = {"corpus_schema_version": "1.0", "benchmark_version": "v2", "dataset_version": "v2", "corpus_kind": "real_public_pdf_snapshots", "splits": {"dev": ["p1"], "final": ["p1"]}, "papers": [paper]}
            manifest["corpus_hash"] = real_corpus_hash(manifest)
            self.assertFalse(validate_real_corpus_manifest(manifest, corpus_root=root).valid)
            manifest["splits"] = {"dev": [], "final": ["p1"]}
            paper["split"] = "final"
            manifest["corpus_hash"] = real_corpus_hash(manifest)
            self.assertFalse(validate_real_corpus_manifest(manifest, corpus_root=root).valid)

    def test_real_retrieval_annotations_bind_to_frozen_document_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = {"id": "e1", "document_id": "doc_1", "source_text": "method"}
            (root / "evidence.jsonl").write_text(json.dumps(evidence) + "\n", encoding="utf-8")
            case = RetrievalBenchmarkCase(case_id="r1", paper_id="p1", document_id="doc_1", query="method", category="method", relevant_evidence_ids=["e1"])
            manifest = {"papers": [{"paper_id": "p1", "paperlens_document_id": "doc_1"}]}
            self.assertTrue(validate_real_retrieval_annotations([case], manifest=manifest, corpus_root=root).valid)
            bad = case.model_copy(update={"relevant_evidence_ids": ["missing"]})
            self.assertFalse(validate_real_retrieval_annotations([bad], manifest=manifest, corpus_root=root).valid)

    def test_reviewed_case_requires_reviewer_metadata_and_cli_records_it(self) -> None:
        case = RetrievalBenchmarkCase(
            case_id="r1", paper_id="p", query="q", category="method",
            relevant_evidence_ids=["e1"], annotation_status="REVIEWED",
        )
        self.assertFalse(validate_reviewed_cases([case]).valid)
        report = validate_retrieval_cases([case], paper_ids=["p"], evidence_ids_by_paper={"p": ["e1"]})
        self.assertFalse(report.valid)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "retrieval.jsonl"
            path.write_text(json.dumps(case.model_copy(update={"annotation_status": "DRAFT"}).model_dump(mode="json")) + "\n", encoding="utf-8")
            reviewed = apply_review(path, "r1", reviewer_id="reviewer_local", notes="Confirmed against the cited passage.")
            self.assertEqual(reviewed["annotation_status"], "REVIEWED")
            self.assertEqual(reviewed["reviewer_id"], "reviewer_local")
            change_log = path.parent / "change_log.jsonl"
            self.assertTrue(change_log.is_file())
            change_record = json.loads(change_log.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(change_record["item_id"], "r1")
            self.assertTrue(change_record["reason"])
            checked = RetrievalBenchmarkCase.model_validate(reviewed)
            self.assertTrue(validate_retrieval_cases([checked], paper_ids=["p"], evidence_ids_by_paper={"p": ["e1"]}).valid)
            self.assertTrue(require_reviewed_cases([checked]))

    def test_reviewed_cases_require_human_notes_and_frozen_manifest_rejects_edits(self) -> None:
        reviewed = RetrievalBenchmarkCase(
            case_id="r1", paper_id="p", query="q", category="method",
            relevant_evidence_ids=["e1"], annotation_status="REVIEWED",
            reviewer_id="reviewer", reviewed_at="2026-08-29T00:00:00+00:00",
        )
        report = validate_reviewed_cases([reviewed])
        self.assertFalse(report.valid)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = {"status": "DRAFT", "annotation_hashes": {}}
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            ledgers = {
                "retrieval.jsonl": reviewed.model_dump_json(),
                "verification.jsonl": json.dumps({"case_id": "v1", "annotation_status": "DRAFT"}),
                "chat.jsonl": json.dumps({"case_id": "c1", "annotation_status": "DRAFT"}),
                "agent.jsonl": json.dumps({"case_id": "a1", "annotation_status": "DRAFT"}),
            }
            for filename, content in ledgers.items():
                (root / filename).write_text(content + "\n", encoding="utf-8")
            refreshed = refresh_annotation_manifest(root)
            self.assertEqual(refreshed["reviewed_counts"]["retrieval"], 1)
            self.assertEqual(refreshed["review_status"], "IN_PROGRESS")
            self.assertEqual(len(refreshed["benchmark_hash"]), 64)
            with self.assertRaises(EvaluationDataError):
                refresh_annotation_manifest(root, freeze=True)
            refreshed["status"] = "VALIDATED"
            (root / "manifest.json").write_text(json.dumps(refreshed), encoding="utf-8")
            with self.assertRaises(EvaluationDataError):
                apply_review(root / "retrieval.jsonl", "r1", reviewer_id="reviewer", notes="second pass")

    def test_valid_exclusion_is_resolved_but_not_publishable_review(self) -> None:
        excluded = {
            "case_id": "r1",
            "annotation_status": "EXCLUDED",
            "reviewer_id": "reviewer_01",
            "reviewed_at": "2026-08-29T00:00:00+00:00",
            "reviewer_notes": ["The source evidence is missing from the frozen export."],
            "exclusion_reason": "source evidence missing",
        }
        self.assertTrue(require_resolved_cases([excluded]))
        self.assertFalse(validate_reviewed_cases([excluded]).valid)

    def test_review_progress_counts_draft_rows_and_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for filename in ("retrieval.jsonl", "verification.jsonl", "chat.jsonl", "agent.jsonl"):
                root.joinpath(filename).write_text(json.dumps({"case_id": filename, "annotation_status": "DRAFT"}) + "\n", encoding="utf-8")
            summary = summarize_review_progress(root)
            self.assertEqual(summary["total_cases"], 4)
            self.assertEqual(summary["resolved_cases"], 0)
            self.assertEqual(summary["checkpoints"]["25"]["status"], "PENDING")


class Phase15ProvisionalTests(unittest.TestCase):
    def test_provisional_contract_is_explicit_and_markdown_prominent(self) -> None:
        self.assertEqual(PROVISIONAL_CONTRACT, {
            "evaluation_status": "PROVISIONAL",
            "annotation_status": "DRAFT",
            "human_reviewers": 0,
            "publishable": False,
            "publishable_quality_claims": False,
            "final_dataset_used": False,
            "tuning": "NONE",
            "split": "DEV",
        })
        markdown = render_markdown({
            **PROVISIONAL_CONTRACT,
            "counts": {"retrieval": 1, "verification": 1, "chat": 1, "agent": 1},
            "retrieval": {lane: {"metrics": None} for lane in ("BM25", "Semantic", "Hybrid")},
            "embedding": {"status": "NOT_CONFIGURED", "reason": "test"},
            "provider": {"status": "NOT_CONFIGURED", "provider": "none", "model": None},
            "corpus_hash": "c", "benchmark_hash": "b", "prediction_hashes": {},
            "provenance": {"offline_reproduction": "PASS"}, "tuning_performed": "NONE",
            "final_touched": False, "phase15e_p": "NOT CLOSED", "phase15_overall": "NOT CLOSED",
        })
        self.assertIn("PROVISIONAL DEV EVALUATION", markdown)
        self.assertIn("NOT PUBLISHABLE", markdown)
        self.assertIn("NOT FINAL", markdown)

    def test_provisional_guard_rejects_explicit_final_and_non_draft(self) -> None:
        with self.assertRaises(EvaluationDataError):
            require_dev_rows([{"case_id": "final-1", "split": "final", "annotation_status": "DRAFT"}], kind="retrieval")
        with self.assertRaises(EvaluationDataError):
            require_dev_rows([{"case_id": "reviewed-1", "split": "dev", "annotation_status": "REVIEWED"}], kind="retrieval")

    def test_embedding_audit_excludes_hash_fallback(self) -> None:
        audit = embedding_architecture_audit({"provider": "none", "model": "hash-v1"})
        self.assertEqual(audit["status"], "NOT_CONFIGURED")
        self.assertEqual(audit["run_eligibility"], "BLOCKED_WITHOUT_REAL_PROVIDER")
        self.assertIn("hash-v1", audit["fallback"])

    def test_prompt_and_runtime_audits_are_deterministic_and_secret_free(self) -> None:
        prompts = prompt_hashes()
        self.assertEqual(set(prompts["hashes"]), {"verification", "chat", "agent_planning", "agent_synthesis"})
        self.assertTrue(all(len(value) == 64 for value in prompts["hashes"].values() if value))
        runtime = embedding_runtime_audit()
        self.assertEqual(runtime["selected_device"], "NOT_RUN")
        generation = generation_provider_audit()
        self.assertIn("provider_available", generation)
        self.assertFalse(generation["secrets_stored"])

    def test_local_runtime_audit_is_fail_closed_and_secret_free(self) -> None:
        runtime = local_runtime_audit()
        self.assertIn("external_runtime", runtime)
        self.assertIn("local_model_candidates", runtime)
        self.assertIsNone(runtime["embedding_model_selected"])
        self.assertEqual(runtime["local_server"]["bind_host"], "127.0.0.1")
        self.assertEqual(runtime["model_inference"], {"embedding": "NOT_RUN", "generation": "NOT_RUN"})
        self.assertNotIn("AI_API_KEY", json.dumps(runtime))

    def test_real_provisional_report_is_dev_only_and_preserves_draft_manifest(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            prediction_path = Path(directory) / "phase15e-bm25-dev.json"
            database_path = Path(directory) / "paperlens-test.db"
            from backend.app.db.database import SQLDatabase
            SQLDatabase(f"sqlite:///{database_path}", create_schema=True)
            report = build_provisional_dev_report(
                corpus_manifest=root / "backend/evaluation/datasets/corpus/manifest.json",
                annotations=root / "backend/evaluation/datasets/real_annotations",
                database_url=f"sqlite:///{database_path}",
                prediction_path=prediction_path,
            )
            self.assertEqual({report[key] for key in ("evaluation_status", "annotation_status", "human_reviewers", "publishable", "split")}, {"PROVISIONAL", "DRAFT", 0, False, "DEV"})
            self.assertEqual(report["retrieval"]["Semantic"]["status"], "NOT_RUN")
            self.assertEqual(report["retrieval"]["Hybrid"]["status"], "NOT_RUN")
            self.assertEqual(report["phase15e_s"], "NOT CLOSED")
            self.assertIn("runtime_enablement", report)
            self.assertIn("local_generation", report)
            frozen = load_prediction_envelope(prediction_path)
            self.assertTrue(frozen.predictions)
            self.assertEqual({value.get("split") for value in frozen.predictions.values()}, {"dev"})


if __name__ == "__main__":
    unittest.main()
