from __future__ import annotations

import unittest

import httpx

from fastapi.testclient import TestClient

from backend.app.comparison.service import PaperComparisonService
from backend.app.db.database import SQLDatabase
from backend.app.db.database import EvidenceRecord
from backend.app.document.normalizer import DocumentNormalizer
from backend.app.evidence.registry import EvidenceRegistry
from backend.app.models.document import (
    EvidenceType,
    ExperimentIR,
    PaperEquation,
    PaperFigure,
    PaperIR,
    PaperReference,
    PaperTable,
    ProblemIR,
    ResearchClaim,
    ResultIR,
    StatementOrigin,
)
from backend.app.models.paper import PaperMetadata
from backend.app.ingestion.raw import ParsedPaper, RawParagraph, RawSection
from backend.app.retrieval.embeddings import HashEmbeddingProvider, OllamaEmbeddingProvider
from backend.app.retrieval.evaluation import RetrievalCase, evaluate_retriever
from backend.app.retrieval.hybrid import HybridEvidenceRetriever, SemanticEvidenceRetriever
from backend.app.chat.retrieval import BM25EvidenceRetriever
from backend.app.main import create_app


def _metadata(arxiv_id: str, title: str) -> PaperMetadata:
    return PaperMetadata(
        arxiv_id=arxiv_id,
        title=title,
        authors=["Author"],
        abstract="A fixture abstract.",
        source_url=f"https://arxiv.org/abs/{arxiv_id}",
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}.pdf",
    )


def _save_paper(db: SQLDatabase, paper_id: str, arxiv_id: str, title: str, *, artifacts: bool = False) -> str:
    metadata = _metadata(arxiv_id, title)
    db.create_placeholder(paper_id=paper_id, source_identity=f"arxiv:{arxiv_id}", arxiv_id=arxiv_id)
    db.save_metadata(paper_id, metadata, status="COMPLETED")
    parsed = ParsedPaper(
        parser_name="fixture",
        page_count=2,
        sections=[RawSection(title="Method", level=1, order=0, paragraphs=[RawParagraph(text="A method uses attention and retrieval.", page=1)])],
        figures=[PaperFigure(id="figure_001", label="Figure 1", caption="Attention flow", page=1)] if artifacts else [],
        tables=[PaperTable(id="table_001", label="Table 1", caption="Scores", raw_text="Model | F1\nOurs | 0.9", headers=["Model", "F1"], rows=[["Ours", "0.9"]], page=1)] if artifacts else [],
        equations=[PaperEquation(id="equation_001", raw_text="y = f(x)", label="1", page=1)] if artifacts else [],
        references=[PaperReference(id="reference_001", order=0, raw_text="Prior work 1706.03762", arxiv_id="1706.03762", year=2017)] if artifacts else [],
    )
    document = DocumentNormalizer().normalize(parsed, paper_id=paper_id, metadata=metadata, source_hash=f"hash-{paper_id}")
    db.replace_document(document, EvidenceRegistry().build_for_document(document))
    return document.id


class Phase8ArtifactTests(unittest.TestCase):
    def test_artifacts_have_typed_registry_records_and_persist(self) -> None:
        db = SQLDatabase("sqlite:///:memory:")
        _save_paper(db, "paper_artifacts", "1234.56789", "Artifacts", artifacts=True)
        document = db.get_document("paper_artifacts")
        self.assertIsNotNone(document)
        assert document is not None
        self.assertEqual(len(document.figures), 1)
        self.assertEqual(document.tables[0].rows, [["Ours", "0.9"]])
        self.assertEqual(document.figures[0].evidence_ids, ["ev_0002"])
        records = db.get_evidence_for_document("paper_artifacts", document.id)
        self.assertEqual([record.evidence_type for record in records], [EvidenceType.PARAGRAPH, EvidenceType.FIGURE_CAPTION, EvidenceType.TABLE, EvidenceType.EQUATION, EvidenceType.REFERENCE])
        reader = TestClient(create_app(database=db)).get("/api/papers/paper_artifacts/reader")
        self.assertEqual(reader.status_code, 200)
        self.assertEqual(reader.json()["document"]["figure_count"], 1)
        self.assertEqual(reader.json()["document"]["tables"][0]["headers"], ["Model", "F1"])
        self.assertEqual(TestClient(create_app(database=db)).get(f"/api/papers/paper_artifacts/documents/{document.id}/figures/figure_001").status_code, 404)


