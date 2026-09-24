"""Focused Phase 18 resolver, provider, and Archify contract tests."""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone

import httpx

from backend.app.core.config import Settings
from backend.app.db.database import SQLDatabase
from backend.app.ingestion.resolver import PaperInputType, classify_paper_input, parse_structured_citation
from backend.app.models.provider import ProviderConfigPublic, ProviderType
from backend.app.provider_config import decrypt_secret, encrypt_secret, mask_secret, test_provider_connection
from backend.app.visualization.archify import ArchifyAdapterError, PaperVisualGraph, render_archify_ir, to_archify_ir, validate_archify_ir, validate_paper_visual_graph


class Phase18ReconstructionTests(unittest.TestCase):
    def test_input_classifier_covers_identifiers_and_citation_formats(self) -> None:
        self.assertEqual(classify_paper_input("arXiv:1706.03762").input_type, PaperInputType.ARXIV_ID)
        self.assertEqual(classify_paper_input("https://doi.org/10.1145/3368089.3409741").input_type, PaperInputType.DOI)
        self.assertEqual(classify_paper_input("https://pubmed.ncbi.nlm.nih.gov/12345678/").input_type, PaperInputType.PMID)
        self.assertEqual(classify_paper_input("@article{key, title={A Safe Paper}, author={Ada Lovelace}}").input_type, PaperInputType.BIBTEX)
        self.assertEqual(classify_paper_input("TY  - JOUR\nTI  - A Safe Paper\nER  -").input_type, PaperInputType.RIS)
        self.assertEqual(classify_paper_input("Lovelace, A. (2024). A Safe Paper. Journal of Tests.").input_type, PaperInputType.CITATION_TEXT)

    def test_structured_citation_is_deterministic_and_never_invents(self) -> None:
        parsed = parse_structured_citation("@article{key, title={A Safe Paper}, author={Ada Lovelace and Alan Turing}, year={2024}, doi={10.1234/example}}", PaperInputType.BIBTEX)
        self.assertEqual(parsed["title"], "A Safe Paper")
        self.assertEqual(parsed["year"], 2024)
        self.assertEqual(parsed["authors"], ["Ada Lovelace", "Alan Turing"])

    def test_provider_secret_is_encrypted_and_owner_bound(self) -> None:
        settings = Settings(database_url="sqlite:///:memory:")
        encrypted = encrypt_secret(settings, "sk-test-secret")
        self.assertNotIn("sk-test-secret", encrypted)
        self.assertEqual(decrypt_secret(settings, encrypted), "sk-test-secret")
        self.assertEqual(mask_secret("sk-test-secret"), "sk-t••••••••cret")
        db = SQLDatabase("sqlite:///:memory:")
        db.create_user("owner_a", "owner-a@example.com", "hash")
        db.create_user("owner_b", "owner-b@example.com", "hash")
        db.save_provider_config(config_id="provider_a", owner_id="owner_a", provider_type=ProviderType.OLLAMA.value, display_name="Local", base_url="http://127.0.0.1:11434", generation_model="qwen3:4b", embedding_model=None, encrypted_secret=encrypted, secret_hint=mask_secret("sk-test-secret"), enabled=True)
        self.assertEqual(len(db.list_provider_configs("owner_a")), 1)
        self.assertEqual(db.list_provider_configs("owner_b"), [])
        self.assertIsNone(db.get_provider_config("provider_a", "owner_b"))

    def test_provider_probe_checks_generation_and_embeddings(self) -> None:
        calls: list[str] = []
        now = datetime.now(timezone.utc)

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"name": "qwen3:4b"}]})
            if request.url.path == "/api/chat":
                return httpx.Response(200, json={"message": {"content": '{"ok":true}'}})
            if request.url.path == "/api/embed":
                return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3, 0.4]]})
            return httpx.Response(404)

        config = ProviderConfigPublic(
            id="provider_probe", provider_type=ProviderType.OLLAMA, display_name="Probe",
            base_url="http://127.0.0.1:11434", generation_model="qwen3:4b", embedding_model="nomic-embed-text",
            secret_configured=False, masked_secret=None, enabled=True, last_tested_at=None,
            last_test_status=None, created_at=now, updated_at=now,
        )
        message = asyncio.run(test_provider_connection(config, "", transport=httpx.MockTransport(handler)))
        self.assertIn("4 dimensions", message)
        self.assertEqual(calls, ["/api/tags", "/api/chat", "/api/embed"])

    def test_archify_adapter_requires_evidence_for_factual_graph(self) -> None:
        graph = PaperVisualGraph(id="g", type="ARCHITECTURE", title="Method", source_document_id="doc", nodes=[{"id": "a", "label": "Input", "evidence_ids": ["ev_1"]}, {"id": "b", "label": "Output", "evidence_ids": ["ev_2"]}], edges=[{"id": "e", "source": "a", "target": "b", "label": "feeds", "evidence_ids": ["ev_3"]}])
        validate_paper_visual_graph(graph)
        payload = to_archify_ir(graph)
        self.assertEqual(payload["archify"]["version"], "2.16.0")
        self.assertEqual(payload["paperlens"]["source_document_id"], "doc")
        self.assertTrue(validate_archify_ir(payload)["ok"])
        rendered = render_archify_ir(payload)
        self.assertIn("<svg", rendered)
        self.assertIn("Archify", rendered)
        with self.assertRaises(ArchifyAdapterError):
            validate_paper_visual_graph(graph.model_copy(update={"nodes": [{"id": "a", "label": "Input"}, {"id": "b", "label": "Output", "evidence_ids": ["ev_2"]}]}))


if __name__ == "__main__":
    unittest.main()
