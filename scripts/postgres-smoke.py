#!/usr/bin/env python3
"""Exercise the persistence boundary against a real PostgreSQL database."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import tempfile
from uuid import uuid4
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.db.database import SQLDatabase
from backend.app.document.normalizer import DocumentNormalizer
from backend.app.evidence.registry import EvidenceRegistry
from backend.app.ingestion.raw import ParsedPaper
from backend.app.models.chat import ChatMessage, ChatMessageStatus, ChatRole, ChatSession
from backend.app.models.document import ExtractionState, PaperIR
from backend.app.models.paper import PaperMetadata, ParsedSection as LegacySection
from backend.app.models.research import ResearchRun, ResearchRunStatus
from backend.app.models.verification import VerificationResult, VerificationStatus
from backend.app.retrieval.embeddings import HashEmbeddingProvider


def main() -> int:
    url = os.environ["PAPERLENS_DATABASE_URL"]
    database = SQLDatabase(url, create_schema=False)
    assert database.healthcheck(), "database healthcheck failed"
    token = uuid4().hex[:10]
    paper_id = f"paper_phase12_{token}"
    source = f"arxiv:phase12-{token}"
    metadata = PaperMetadata(arxiv_id=f"phase12{token}", title="Phase 12 PostgreSQL fixture", source_url="https://arxiv.org/abs/1706.03762", pdf_url="https://arxiv.org/pdf/1706.03762.pdf")
    with tempfile.TemporaryDirectory() as directory:
        pdf_path = Path(directory) / "source.pdf"
        pdf_path.write_bytes(b"%PDF-phase12")
        database.create_placeholder(paper_id=paper_id, source_identity=source, arxiv_id=metadata.arxiv_id)
        database.save_metadata(paper_id, metadata, status="DOWNLOADING")
        database.save_parsed(paper_id, metadata, [LegacySection(title="Introduction", order=0, text="PostgreSQL persistence keeps evidence linked.")], pdf_path)
        paper = database.get_by_id(paper_id)
        assert paper is not None
        parsed = ParsedPaper.from_legacy_sections(paper.sections, parser_name="phase12-smoke")
        document = DocumentNormalizer().normalize(parsed, paper_id=paper_id, metadata=metadata)
        evidence = EvidenceRegistry().build_for_document(document)
        database.replace_document(document, evidence)
        assert database.get_document(paper_id) is not None
        assert database.get_evidence(paper_id, evidence[0].id) is not None

        analysis = PaperIR(paper_id=paper_id, document_id=document.id, metadata=metadata, extraction={"method": ExtractionState(status="NO_EVIDENCE")}, document_hash=document.document_hash)
        database.save_analysis(analysis, cache_key=f"phase12-analysis-{token}", provider="none", model="none", prompt_version="v1", schema_version="v1")
        verification = VerificationResult(
            claim_id="claim_phase12", status=VerificationStatus.UNVERIFIED, evidence_ids=[evidence[0].id],
            rationale="Provider unavailable in the smoke test.", prompt_version="v1", schema_version="v1",
            document_hash=document.document_hash, claim_hash=hashlib.sha256(b"claim").hexdigest(),
            evidence_hash=hashlib.sha256(evidence[0].source_text.encode()).hexdigest(), cache_key=f"phase12-verification-{token}",
        )
        database.save_verification_results(paper_id, document.id, [verification])
        session = database.create_chat_session(ChatSession(id=f"chat_{token}", paper_id=paper_id, document_id=document.id, document_hash=document.document_hash))
        database.save_chat_message(ChatMessage(id=f"message_{token}", session_id=session.id, role=ChatRole.USER, content="What is this?", document_id=document.id))
        assert len(database.get_chat_messages(session.id)) == 1
        workspace = database.create_workspace("Phase 12 PostgreSQL")
        database.add_workspace_paper(workspace.id, paper_id)
        run = database.create_research_run(ResearchRun(id=f"research_{token}", workspace_id=workspace.id, research_question="Does persistence work?", status=ResearchRunStatus.CREATED, max_iterations=1, max_candidates=1, max_ingested_papers=1))
        assert database.get_research_run(run.id) is not None
        provider = HashEmbeddingProvider(dimension=8)
        vectors = asyncio.run(provider.embed_texts([evidence[0].source_text]))
        database.save_embeddings(paper_id, document.id, provider, [(evidence[0], vectors[0])])
        assert evidence[0].id in database.get_embeddings(paper_id, document.id, provider.model, provider.version)
        database.save_idempotent_response("phase12", "retry", {"ok": True})
        assert database.get_idempotent_response("phase12", "retry") == {"ok": True}
    print(json.dumps({"database": "postgresql", "paper": paper_id, "document": document.id, "evidence": len(evidence), "analysis": True, "verification": True, "chat": True, "workspace": True, "research_run": True, "embeddings": True, "idempotency": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