class Phase8RetrievalTests(unittest.IsolatedAsyncioTestCase):
    async def test_ollama_embeddings_are_real_provider_vectors_and_normalized(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/embed")
            self.assertEqual(request.headers["Authorization"], "Bearer local-paperlens")
            return httpx.Response(200, json={"embeddings": [[3.0, 4.0], [0.0, 2.0]]})

        provider = OllamaEmbeddingProvider(
            model="nomic-embed-text",
            dimension=0,
            version="ollama-test-v1",
            api_key="local-paperlens",
            transport=httpx.MockTransport(handler),
        )
        vectors = await provider.embed_texts(["one", "two"])
        self.assertEqual(provider.dimension, 2)
        self.assertEqual(vectors[0], [0.6, 0.8])
        self.assertEqual(vectors[1], [0.0, 1.0])

    async def test_semantic_cache_is_reused_and_evaluation_is_deterministic(self) -> None:
        db = SQLDatabase("sqlite:///:memory:")
        document_id = _save_paper(db, "paper_semantic", "2234.56789", "Semantic")
        class CountingHashProvider(HashEmbeddingProvider):
            def __init__(self) -> None:
                super().__init__(dimension=32)
                self.calls = 0

            async def embed_texts(self, texts: list[str]) -> list[list[float]]:
                self.calls += 1
                return await super().embed_texts(texts)

            async def embed_query(self, query: str) -> list[float]:
                self.calls += 1
                return await super().embed_query(query)

        provider = CountingHashProvider()
        retriever = SemanticEvidenceRetriever(db, provider, top_k=3)
        first = await retriever.retrieve_async("paper_semantic", "attention retrieval", limit=3)
        first_calls = provider.calls
        second = await retriever.retrieve_async("paper_semantic", "attention retrieval", limit=3)
        self.assertEqual([item.evidence_id for item in first], [item.evidence_id for item in second])
        self.assertEqual(provider.calls, first_calls + 1, "unchanged evidence should reuse cached document vectors")
        self.assertEqual(db.get_embeddings("paper_semantic", document_id, provider.model, provider.version).keys(), {"ev_0001"})
        with db.session_factory.begin() as session:
            record = session.get(EvidenceRecord, "ev_0001")
            assert record is not None
            record.source_text = "A changed retrieval passage about attention."
        await retriever.retrieve_async("paper_semantic", "changed retrieval", limit=3)
        self.assertEqual(provider.calls, first_calls + 3, "changed evidence should trigger one fresh text embedding")
        case = [RetrievalCase(question="attention", relevant_evidence_ids=frozenset({"ev_0001"}))]
        bm25 = BM25EvidenceRetriever(db)
        hybrid = HybridEvidenceRetriever(db, retriever)
        hybrid_items = await hybrid.retrieve_async("paper_semantic", "attention", limit=1)
        for name, retrieve in (
            ("bm25", lambda query, limit: [item.evidence_id for item in bm25.retrieve("paper_semantic", query, limit)]),
            ("semantic", lambda query, limit: [item.evidence_id for item in first]),
            ("hybrid", lambda query, limit: [item.evidence_id for item in hybrid_items]),
        ):
            metrics = evaluate_retriever(case, retrieve, k=1)
            self.assertEqual(metrics.recall_at_k, 1.0, name)
            self.assertEqual(metrics.mrr, 1.0, name)

    async def test_hybrid_fuses_lexical_and_semantic_without_cross_document_leakage(self) -> None:
        db = SQLDatabase("sqlite:///:memory:")
        _save_paper(db, "paper_hybrid", "3234.56789", "Hybrid")
        _save_paper(db, "paper_other", "5234.56789", "Other")
        semantic = SemanticEvidenceRetriever(db, HashEmbeddingProvider(dimension=32), top_k=4)
        results = await HybridEvidenceRetriever(db, semantic).retrieve_async("paper_hybrid", "attention", limit=4)
        self.assertTrue(results)
        self.assertTrue(all(item.paper_id == "paper_hybrid" and item.document_id for item in results))
        self.assertTrue(all(item.retrieval_method == "hybrid-rrf-v1" for item in results))


class Phase8WorkspaceComparisonTests(unittest.TestCase):
    def test_workspace_persistence_comparison_evidence_identity_and_citation_graph(self) -> None:
        db = SQLDatabase("sqlite:///:memory:")
        _save_paper(db, "paper_a", "4234.56789", "Paper A", artifacts=True)
        _save_paper(db, "paper_b", "1706.03762", "Paper B")
        analysis_a = PaperIR(
            paper_id="paper_a", document_id=db.get_document("paper_a").id, metadata=_metadata("4234.56789", "Paper A"),
            problem=ProblemIR(id="problem", statement="Shared problem", evidence_ids=["ev_0001"], origin=StatementOrigin.AUTHOR_EXPLICIT),
            experiments=[ExperimentIR(id="exp", name="Main", datasets=["Dataset A"], metrics=["F1"], evidence_ids=["ev_0001"], origin=StatementOrigin.AUTHOR_EXPLICIT)],
            results=[ResultIR(id="result", statement="F1 0.9", metric="F1", value=0.9, evidence_ids=["ev_0001"], origin=StatementOrigin.AUTHOR_EXPLICIT)],
        )
        analysis_b = analysis_a.model_copy(update={"paper_id": "paper_b", "document_id": db.get_document("paper_b").id, "metadata": _metadata("1706.03762", "Paper B")})
        db.save_analysis(analysis_a, cache_key="cache-a", provider="fixture", model="fixture", prompt_version="v1", schema_version="v1")
        db.save_analysis(analysis_b, cache_key="cache-b", provider="fixture", model="fixture", prompt_version="v1", schema_version="v1")
        workspace = db.create_workspace("Compare")
        other_workspace = db.create_workspace("Another")
        db.add_workspace_paper(workspace.id, "paper_a")
        db.add_workspace_paper(workspace.id, "paper_b")
        db.add_workspace_paper(other_workspace.id, "paper_a")
        self.assertEqual(len(db.get_workspace_papers(workspace.id)), 2)
        self.assertEqual([item.paper_id for item in db.get_workspace_papers(other_workspace.id)], ["paper_a"])
        comparison = PaperComparisonService(db).compare(["paper_a", "paper_b"])
        datasets = next(item for item in comparison.dimensions if item.name == "Datasets")
        self.assertEqual(datasets.comparability.value, "COMPARABLE")
        self.assertEqual(datasets.entries[0].paper_id, "paper_a")
        self.assertEqual(datasets.entries[0].evidence_ids, ["ev_0001"])
        graph = TestClient(create_app(database=db)).get("/api/papers/paper_a/citation-graph")
        self.assertEqual(graph.status_code, 200)
        self.assertTrue(any(edge["target_node_id"] == "paper:paper_b" for edge in graph.json()["edges"]))
        client = TestClient(create_app(database=db))
        created = client.post("/api/workspaces", json={"name": "API workspace"})
        self.assertEqual(created.status_code, 201)
        workspace_id = created.json()["id"]
        self.assertEqual(client.post(f"/api/workspaces/{workspace_id}/papers/paper_a").status_code, 200)


if __name__ == "__main__":
    unittest.main()
