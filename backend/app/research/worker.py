"""Small database-polled research worker.

The worker intentionally has no queue dependency: the database is the queue,
claim ledger, lease clock, and fencing authority for both server and desktop
execution.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from contextlib import suppress

from ..core.config import Settings
from ..db.database import SQLDatabase
from ..models.research import ExecutionClaim
from .agent import ResearchAgent

logger = logging.getLogger("paperlens.research.worker")


class ResearchWorker:
    def __init__(self, database: SQLDatabase, agent: ResearchAgent, *, settings: Settings | None = None, worker_id: str | None = None, metrics: object | None = None) -> None:
        self.database = database
        self.agent = agent
        self.settings = settings or Settings.from_env()
        self.worker_id = (worker_id or f"{socket.gethostname()}:{os.getpid()}")[:128]
        self.metrics = metrics
        self._stop = asyncio.Event()

    async def run_once(self) -> bool:
        claim = self.database.claim_next_research_run(
            self.worker_id,
            lease_seconds=self.settings.research_claim_lease_seconds,
            max_attempts=self.settings.research_max_attempts,
        )
        if claim is None:
            return False
        await self._process_claim(claim)
        return True

    async def _process_claim(self, claim: ExecutionClaim) -> None:
        owner_id = self.database.get_research_run_owner(claim.run_id)
        if owner_id is None or not self.database.is_owner_enabled(owner_id):
            self.database.fail_execution(claim, error_class="OWNER_DISABLED" if owner_id else "OWNER_MISSING", error_message="The run owner is unavailable.", retryable=False, max_attempts=self.settings.research_max_attempts)
            return
        heartbeat = asyncio.create_task(self._heartbeat(claim))
        started = time.perf_counter()
        try:
            await self.agent.execute(claim.run_id, owner_id, claim)
            if self.metrics is not None and hasattr(self.metrics, "observe_research_execution"):
                self.metrics.observe_research_execution("completed", duration_ms=(time.perf_counter() - started) * 1000)
        except Exception as exc:  # defensive boundary: no worker crash loses the durable failure
            logger.warning("research attempt failed", extra={"run_id": claim.run_id, "attempt_id": claim.attempt_id, "error_class": exc.__class__.__name__})
            self.database.fail_execution(
                claim,
                error_class=exc.__class__.__name__,
                error_message=str(exc),
                retryable=isinstance(exc, (TimeoutError, ConnectionError)),
                max_attempts=self.settings.research_max_attempts,
            )
            if self.metrics is not None and hasattr(self.metrics, "observe_research_execution"):
                self.metrics.observe_research_execution("failed", duration_ms=(time.perf_counter() - started) * 1000)
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

    async def _heartbeat(self, claim: ExecutionClaim) -> None:
        interval = max(1.0, self.settings.research_claim_lease_seconds / 3)
        while True:
            await asyncio.sleep(interval)
            if not self.database.renew_execution_lease(claim, lease_seconds=self.settings.research_claim_lease_seconds):
                return

    async def run_forever(self) -> None:
        self._stop.clear()
        active: set[asyncio.Task[None]] = set()
        while not self._stop.is_set():
            while len(active) < self.settings.research_worker_concurrency:
                claim = self.database.claim_next_research_run(
                    self.worker_id,
                    lease_seconds=self.settings.research_claim_lease_seconds,
                    max_attempts=self.settings.research_max_attempts,
                )
                if claim is None:
                    break
                active.add(asyncio.create_task(self._process_claim(claim)))
            if active:
                done, active = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    with suppress(Exception):
                        task.result()
            else:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.settings.research_worker_poll_seconds)
                except asyncio.TimeoutError:
                    pass

    def stop(self) -> None:
        self._stop.set()


async def main() -> None:
    settings = Settings.from_env()
    settings.validate()
    database = SQLDatabase(settings.database_url, create_schema=settings.auto_create_schema, pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow, pool_timeout=settings.db_pool_timeout)
    # Importing the app factory here would create a second database and worker.
    from .discovery import ArxivDiscoveryProvider
    from .planner import ResearchPlanner
    from ..ai.provider import create_ai_provider
    from ..extraction.service import ResearchExtractionService
    from ..ingestion.service import IngestionService

    provider = create_ai_provider(settings)
    ingestion = IngestionService(database, settings=settings)
    extraction = ResearchExtractionService(database, provider, settings=settings)
    agent = ResearchAgent(database, ResearchPlanner(provider, settings=settings), ArxivDiscoveryProvider(timeout=settings.arxiv_request_timeout), ingestion, extraction, settings=settings)
    await ResearchWorker(database, agent, settings=settings).run_forever()


if __name__ == "__main__":  # pragma: no cover - operational entry point
    asyncio.run(main())
