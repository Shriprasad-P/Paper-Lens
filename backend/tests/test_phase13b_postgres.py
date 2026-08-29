"""Optional PostgreSQL multi-client closure checks.

Set PAPERLENS_POSTGRES_TEST_URL to run this against a disposable PostgreSQL
database; the normal SQLite suite remains self-contained.
"""

from __future__ import annotations

import os
import threading
import unittest
from uuid import uuid4

from backend.app.db.database import SQLDatabase
from backend.app.models.research import ResearchRun


class PostgreSQLDurableExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.url = os.getenv("PAPERLENS_POSTGRES_TEST_URL")
        if not cls.url:
            raise unittest.SkipTest("PAPERLENS_POSTGRES_TEST_URL is not configured")

    def test_two_independent_clients_have_one_attempt_owner(self) -> None:
        database = SQLDatabase(self.url, create_schema=False)
        run_id = f"pg_test_{uuid4().hex}"
        database.create_research_run(ResearchRun(id=run_id, research_question="concurrency", max_iterations=1, max_candidates=1, max_ingested_papers=1))
        database.queue_research_run(run_id)
        claims: list[object] = []

        def claim(worker: str) -> None:
            claims.append(SQLDatabase(self.url, create_schema=False).claim_next_research_run(worker))

        threads = [threading.Thread(target=claim, args=(f"worker-{index}",)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(item is not None for item in claims), 1)


if __name__ == "__main__":
    unittest.main()
