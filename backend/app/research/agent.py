"""Bounded, observable research-agent orchestration."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from ..core.config import Settings
from ..db.database import SQLDatabase
from ..extraction.service import ResearchExtractionService
from ..ingestion.service import IngestionService
from ..models.research import (
    PaperCandidate,
    ResearchCoverage,
    ResearchRun,
    ResearchRunEvent,
    ResearchRunStatus,
    ExecutionClaim,
)
from .discovery import LiteratureDiscoveryError, LiteratureDiscoveryProvider, normalize_arxiv_id
from .planner import ResearchPlanner
from .ranking import CandidateRanker, deduplicate_candidates, select_candidates
from .retrieval import CrossPaperEvidenceRetriever
from .synthesis import ResearchSynthesisError, ResearchSynthesizer, validate_research_report


class ResearchAgentError(Exception):
    """Expected failure from a research run."""


class ResearchAgent:
    def __init__(
        self,
        database: SQLDatabase,
        planner: ResearchPlanner,
        discovery: LiteratureDiscoveryProvider,
        ingestion: IngestionService,
        extraction: ResearchExtractionService,
        *,
        settings: Settings | None = None,
        synthesizer: ResearchSynthesizer | None = None,
    ) -> None:
        self.database = database
        self.planner = planner
        self.discovery = discovery
        self.ingestion = ingestion
        self.extraction = extraction
        self.settings = settings or Settings.from_env()
        self.synthesizer = synthesizer or ResearchSynthesizer(database, CrossPaperEvidenceRetriever(database, settings=self.settings))
        self.ranker = CandidateRanker(database)
    async def execute(self, run_id: str, owner_id: str = "user_legacy_local", claim: ExecutionClaim | None = None) -> ResearchRun:
        """Execute through the durable claim path (kept for direct desktop callers/tests)."""

        run = self.database.get_research_run(run_id, owner_id)
        if run is None:
            raise ResearchAgentError("Research run not found.")
        if claim is None:
            queued = self.database.queue_research_run(run_id, owner_id)
            if queued is None:
                raise ResearchAgentError("Research run not found.")
            claim = self.database.claim_research_run(run_id, f"inline-{uuid4().hex[:12]}", lease_seconds=max(30, int(self.settings.research_step_timeout)), owner_id=owner_id)
            if claim is None:
                return self.database.get_research_run(run_id, owner_id) or run
        if run.status == ResearchRunStatus.CANCELLED:
            return run
        if not self.database.mark_attempt_running(claim):
            return self.database.get_research_run(run_id, owner_id) or run
        run = self.database.get_research_run(run_id, owner_id) or run
        failures = 0
        try:
            run = await self._status(run, ResearchRunStatus.PLANNING, "Planning bounded literature searches.", owner_id=owner_id, claim=claim)
            plan = await asyncio.wait_for(
                self.planner.plan(run.research_question, desired_paper_count=run.max_ingested_papers),
                timeout=self.settings.research_step_timeout,
            )
            self.database.save_research_plan(run.id, plan, owner_id, claim)
            for query in plan.search_queries:
                self.database.add_research_query(run.id, query, 1, owner_id, claim)
            self._event(run.id, "PLAN_CREATED", f"Prepared {len(plan.search_queries)} bounded queries.", {"query_count": len(plan.search_queries)}, owner_id, claim)

            candidates: list[PaperCandidate] = []
            selected: list[PaperCandidate] = []
            ingested_ids: list[str] = []
            seen_candidate_ids: set[str] = set()
            queries = list(plan.search_queries)
            provider_calls = 0
            previous_new_count = 0
            coverage = ResearchCoverage(evidence_count=0, summary="Coverage has not been evaluated yet.")
            for iteration in range(1, run.max_iterations + 1):
                if self._cancelled(run.id, owner_id, claim):
                    return self.database.get_research_run(run.id, owner_id) or run
                run = await self._status(run, ResearchRunStatus.DISCOVERING, f"Discovering literature (iteration {iteration}).", owner_id=owner_id, claim=claim)
                discovered: list[PaperCandidate] = []
                for query in queries:
                    if self._cancelled(run.id, owner_id, claim):
                        return self.database.get_research_run(run.id, owner_id) or run
                    if provider_calls >= min(self.settings.research_max_provider_calls, run.max_candidates):
                        break
                    try:
                        discovered.extend(
                            await asyncio.wait_for(
                                self.discovery.search(query, min(run.max_candidates, self.settings.research_max_candidates)),
                                timeout=self.settings.research_step_timeout,
                            )
                        )
                    except LiteratureDiscoveryError as exc:
                        failures += 1
                        self._event(run.id, "DISCOVERY_FAILED", str(exc), {"query": query, "iteration": iteration}, owner_id, claim)
                    provider_calls += 1
                normalized = deduplicate_candidates([*candidates, *discovered])
                new_count = len([item for item in normalized if item.candidate_id not in seen_candidate_ids])
                seen_candidate_ids.update(item.candidate_id for item in normalized)
                candidates = self.ranker.rank(run.research_question, normalized, limit=run.max_candidates, owner_id=owner_id)
                selected = select_candidates(candidates, run.max_candidates, run.max_ingested_papers)
                self.database.save_research_candidates(run.id, [*candidates, *selected], owner_id, claim)
                self._event(run.id, "CANDIDATES_FOUND", f"Found {len(candidates)} unique candidate papers.", {"iteration": iteration, "new_count": new_count, "candidate_count": len(candidates)}, owner_id, claim)
                run = await self._status(run, ResearchRunStatus.SELECTING, f"Selected {len(selected)} papers within the run budget.", owner_id=owner_id, claim=claim)
                self._event(run.id, "CANDIDATES_SELECTED", f"Selected {len(selected)} papers for bounded ingestion.", {"selected_count": len(selected)}, owner_id, claim)
                if not selected or (new_count == 0 and iteration > 1):
                    self._event(run.id, "STOPPED_NO_NEW_CANDIDATES", "Stopping because discovery produced no new candidates.", {"iteration": iteration}, owner_id, claim)
                    break

                run = await self._status(run, ResearchRunStatus.INGESTING, f"Ingesting up to {run.max_ingested_papers} papers.", owner_id=owner_id, claim=claim)
                ingest_results = await self._ingest_selected(run, selected, owner_id, claim)
                failures += sum(1 for _, error in ingest_results if error)
                by_candidate = {candidate.candidate_id: candidate for candidate, _ in ingest_results}
                selected = [by_candidate.get(candidate.candidate_id, candidate) for candidate in selected]
                candidates = [by_candidate.get(candidate.candidate_id, candidate) for candidate in candidates]
                for candidate, error in ingest_results:
                    if candidate.paper_id and not error and candidate.paper_id not in ingested_ids:
                        ingested_ids.append(candidate.paper_id)
                if ingested_ids:
                    workspace_id = run.workspace_id
                    if workspace_id is None:
                        workspace = self.database.create_workspace(f"Research · {run.research_question[:72]}", owner_id, claim)
                        workspace_id = workspace.id
                        if not self.database.execution_claim_valid(claim):
                            raise ResearchAgentError("Research execution claim was lost.")
                        run = await self._status(run.model_copy(update={"workspace_id": workspace_id}), run.status, "Created a workspace for the selected literature.", owner_id=owner_id, claim=claim)
                    for paper_id in ingested_ids:
                        try:
                            self.database.add_workspace_paper(workspace_id, paper_id, owner_id, claim)
                        except Exception:
                            failures += 1
                    self._event(run.id, "WORKSPACE_UPDATED", f"Workspace contains {len(ingested_ids)} selected papers.", {"workspace_id": workspace_id, "paper_count": len(ingested_ids)}, owner_id, claim)
                self.database.save_research_candidates(run.id, [*candidates, *selected], owner_id, claim)
                self._event(run.id, "INGESTION_COMPLETE", f"Ingested {len(ingested_ids)} papers with {failures} failures.", {"ingested_count": len(ingested_ids), "failure_count": failures}, owner_id, claim)
                if self._cancelled(run.id, owner_id, claim):
                    return self.database.get_research_run(run.id, owner_id) or run
                run = await self._status(run, ResearchRunStatus.ANALYZING, "Extracting evidence-grounded paper analyses.", owner_id=owner_id, claim=claim)
                for paper_id in list(ingested_ids):
                    if self._cancelled(run.id, owner_id, claim):
                        return self.database.get_research_run(run.id, owner_id) or run
                    try:
                        await asyncio.wait_for(self.extraction.extract(paper_id, owner_id), timeout=self.settings.research_step_timeout)
                        self._event(run.id, "PAPER_ANALYZED", f"Analyzed paper {paper_id}.", {"paper_id": paper_id}, owner_id, claim)
                    except Exception as exc:
                        failures += 1
                        self._event(run.id, "ANALYSIS_FAILED", "Paper analysis failed; continuing with remaining papers.", {"paper_id": paper_id, "error": str(exc)[:200]}, owner_id, claim)
                coverage = self._coverage(plan.concepts, ingested_ids, owner_id)
                self._event(run.id, "COVERAGE_EVALUATED", coverage.summary, coverage.model_dump(mode="json"), owner_id, claim)
                if coverage.sufficient or iteration >= run.max_iterations:
                    break
                missing = coverage.missing_concepts[:3]
                if not missing:
                    break
                refined = f"{run.research_question} {' '.join(missing)} evidence"
                if refined in queries:
                    self._event(run.id, "STOPPED_NO_NEW_CANDIDATES", "No bounded search refinement remained.", {"iteration": iteration}, owner_id, claim)
                    break
                queries = [refined]
                self.database.add_research_query(run.id, refined, iteration + 1, owner_id, claim)
                self._event(run.id, "SEARCH_REFINED", "Refined search using uncovered concepts.", {"query": refined, "iteration": iteration + 1}, owner_id, claim)
                previous_new_count = new_count
                if previous_new_count == 0:
                    break

            if self._cancelled(run.id, owner_id, claim):
                return self.database.get_research_run(run.id, owner_id) or run
            run = await self._status(run, ResearchRunStatus.SYNTHESIZING, "Constructing a citation-valid research report.", owner_id=owner_id, claim=claim)
            report = await asyncio.wait_for(
                self.synthesizer.synthesize(
                    run.research_question,
                    ingested_ids,
                    queries=self.database.get_research_queries(run.id, owner_id),
                    coverage=coverage,
                    selected_candidates=selected,
                    owner_id=owner_id,
                ),
                timeout=self.settings.research_step_timeout,
            )
            validate_research_report(report, self.database, set(ingested_ids), owner_id)
            self.database.save_research_report(run.id, report, owner_id, claim)
            self._event(run.id, "REPORT_CREATED", "Saved a report containing only registry-grounded citations.", {"claim_count": len(report.executive_summary)}, owner_id, claim)
            run = await self._status(run, ResearchRunStatus.VERIFYING, "Validated report evidence identity and numeric fidelity.", owner_id=owner_id, claim=claim)
            self._event(run.id, "VERIFICATION_COMPLETE", "Unsupported claims remain explicitly UNVERIFIED.", {"verified": False}, owner_id, claim)
            final_status = ResearchRunStatus.COMPLETED if ingested_ids and failures == 0 else ResearchRunStatus.PARTIAL
            run = await self._status(run, final_status, "Research run completed." if final_status == ResearchRunStatus.COMPLETED else "Research run completed with partial results.", completed=True, owner_id=owner_id, claim=claim)
            self.database.complete_execution(claim, status=final_status)
            return self.database.get_research_run(run.id, owner_id) or run
        except ResearchSynthesisError as exc:
            if self.database.execution_claim_valid(claim):
                self._event(run.id, "RUN_FAILED", str(exc), {}, owner_id, claim)
                self.database.fail_execution(claim, error_class="SYNTHESIS", error_message=str(exc), retryable=False, max_attempts=self.settings.research_max_attempts)
            return self.database.get_research_run(run.id, owner_id) or run
        except Exception as exc:
            if self.database.execution_claim_valid(claim):
                self._event(run.id, "RUN_FAILED", "Research run failed safely.", {"error": str(exc)[:200]}, owner_id, claim)
                self.database.fail_execution(claim, error_class=exc.__class__.__name__, error_message=str(exc), retryable=isinstance(exc, (TimeoutError, ConnectionError, LiteratureDiscoveryError)), max_attempts=self.settings.research_max_attempts)
            return self.database.get_research_run(run.id, owner_id) or run

    async def cancel(self, run_id: str, owner_id: str = "user_legacy_local") -> ResearchRun:
        run = self.database.request_research_cancellation(run_id, owner_id)
        if run is None:
            raise ResearchAgentError("Research run not found.")
        return run

    async def _ingest_selected(self, run: ResearchRun, selected: list[PaperCandidate], owner_id: str, claim: ExecutionClaim) -> list[tuple[PaperCandidate, str | None]]:
        semaphore = asyncio.Semaphore(
            max(1, min(self.settings.research_ingestion_concurrency, self.settings.max_concurrent_ingestions, 4))
        )
        existing = {normalize_arxiv_id(item.metadata.arxiv_id): item.id for item in self.database.list_papers(owner_id)}

        async def one(candidate: PaperCandidate) -> tuple[PaperCandidate, str | None]:
            async with semaphore:
                if self._cancelled(run.id, owner_id, claim):
                    return candidate.model_copy(update={"ingestion_status": "CANCELLED"}), "cancelled"
                arxiv_id = normalize_arxiv_id(candidate.arxiv_id)
                if not arxiv_id:
                    return candidate.model_copy(update={"ingestion_status": "FAILED", "error": "Candidate has no supported arXiv identifier."}), "no-supported-source"
                if arxiv_id in existing:
                    updated = candidate.model_copy(update={"paper_id": existing[arxiv_id], "ingestion_status": "COMPLETED"})
                    self._event(run.id, "PAPER_REUSED", f"Reused ingested paper {existing[arxiv_id]}.", {"paper_id": existing[arxiv_id]}, owner_id, claim)
                    return updated, None
                try:
                    paper = await asyncio.wait_for(self.ingestion.ingest(arxiv_id, owner_id), timeout=self.settings.research_step_timeout)
                    updated = candidate.model_copy(update={"paper_id": paper.id, "ingestion_status": "COMPLETED"})
                    self._event(run.id, "PAPER_INGESTED", f"Ingested paper {paper.id}.", {"paper_id": paper.id}, owner_id, claim)
                    return updated, None
                except Exception as exc:
                    updated = candidate.model_copy(update={"ingestion_status": "FAILED", "error": str(exc)[:240]})
                    self._event(run.id, "PAPER_FAILED", "Paper ingestion failed; continuing.", {"candidate_id": candidate.candidate_id, "error": str(exc)[:200]}, owner_id, claim)
                    return updated, str(exc)

        return await asyncio.gather(*(one(item) for item in selected))

    def _coverage(self, concepts: list[str], paper_ids: list[str], owner_id: str = "user_legacy_local") -> ResearchCoverage:
        covered: set[str] = set()
        evidence_count = 0
        for paper_id in paper_ids:
            paper = self.database.get_by_id(paper_id, owner_id)
            document = self.database.get_document(paper_id, owner_id)
            if paper is None or document is None:
                continue
            evidence = self.database.get_evidence_for_document(paper_id, document.id, owner_id)
            evidence_count += len(evidence)
            text = f"{paper.metadata.title} {paper.metadata.abstract or ''} {' '.join(item.source_text for item in evidence)}".lower()
            covered.update(concept for concept in concepts if concept.lower() in text)
        missing = [concept for concept in concepts if concept not in covered]
        sufficient = bool(paper_ids) and (len(paper_ids) >= 2 or (covered and not missing)) and evidence_count > 0
        return ResearchCoverage(
            sufficient=sufficient,
            covered_concepts=sorted(covered),
            missing_concepts=missing[:16],
            relevant_paper_ids=paper_ids,
            evidence_count=evidence_count,
            summary=f"Coverage includes {len(covered)} of {len(concepts)} planned concepts across {len(paper_ids)} papers and {evidence_count} evidence records.",
        )

    async def _status(self, run: ResearchRun, status: ResearchRunStatus, message: str, *, completed: bool = False, owner_id: str = "user_legacy_local", claim: ExecutionClaim | None = None) -> ResearchRun:
        now = datetime.now(timezone.utc)
        updated = run.model_copy(update={"status": status, "updated_at": now, "completed_at": now if completed else run.completed_at})
        self.database.update_research_run(updated, owner_id, claim)
        self._event(run.id, "STATUS_CHANGED", message, {"status": status.value}, owner_id, claim)
        return updated

    def _event(self, run_id: str, event_type: str, message: str, metadata: dict[str, object], owner_id: str = "user_legacy_local", claim: ExecutionClaim | None = None) -> None:
        self.database.add_research_event(ResearchRunEvent(id=f"event_{uuid4().hex}", research_run_id=run_id, event_type=event_type, message=message, metadata=metadata, attempt_id=claim.attempt_id if claim else None), owner_id, claim)

    def _cancelled(self, run_id: str, owner_id: str = "user_legacy_local", claim: ExecutionClaim | None = None) -> bool:
        run = self.database.get_research_run(run_id, owner_id)
        if run is None or run.status == ResearchRunStatus.CANCELLED or run.cancel_requested_at is not None:
            if claim is not None and self.database.execution_claim_valid(claim):
                self.database.complete_execution(claim)
            return True
        return claim is not None and not self.database.execution_claim_valid(claim)
