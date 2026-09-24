from __future__ import annotations

import unittest

from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.ai.provider import UnavailableAIProvider
from backend.app.core.config import Settings
from backend.app.extraction.service import ResearchExtractionService
from backend.app.interactive.assembler import assemble_interactive_paper, interactive_cache_key, analysis_fingerprint
from backend.app.interactive.service import InteractivePaperService
from backend.app.interactive.validator import sanitize_diagram, validate_paper
from backend.app.main import create_app
from backend.app.models.interactive_paper import (
    BlockSimplification,
    BlockStatus,
    BlockType,
    DiagramType,
    EquationExplanation,
    EquationTerm,
    GenerationMode,
    InteractivePaper,
    InteractivePaperBlock,
    INTERACTIVE_SCHEMA_VERSION,
    VisualDiagram,
    VisualEdge,
    VisualNode,
)
from backend.tests.test_extraction import FakeProvider, _document_fixture


class InteractiveFakeProvider(FakeProvider):
    def __init__(self, *, malformed: bool = False, html: bool = False, bad_evidence: bool = False):
        super().__init__()
        self.malformed = malformed
        self.html = html
        self.bad_evidence = bad_evidence

    async def generate_structured(self, prompt: str, schema):
        if schema is BlockSimplification:
            self.calls += 1
            if self.malformed:
                raise ValueError("malformed provider json")
            if self.html:
                return BlockSimplification(
                    simplified_explanation="<script>alert(1)</script>",
                    evidence_ids=["ev_0001"],
                )
            evidence = ["ev_9999"] if self.bad_evidence else ["ev_0001"]
            return BlockSimplification(
                simplified_explanation="The paper addresses a stated problem using the encoded method.",
                key_points=["Grounded rewrite"],
                evidence_ids=evidence,
            )
        return await super().generate_structured(prompt, schema)


class InteractivePaperSchemaTests(unittest.TestCase):
    def test_block_rejects_script_markup(self) -> None:
        with self.assertRaises(ValidationError):
            InteractivePaperBlock(
                id="block_x",
                type=BlockType.METHOD,
                title="Method",
                simplified_explanation="<script>alert(1)</script>",
                evidence_ids=["ev_0001"],
            )

    def test_diagram_types_are_closed(self) -> None:
        with self.assertRaises(ValidationError):
            VisualDiagram.model_validate({"type": "mermaid", "title": "Nope", "nodes": [], "edges": []})


