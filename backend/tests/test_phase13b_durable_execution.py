from __future__ import annotations

import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from backend.app.db.database import ResearchExecutionAttemptRecord, SQLDatabase
from backend.app.models.research import ResearchRun, ResearchExecutionState, ResearchRunStatus


class DurableResearchExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.db = SQLDatabase(f"sqlite:///{self.path}")
        self.db.create_research_run(ResearchRun(id="run_13b", research_question="bounded", max_iterations=1, max_candidates=2, max_ingested_papers=1))

    def tearDown(self) -> None:
        self.db.engine.dispose()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(self.path + suffix)
            except FileNotFoundError:
                pass

    def test_two_workers_have_one_durable_winner(self) -> None:
        self.db.queue_research_run("run_13b")
        results: list[object] = []
        threads = [threading.Thread(target=lambda worker=f"worker-{i}": results.append(self.db.claim_next_research_run(worker))) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(item is not None for item in results), 1)
        self.assertEqual(self.db.get_research_run("run_13b").attempt_count, 1)

    def test_expiry_fences_old_claim_and_recovery_requeues(self) -> None:
        self.db.queue_research_run("run_13b")
        old = self.db.claim_next_research_run("worker-a", lease_seconds=5)
        self.assertIsNotNone(old)
        with self.db.session_factory.begin() as session:
            session.execute(update(ResearchExecutionAttemptRecord).where(ResearchExecutionAttemptRecord.attempt_id == old.attempt_id).values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        self.db.recover_incomplete_work()
        self.assertFalse(self.db.execution_claim_valid(old))
        new = self.db.claim_next_research_run("worker-b", lease_seconds=5)
        self.assertIsNotNone(new)
        self.assertNotEqual(old.attempt_id, new.attempt_id)
        self.assertFalse(self.db.complete_execution(old))
        self.assertTrue(self.db.complete_execution(new))

    def test_cancellation_is_durable_and_dominates_completion(self) -> None:
        self.db.queue_research_run("run_13b")
        claim = self.db.claim_next_research_run("worker-a", lease_seconds=30)
        self.assertIsNotNone(claim)
        self.assertTrue(self.db.mark_attempt_running(claim))
        requested = self.db.request_research_cancellation("run_13b")
        self.assertEqual(requested.execution_state, ResearchExecutionState.CANCEL_REQUESTED)
        self.assertTrue(self.db.complete_execution(claim))
        final = self.db.get_research_run("run_13b")
        self.assertEqual(final.status, ResearchRunStatus.CANCELLED)
        self.assertEqual(final.execution_state, ResearchExecutionState.CANCELLED)

    def test_duplicate_enqueue_is_idempotent(self) -> None:
        first = self.db.queue_research_run("run_13b")
        second = self.db.queue_research_run("run_13b")
        self.assertEqual(first.execution_state, ResearchExecutionState.QUEUED)
        self.assertEqual(second.execution_state, ResearchExecutionState.QUEUED)
        self.assertEqual(self.db.get_research_events("run_13b")[-1].event_type, "QUEUED")

    def test_attempt_history_is_owner_scoped_and_token_is_not_returned(self) -> None:
        self.db.queue_research_run("run_13b")
        claim = self.db.claim_next_research_run("worker-a")
        summary = self.db.get_research_attempt("run_13b")
        self.assertEqual(summary.attempt_id, claim.attempt_id)
        self.assertNotIn("token", summary.model_dump())
        self.assertIsNone(self.db.get_research_attempt("run_13b", "another-owner"))


if __name__ == "__main__":
    unittest.main()
