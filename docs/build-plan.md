# PaperLens Build Plan

## Current Phase

Phase 12 — Deployment & Public Beta (complete); macOS local validation complete

## Current Milestone

Reproducible production-like packaging, PostgreSQL migration validation, public-beta
capability gating, release gates, smoke/load checks, backup/rollback guidance,
and deployment documentation — all validated for `v0.1.0-beta`.

## Completed

- [x] Add repository rules and project documentation.
- [x] Add FastAPI application boundary and health endpoint.
- [x] Add portable local database abstraction.
- [x] Add Next.js landing-page shell.
- [x] Add focused backend tests.
- [x] Add strict arXiv ID/URL normalization.
- [x] Retrieve and validate arXiv metadata and PDFs.
- [x] Parse PDF text into normalized sections with PyMuPDF.
- [x] Persist papers/sections with deterministic IDs and idempotency.
- [x] Add typed ingestion and retrieval API endpoints.
- [x] Connect the landing page to ingestion and render normalized papers.
- [x] Validate backend, frontend, and live arXiv integration.
- [x] Add parser-neutral raw sections with page/source-region provenance.
- [x] Add StructuredDocument normalization, stable IDs, and content hashes.
- [x] Add paragraph EvidenceRegistry and typed PaperIR shell.
- [x] Persist and retrieve documents, paragraphs, and evidence transactionally.
- [x] Add document/evidence APIs and frontend evidence drawer.
- [x] Validate Phase 2 regression and live Phase 3 structure/evidence flow.
- [x] Add AIProvider abstraction and OpenAI-compatible adapter with bounded retries.
- [x] Add prompt registry and untrusted-source prompt rules.
- [x] Add deterministic section classification and focused evidence selection.
- [x] Add independent problem, motivation, gap, contribution, method, equation, experiment, result, limitation, and future-work extractors.
- [x] Add schema/evidence validation, explicit/inferred origins, partial failure states, and cache keys.
- [x] Persist PaperIR and expose extraction/analysis APIs.
- [x] Add minimal analysis UI with evidence interaction.
- [x] Validate mocked provider grounding/retry/cache tests and safe no-credential live path.
- [x] Add compact typed ReaderResponse and secure persisted-PDF source endpoint.
- [x] Add deterministic VisualizationSpec planner for method flows and result views.
- [x] Add `/papers/{paper_id}` visual reader route with responsive section navigation.
- [x] Add React Flow method visualization and accessible textual fallback.
- [x] Add unified paper visualization map for method/functions, tables, figures, equations, and results.
- [x] Add KaTeX equation explorer and safe original-expression fallback.
- [x] Add Recharts numeric result view with table/text fallback.
- [x] Add lazy multi-record evidence drawer and source PDF page navigation.
- [x] Validate reader API/source safety, backend regressions, frontend build, and dependency audit.
- [x] Add stable claim collection and categorical verification statuses.
- [x] Add deterministic evidence/document/numeric pre-validation and focused faithfulness prompt.
- [x] Add independent verifier/orchestrator with partial failure isolation and no-credential `UNVERIFIED` fallback.
- [x] Persist versioned verification results and cache by claim/evidence/document/provider/model/prompt/schema.
- [x] Add typed verification APIs and reader badges, summary, manual verify action, and unsupported-claim treatment.
- [x] Validate all statuses, malformed output, prompt injection, numeric fidelity, cache invalidation, API persistence, and Phase 1–5 regressions.
- [x] Add provider-neutral `BM25EvidenceRetriever` (`bm25-v1`) with scientific-token normalization, bounded Top-K, section-aware ranking, and local retrieval cache.
- [x] Add bounded chat context assembly and `paper_chat.md` rules that treat source text and history as untrusted/non-evidence data.
- [x] Add document-bound persistent chat sessions/messages with citation metadata, chronological history, and safe re-ingestion freeze behavior.
- [x] Add structured chat output validation for supplied-context citations, wrong-paper/document rejection, missing citations, numeric fidelity, and first-class insufficient evidence.
- [x] Add chat APIs and a responsive reader Paper Chat panel that reuses the evidence drawer and PDF page navigation.
- [x] Add deterministic retrieval, grounding, persistence, API, prompt-injection, no-credential, and out-of-scope chat tests.
- [x] Add source-first figure, table, equation, and reference extraction with Evidence Registry links and typed reader sections.
- [x] Add provider-neutral semantic embedding interfaces, SQLite embedding cache/invalidation, cosine retrieval, RRF hybrid fusion, and deterministic Recall@K/MRR/Hit@K evaluation.
- [x] Keep BM25 as the default retrieval path and add safe semantic-provider fallback behavior.
- [x] Add persistent workspaces and workspace-paper membership APIs/UI.
- [x] Add evidence-preserving multi-paper comparison IR with comparability and numeric-safety rules.
- [x] Add bounded local citation-graph matching API/UI and multi-document ID collision protection.
- [x] Add Phase 8 artifact, retrieval, workspace, comparison, and citation graph regression tests.
- [x] Add persistent research-run, plan, query, candidate, event, and report records.
- [x] Add deterministic planner fallback and official arXiv Atom discovery provider.
- [x] Add candidate normalization, version-aware deduplication, deterministic ranking, diversity selection, and budgets.
- [x] Reuse ingestion/extraction with bounded concurrency, partial failures, workspace attachment, cancellation, and finite agent iterations.
- [x] Add cross-paper BM25/semantic/hybrid retrieval with composite evidence identity and report validation.
- [x] Add deterministic report IR for claims, themes, methods, agreements, contradictions, gaps, limitations, and future directions.
- [x] Add research APIs, progress timeline, report/citation UI, Phase 9 tests, and documentation.
- [x] Add a separate `backend/evaluation` package with versioned schemas, manifest, JSONL annotations, and deterministic fixture loaders.
- [x] Add pure retrieval, classification, citation, evidence attribution, numeric fidelity, boundary, claim-matching, and latency metrics with validation tests.
- [x] Add parser/artifact/extraction/verification/retrieval/chat/research-agent/synthesis runner boundaries and failure taxonomy.
- [x] Add offline CLI (`smoke`, component commands, `all`, explicit `--live`) with reproducibility metadata and JSON/Markdown reports.
- [x] Document preliminary benchmark policy, corpus limitations, annotation workflow, safety cases, and recommendations.
- [x] Migrate Next.js/eslint-config-next to 16.3.1 and validate the production dependency audit.
- [x] Add typed runtime validation, explicit CORS, security headers, request limits, stable error envelopes, request IDs, metrics, and live/ready probes.
- [x] Stream and bound PDF downloads, enforce page/text limits, harden artifact paths, and add SSRF redirect regression coverage.
- [x] Add SQLite constraint/lock hardening, explicit Alembic migration scaffold, idempotent recovery, and `INTERRUPTED` research-run state.
- [x] Add bounded provider error codes and jittered transient retries while preserving no-key degraded behavior.
- [x] Add deterministic Playwright reader/evidence/PDF/chat/workspace/research/failure smoke tests and CI quality gates.
- [x] Add production, operations, and security guides and document deployment limitations.

