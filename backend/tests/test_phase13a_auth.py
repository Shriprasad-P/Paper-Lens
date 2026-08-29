"""Phase 13A account, session, and two-user isolation proof."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from io import StringIO
import logging

from fastapi.testclient import TestClient

from backend.app.auth import session_token_hash
from backend.app.core.config import Settings
from backend.app.db.database import SQLDatabase, SessionRecord
from backend.app.document.normalizer import DocumentNormalizer
from backend.app.evidence.registry import EvidenceRegistry
from backend.app.ingestion.raw import ParsedPaper, RawParagraph, RawSection
from backend.app.main import create_app
from backend.app.models.paper import PaperMetadata


def _paper(db: SQLDatabase, owner_id: str, paper_id: str, arxiv_id: str) -> str:
    metadata = PaperMetadata(
        arxiv_id=arxiv_id,
        title=paper_id,
        source_url=f"https://arxiv.org/abs/{arxiv_id}",
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}.pdf",
    )
    db.create_placeholder(
        paper_id=paper_id,
        source_identity=f"arxiv:{arxiv_id}",
        arxiv_id=arxiv_id,
        owner_id=owner_id,
    )
    db.save_metadata(paper_id, metadata, status="COMPLETED", owner_id=owner_id)
    parsed = ParsedPaper(
        parser_name="phase13a-fixture",
        page_count=1,
        sections=[
            RawSection(
                title="Method",
                level=1,
                order=0,
                paragraphs=[RawParagraph(text="A bounded method with registry evidence for isolation testing.", page=1)],
            )
        ],
    )
    document = DocumentNormalizer().normalize(parsed, paper_id=paper_id, metadata=metadata)
    db.replace_document(document, EvidenceRegistry().build_for_document(document), owner_id)
    return document.id


class Phase13AAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = SQLDatabase("sqlite:///:memory:")
        self.settings = Settings(
            environment="test",
            auth_required=True,
            database_url="sqlite:///:memory:",
            ai_provider="none",
            research_agent_enabled=True,
        )
        self.app = create_app(settings=self.settings, database=self.db)
        self.a = TestClient(self.app)
        self.b = TestClient(self.app)
        self.user_a = self.a.post(
            "/api/auth/register", json={"email": "a@example.com", "password": "correct horse battery staple"}
        ).json()["user"]["id"]
        self.user_b = self.b.post(
            "/api/auth/register", json={"email": "b@example.com", "password": "correct horse battery staple"}
        ).json()["user"]["id"]
        self.paper_a = _paper(self.db, self.user_a, "paper_a", "1111.11111")
        self.paper_b = _paper(self.db, self.user_b, "paper_b", "2222.22222")

    def test_two_user_workspace_paper_chat_and_research_isolation(self) -> None:
        workspace_a = self.a.post("/api/workspaces", json={"name": "Workspace A"}).json()["id"]
        workspace_b = self.b.post("/api/workspaces", json={"name": "Workspace B"}).json()["id"]
        self.assertEqual([item["id"] for item in self.a.get("/api/workspaces").json()], [workspace_a])
        self.assertEqual([item["id"] for item in self.b.get("/api/workspaces").json()], [workspace_b])

        for client, foreign_workspace, foreign_paper in (
            (self.a, workspace_b, "paper_b"),
            (self.b, workspace_a, "paper_a"),
        ):
            self.assertEqual(client.get(f"/api/workspaces/{foreign_workspace}").status_code, 404)
            self.assertEqual(client.patch(f"/api/workspaces/{foreign_workspace}", json={"name": "hijack"}).status_code, 404)
            self.assertEqual(client.delete(f"/api/workspaces/{foreign_workspace}").status_code, 404)
            self.assertEqual(client.post(f"/api/workspaces/{foreign_workspace}/papers/{foreign_paper}").status_code, 404)
            self.assertEqual(client.get(f"/api/papers/{foreign_paper}").status_code, 404)
            self.assertEqual(client.get(f"/api/papers/{foreign_paper}/document").status_code, 404)
            self.assertEqual(client.get(f"/api/papers/{foreign_paper}/evidence/ev_0001").status_code, 404)
            self.assertEqual(client.get(f"/api/papers/{foreign_paper}/source").status_code, 404)
            self.assertEqual(client.get(f"/api/papers/{foreign_paper}/reader").status_code, 404)
            self.assertEqual(client.get(f"/api/papers/{foreign_paper}/analysis").status_code, 404)
            self.assertEqual(client.get(f"/api/papers/{foreign_paper}/verification").status_code, 404)
            self.assertEqual(client.get(f"/api/papers/{foreign_paper}/citation-graph").status_code, 404)

        chat_a = self.a.post("/api/papers/paper_a/chat/sessions")
        chat_b = self.b.post("/api/papers/paper_b/chat/sessions")
        self.assertEqual(chat_a.status_code, 201)
        self.assertEqual(chat_b.status_code, 201)
        self.assertEqual(
            self.a.get(f"/api/papers/paper_b/chat/sessions/{chat_b.json()['session_id']}").status_code,
            404,
        )
        self.assertEqual(
            self.b.get(f"/api/papers/paper_a/chat/sessions/{chat_a.json()['session_id']}").status_code,
            404,
        )

        run_a = self.a.post("/api/research/runs", json={"question": "A"})
        run_b = self.b.post("/api/research/runs", json={"question": "B"})
        self.assertEqual(run_a.status_code, 201)
        self.assertEqual(run_b.status_code, 201)
        run_b_id = run_b.json()["run"]["id"]
        self.assertEqual(self.a.get(f"/api/research/runs/{run_b_id}").status_code, 404)
        self.assertEqual(self.a.post(f"/api/research/runs/{run_b_id}/execute").status_code, 404)
        self.assertEqual(self.a.post(f"/api/research/runs/{run_b_id}/cancel").status_code, 404)
        self.assertEqual(self.a.get(f"/api/research/runs/{run_b_id}/report").status_code, 404)

    def test_session_lifecycle_and_hash_only_persistence(self) -> None:
        self.assertEqual(self.a.get("/api/auth/me").status_code, 200)
        raw_cookie = self.a.cookies.get("paperlens_session")
        self.assertIsNotNone(raw_cookie)
        with self.db.session_factory() as session:
            records = session.query(SessionRecord).all()
            self.assertTrue(records)
            self.assertTrue(all(record.token_hash != raw_cookie for record in records))
            self.assertTrue(all(len(record.token_hash) == 64 for record in records))

        expired = TestClient(self.app)
        expired.cookies.set("paperlens_session", raw_cookie)
        with self.db.session_factory.begin() as session:
            record = session.query(SessionRecord).filter(SessionRecord.token_hash == session_token_hash(raw_cookie)).first()
            assert record is not None
            record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        self.assertEqual(expired.get("/api/auth/me").status_code, 401)

        malformed = TestClient(self.app)
        malformed.cookies.set("paperlens_session", "malformed-session-token")
        self.assertEqual(malformed.get("/api/auth/me").status_code, 401)

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        auth_logger = logging.getLogger("paperlens.auth")
        auth_logger.addHandler(handler)
        try:
            malformed.get("/api/auth/me")
        finally:
            auth_logger.removeHandler(handler)
        self.assertNotIn("malformed-session-token", stream.getvalue())

        self.assertEqual(self.a.post("/api/auth/logout").status_code, 200)
        self.assertEqual(self.a.get("/api/auth/me").status_code, 401)
        self.assertEqual(
            self.a.post("/api/auth/login", json={"email": "unknown@example.com", "password": "wrong password"}).status_code,
            401,
        )

    def test_unauthenticated_shared_requests_are_401(self) -> None:
        anonymous = TestClient(self.app)
        self.assertEqual(anonymous.get("/api/workspaces").status_code, 401)
        self.assertEqual(anonymous.get("/api/papers/paper_a").status_code, 401)


if __name__ == "__main__":
    unittest.main()