class InteractiveValidationTests(unittest.TestCase):
    def test_nodes_without_evidence_are_dropped_unless_inferred(self) -> None:
        diagram = VisualDiagram(
            type=DiagramType.FLOW,
            title="Flow",
            nodes=[
                VisualNode(id="a", label="A", evidence_ids=["ev_0001"]),
                VisualNode(id="b", label="Hallucinated", evidence_ids=["ev_missing"]),
                VisualNode(id="c", label="Inferred", evidence_ids=[], inferred=True),
            ],
            edges=[
                VisualEdge(id="e1", source="a", target="b", evidence_ids=["ev_0001"]),
                VisualEdge(id="e2", source="a", target="c", evidence_ids=[], inferred=True),
                VisualEdge(id="e3", source="a", target="c", evidence_ids=["ev_nope"]),
            ],
        )
        sanitized = sanitize_diagram(diagram, {"ev_0001"})
        assert sanitized is not None
        self.assertEqual({node.id for node in sanitized.nodes}, {"a", "c"})
        self.assertEqual([edge.id for edge in sanitized.edges], ["e2"])
        self.assertTrue(sanitized.edges[0].inferred)

    def test_equation_without_evidence_is_dropped(self) -> None:
        paper = InteractivePaper(
            paper_id="paper_extraction",
            document_id="doc_x",
            cache_key="k",
            blocks=[
                InteractivePaperBlock(
                    id="block_eq",
                    type=BlockType.EQUATION_EXPLANATION,
                    title="Eq",
                    simplified_explanation="Cross-entropy.",
                    equations=[
                        EquationExplanation(
                            id="eq1",
                            original_expression="L = 1",
                            evidence_ids=["ev_missing"],
                            terms=[EquationTerm(symbol="L", meaning="loss")],
                        )
                    ],
                    evidence_ids=["ev_0001"],
                    status=BlockStatus.READY,
                )
            ],
        )
        validated = validate_paper(paper, available_ids={"ev_0001"}, figure_ids=set(), table_ids=set())
        self.assertEqual(validated.blocks[0].equations, [])
        self.assertEqual(validated.blocks[0].status, BlockStatus.READY)

    def test_visual_failure_keeps_text(self) -> None:
        paper = InteractivePaper(
            paper_id="paper_extraction",
            document_id="doc_x",
            cache_key="k",
            blocks=[
                InteractivePaperBlock(
                    id="block_method",
                    type=BlockType.METHOD,
                    title="How it works",
                    simplified_explanation="The encoder is followed by attention.",
                    visual=VisualDiagram(
                        type=DiagramType.ARCHITECTURE,
                        title="Arch",
                        nodes=[VisualNode(id="n", label="Ghost", evidence_ids=["ev_nope"])],
                    ),
                    evidence_ids=["ev_0001"],
                    status=BlockStatus.READY,
                )
            ],
        )
        validated = validate_paper(paper, available_ids={"ev_0001"}, figure_ids=set(), table_ids=set())
        self.assertIsNone(validated.blocks[0].visual)
        self.assertEqual(validated.blocks[0].status, BlockStatus.READY)
        self.assertIn("Visualization dropped", validated.blocks[0].error or "")


class InteractiveAssemblerTests(unittest.IsolatedAsyncioTestCase):
    async def test_assembles_mixed_method_block_from_paper_ir(self) -> None:
        database, paper_id = _document_fixture()
        extraction = ResearchExtractionService(
            database,
            FakeProvider(),
            settings=Settings(ai_provider="mock", ai_model="fixture-model"),
        )
        analysis = await extraction.extract(paper_id)
        document = database.get_document(paper_id)
        assert document is not None
        evidence = {item.id for item in database.get_evidence_for_document(paper_id, document.id)}
        paper = assemble_interactive_paper(
            document,
            analysis,
            available_ids=evidence,
            cache_key="k",
            provider="mock",
            model="fixture-model",
        )
        types = [block.type for block in paper.blocks if block.status == BlockStatus.READY]
        self.assertIn(BlockType.OVERVIEW, types)
        self.assertIn(BlockType.PROBLEM, types)
        self.assertIn(BlockType.METHOD, types)
        self.assertIn(BlockType.EXPERIMENT, types)
        self.assertIn(BlockType.RESULT, types)
        self.assertIn(BlockType.LIMITATION, types)
        method = next(block for block in paper.blocks if block.type == BlockType.METHOD)
        self.assertIsNotNone(method.visual)
        self.assertEqual(method.visual.type, DiagramType.PIPELINE)
        self.assertEqual(method.archify_ir["diagram"]["diagram_type"], "workflow")
        self.assertTrue(method.visual.nodes)
        self.assertTrue(any(edge.inferred for edge in method.visual.edges) or method.visual.edges == [])
        self.assertTrue(method.evidence_ids)
        self.assertTrue(all(eid in evidence for eid in method.evidence_ids))

    async def test_source_hash_change_invalidates_cache(self) -> None:
        database, paper_id = _document_fixture()
        settings = Settings(ai_provider="mock", ai_model="fixture-model")
        service = InteractivePaperService(database, UnavailableAIProvider(), settings=settings)
        first = await service.generate(paper_id, simplify=False)
        document = database.get_document(paper_id)
        assert document is not None
        document.source_hash = "changed-hash"
        database.replace_document(document, database.get_evidence_for_document(paper_id, document.id))
        self.assertIsNone(service.current(paper_id))
        second = await service.get_or_assemble(paper_id)
        self.assertNotEqual(first.cache_key, second.cache_key)
        self.assertEqual(second.source_hash, "changed-hash")

    async def test_cache_key_changes_with_schema_and_model(self) -> None:
        left = interactive_cache_key(
            owner_id="user",
            paper_id="p",
            document_hash="d",
            source_hash="s",
            analysis_fingerprint_value="a",
            schema_version=INTERACTIVE_SCHEMA_VERSION,
            prompt_version="v1",
            provider="ollama",
            model="qwen3:4b",
            generation_mode=GenerationMode.ASSEMBLER,
        )
        right = interactive_cache_key(
            owner_id="user",
            paper_id="p",
            document_hash="d",
            source_hash="s",
            analysis_fingerprint_value="a",
            schema_version="interactive-paper-v2",
            prompt_version="v1",
            provider="ollama",
            model="qwen3:4b",
            generation_mode=GenerationMode.ASSEMBLER,
        )
        self.assertNotEqual(left, right)

    async def test_malformed_llm_output_keeps_assembled_block(self) -> None:
        database, paper_id = _document_fixture()
        settings = Settings(ai_provider="mock", ai_model="fixture-model")
        await ResearchExtractionService(database, FakeProvider(), settings=settings).extract(paper_id)
        service = InteractivePaperService(database, InteractiveFakeProvider(malformed=True), settings=settings)
        paper = await service.generate(paper_id, simplify=True)
        overview = next(block for block in paper.blocks if block.type == BlockType.OVERVIEW)
        self.assertEqual(overview.status, BlockStatus.READY)
        self.assertTrue(overview.simplified_explanation)

    async def test_unavailable_provider_still_assembles_without_external_calls(self) -> None:
        database, paper_id = _document_fixture()
        settings = Settings(ai_provider="none", ai_model="qwen3:4b")
        service = InteractivePaperService(database, UnavailableAIProvider(), settings=settings)
        paper = await service.generate(paper_id, simplify=True)
        self.assertGreaterEqual(len([block for block in paper.blocks if block.status == BlockStatus.READY]), 1)
        self.assertEqual(paper.provider, "none")


class InteractiveApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_reader_includes_interactive_paper_and_stays_local(self) -> None:
        database, paper_id = _document_fixture()
        settings = Settings(
            database_url="sqlite:///:memory:",
            paper_storage_path="/tmp/paperlens-interactive",
            ai_provider="mock",
            ai_model="fixture-model",
        )
        extraction = ResearchExtractionService(database, FakeProvider(), settings=settings)
        await extraction.extract(paper_id)
        client = TestClient(
            create_app(
                database=database,
                extraction_service=extraction,
                interactive_paper_service=InteractivePaperService(database, InteractiveFakeProvider(), settings=settings),
                settings=settings,
            )
        )
        reader = client.get(f"/api/papers/{paper_id}/reader")
        self.assertEqual(reader.status_code, 200)
        payload = reader.json()["interactive_paper"]
        self.assertIsNotNone(payload)
        self.assertEqual(payload["schema_version"], INTERACTIVE_SCHEMA_VERSION)
        self.assertTrue(payload["blocks"])
        for block in payload["blocks"]:
            visual = block.get("visual") or {}
            for edge in visual.get("edges") or []:
                self.assertIn("source", edge)
                self.assertIn("target", edge)
                self.assertNotIn("from", edge)
        generated = client.post(f"/api/papers/{paper_id}/interactive")
        self.assertEqual(generated.status_code, 200)
        self.assertEqual(generated.json()["provider"], "mock")

    async def test_analysis_fingerprint_changes_cache(self) -> None:
        database, paper_id = _document_fixture()
        settings = Settings(ai_provider="mock", ai_model="fixture-model")
        extraction = ResearchExtractionService(database, FakeProvider(), settings=settings)
        before = analysis_fingerprint(None)
        analysis = await extraction.extract(paper_id)
        after = analysis_fingerprint(analysis)
        self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()