## Current

- [x] Install project dependencies in an isolated `.venv` and frontend workspace.

## Later

- [x] Phase 13A — Add durable first-party accounts, revocable sessions, password hashing, and a canonical principal dependency.
- [x] Phase 13A — Add SQL-scoped ownership for papers, workspaces, chats, research runs, and inherited child resources.
- [x] Phase 13A — Backfill existing local records through migration `0002_phase13a_auth_ownership` and preserve explicit desktop-local mode.
- [x] Phase 13A — Add two-user isolation, IDOR, session lifecycle, CSRF/CORS, and migration coverage.
- [x] Phase 13B — Replace process-local research execution with database claims, leases, fencing, durable cancellation, retries, and a bounded polling worker.
- [x] Phase 13B — Durable research execution and queue/lease infrastructure.
- [x] Phase 14 — Isolate untrusted PDF parsing in bounded child processes.
- [x] Phase 14 — Enforce streamed byte, page, incremental text, and image budgets.
- [x] Phase 14 — Add parent timeout/termination, bounded parser concurrency, safe errors, metrics, and regression fixtures.
- [ ] Consider animation only after the reader is stable.

## Phase 12 release work

- [x] Add non-root backend/frontend production images, strict Docker ignores, and PostgreSQL Compose migration/readiness harness.
- [x] Add production aliases, release metadata, capability flags, server-side beta limits, and safe request-ID/error UX.
- [x] Add immutable-SHA CI release workflow, image/security scans, backup/restore and maintenance scripts.
- [x] Add public-beta support, release checklist/notes, security record, rollback/retention guidance, and issue templates.
- [x] Validate real PostgreSQL migrations/persistence, container startup, health/readiness, and bounded load.

## macOS local validation

- [x] Add a Tauri 2 shell with bundle metadata, icon, CSP, single-instance focus, and window sizing.
- [x] Bundle the backend as a PyInstaller sidecar and the Next.js standalone runtime with a bundled Node executable.
- [x] Create Application Support SQLite/PDF/artifact/cache/log directories and run Alembic before readiness.
- [x] Select dynamic loopback ports, pass a per-launch desktop token, support development mode, and keep web mode unchanged.
- [x] Supervise process groups, detect child crashes, and cleanly terminate backend/frontend children on close or exit.
- [x] Add `script/build_and_run.sh`, Codex Run action metadata, macOS documentation, and desktop lifecycle regression coverage.
- [x] Build and launch the local `.app`; validate readiness, UI rendering, token/CORS behavior, persistence, and clean shutdown.

## Blockers

- A hosted HTTPS edge and provider-specific staging URL/credentials remain external deployment responsibilities; the local Compose release harness is validated.

## Explicitly Out of Scope for Current Phase

- Organizations, sharing, invitations, RBAC, billing, email verification,
  password reset, OAuth, and product redesign remain out of scope for Phase 13A.
- Image understanding or arbitrary image/file serving; artifacts remain caption/table/equation/reference evidence.
- Live external AI extraction without configured credentials.

## Phase 14 — bounded PDF ingestion

Phase 14 is complete. Manual and research-triggered ingestion share the same
isolated parser service. The coordinator checks actual bytes and the PDF magic
before starting a child; the child checks page count before traversal and
extracts text and source artifacts in one pass under incremental budgets. The
parent enforces timeout, cancellation cleanup, and a parser-process semaphore.
Failed parses are staged as non-completed work and never publish a partial
document/evidence set. Remaining limitations (best-effort Unix memory/CPU
limits, platform-specific child behavior, and process-local metrics) are
documented in `docs/security.md` and `docs/operations.md`.

## Phase 15 — measured research quality

Phase 15 evaluation plumbing is implemented but not closed. The evaluator
separates retrieval, verification, chat grounding, and research-agent quality;
stores immutable dataset/annotation/prediction provenance; validates evidence
identity fail-closed; records retrieval error categories and numeric fidelity;
and preserves representative failures. The current public-paper manifest is
identifier-only and annotations are draft, so fixture numbers remain
`PRELIMINARY`. Closing the phase requires acquired and hashed PDF versions,
reviewed annotations, frozen real predictions, and one reproducible FINAL run.

### Phase 15B — real corpus progress (not closed)

The 35-paper candidate pool now has exact, versioned arXiv PDF snapshots and
SHA-256 metadata under `backend/evaluation/datasets/corpus/`. Every snapshot
was passed through the Phase 14 bounded downloader/parser/normalizer/document
persistence/evidence-registry path in a clean SQLite evaluation database:
35/35 completed, 34,117 evidence records, parser `1.28.2`, corpus hash
`eb3925e01260897f383c9832e1c564aeff7197e192a62d19ce63cc0f1a0309c1`.

Draft real-corpus ledgers contain 60 retrieval, 50 verification, 40 chat, and
10 agent cases tied to those evidence IDs. A production BM25 run is frozen;
semantic and hybrid are intentionally not run without a real embedding
provider. Human review, provider-backed verification/chat/agent predictions,
and a single frozen FINAL run remain open. Do not mark Phase 15B or Phase 16
complete based on the draft ledgers.

### Phase 15C — review/provider gates (in progress)

The real ledgers now have a read-only 160-case schema/evidence audit and a
minimal local reviewer at `backend/evaluation/review_cli.py`. Reviewer metadata
is part of every case schema, and reviewed-only scoring fails closed. No human
reviewer or provider credentials are present in this workspace, so no labels
were promoted and no semantic, verification, chat, or agent predictions were
fabricated. Phase 15C remains open pending genuine review and provider-backed
DEV baseline runs.
