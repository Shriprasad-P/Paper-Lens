# PaperLens Agent State

## Architecture

Phase 10 vertical slice: Phase 2 arXiv ingestion, Phase 3 StructuredDocument/EvidenceRegistry, Phase 4 evidence-grounded PaperIR, Phase 5 deterministic visual reader, Phase 6 claim-level faithfulness verification, Phase 7 single-paper evidence-grounded chat, Phase 8 research intelligence, Phase 9 research agent/discovery, and Phase 10 offline evaluation/benchmarking.

## Implemented

- Repository engineering rules and project documentation.
- Backend settings, health endpoint, and database abstraction.
- Next.js App Router shell with PaperLens landing page.
- Focused backend unit tests for configuration and persistence.
- arXiv URL/ID normalization with host and path safety checks.
- Metadata/PDF retrieval, PDF validation, section parsing, persistence, idempotency, and typed ingestion API.
- Frontend request states and normalized paper reader view.
- StructuredDocument, PaperSection, PaperParagraph, SourceRegion, typed PaperIR shell, and extraction states.
- Deterministic normalization/content hashes and paragraph evidence registry.
- Transactional document/section/paragraph/evidence persistence and retrieval APIs.
- Frontend source paragraph list with evidence drawer.
- Provider-neutral AI abstraction with OpenAI-compatible adapter, bounded schema retries, and prompt registry.
- Deterministic section classification, focused evidence selection, ten independent extractors, and PaperIR conversion.
- Evidence ID validation, explicit/inferred origins, extraction states, cache keys, and analysis persistence/API.
- Minimal analysis UI with origin badges and evidence interaction.
- Typed ReaderResponse endpoint with compact document/source metadata and deterministic VisualizationSpec planning.
- `/papers/{paper_id}` reader route with navigation, overview, problem/gap/contribution sections, partial-state handling, and responsive layout.
- React Flow method graph with deterministic layout plus accessible textual method outline.
- KaTeX equation rendering with original-expression fallback and undefined-variable messaging.
- Recharts numeric result visualization with textual/table fallback and preserved numeric values.
- Multi-record evidence drawer with session cache, source metadata, and PDF page navigation.
- Typed `VerificationStatus`, `VerificationOutput`, `VerificationResult`, summary, and API response models kept separate from PaperIR.
- Stable claim collection for semantic PaperIR objects, including method summaries/steps and available equation interpretations/experiment fields.
- Focused `FaithfulnessVerifier` prompt and service with deterministic evidence/document/numeric pre-validation, safe `UNVERIFIED` fallback, partial failure isolation, and prompt-injection rules.
- Versioned `claim_verifications` persistence with claim/evidence/document/provider/model/prompt/schema cache keys.
- `POST /api/papers/{paper_id}/verify` and `GET /api/papers/{paper_id}/verification` APIs.
- Reader verification summary, manual verify/reverify action, per-claim badges, and unsupported/contradictory overview/chart suppression.
- Provider-neutral `BM25EvidenceRetriever` (`bm25-v1`) over paragraph Evidence Registry records, preserving scientific tokens and using bounded section-aware scoring.
- Paper Chat context assembly with `CHAT_RETRIEVAL_TOP_K=8`, `CHAT_MAX_CONTEXT_CHARS=12000`, a configurable relevance floor, and local retrieval caching.
- Persistent `ChatSession`/`ChatMessage` records bound to `document_id` and `document_hash`; historical sessions freeze when the paper is re-ingested.
- Structured Paper Chat output, citation/document-version validation, numeric fidelity checks, prompt-injection boundaries, and explicit insufficient/generation-failure states.
- Session/history/message APIs and reader Paper Chat panel with citation buttons wired to the existing evidence drawer and PDF page navigation.
- Source-first figure/table/equation/reference parsing, typed artifact persistence, registry evidence IDs, and reader artifact sections.
- Provider-neutral semantic retrieval with deterministic hash provider, SQLite embedding cache keyed by evidence hash/model/version, cosine scoring, RRF fusion, and lexical fallback.
- Retrieval evaluation fixtures for Recall@K, MRR, and Hit@K.
- Persistent workspaces, paper membership APIs/UI, comparison IR with paper/document/evidence identity, safe comparability labels, and numeric-rank suppression.
- Bounded citation graph API/UI matching exact extracted arXiv references to papers already in the local database.
- Namespaced persistence safeguard for legacy section/paragraph/evidence IDs when multiple documents share a database.

## Phase 9 Additions

- Persistent `ResearchRun`, plan/query/candidate/event/report records with observable stage transitions and immutable original questions.
- Deterministic `ResearchPlanner` fallback plus official arXiv Atom discovery, version/DOI/title normalization, conservative deduplication, ranking, and bounded selection.
- Bounded research-agent loop (maximum three iterations) with coverage/refinement, no-new stopping, cancellation, partial ingestion failures, workspace attachment, and concurrency limit two.
- Cross-paper lexical/semantic/hybrid Evidence Registry retrieval and composite `(paper_id, document_id, evidence_id)` citation validation, including numeric fidelity checks.
- Deterministic report sections for claims, themes, methods, agreements, safe contradictions, calibrated gaps, limitations, future directions, and selected-paper summaries.
- `/research` and `/research/{run_id}` UI with persisted event progress, cancellation, report sections, and evidence-drawer citation navigation.
- Separate `backend/evaluation` package with versioned manifest, annotation schemas/import-export, deterministic fixture expansion, metric implementations, component runners, failure taxonomy, and JSON/Markdown reports.
- Offline CLI commands for smoke, parsing, extraction, verification, retrieval, chat, research-agent, synthesis, and all; live mode is explicit and never implicit.

## Phase 11 Additions

- Next.js and `eslint-config-next` migrated from the Phase 10 15.x line to 16.3.1; the lockfile's production audit is clean.
- Typed configuration validation rejects malformed URLs, wildcard credentialed CORS, unsafe production schema auto-creation, and invalid limits.
- Request IDs, structured bounded request logs, Prometheus text metrics, `/health/live`, `/health/ready`, conservative security headers, typed error envelopes, and JSON request limits are active.
- arXiv PDF downloads stream under byte limits, validate final redirect hosts, and parser page/text limits prevent hostile documents from expanding memory.
- SQLite enables foreign keys/WAL/busy timeout/pre-ping; an Alembic scaffold provides explicit production migrations; candidate/workspace/cache identities remain idempotent.
- Restart recovery marks unfinished ingestion `FAILED` and active research runs `INTERRUPTED` with an append-only event; cancellation remains persisted and does not delete valid artifacts.
- AI provider failures have normalized codes and bounded jittered retries for transient failures only; no-key reader/retrieval behavior remains safe.
- Playwright deterministic mocks cover reader, source PDF, evidence drawer, Paper Chat entry, workspaces, research entry, and ingestion failure; CI runs backend/evaluation/frontend/E2E gates.
- Production, operations, security, migration, retention, and known-risk guidance is documented.

## Current Phase

Phase 17 — Unified Interactive Paper (V1 implemented; review uncommitted)

## Current Task

Replaced the fragmented visual-reader destinations with one evidence-grounded
InteractivePaper: typed mixed-content blocks, visualization IR, inline
renderer, staged local generation through the existing AIProvider, and the
existing evidence drawer / Ask PaperLens chat.

## Validation

- macOS toolchain (`tauri info`) — macOS 26.6.2 arm64, Xcode 26.6, Rust/Cargo, Tauri CLI 2.11.4 — passed.
- Standalone PyInstaller sidecar — fresh SQLite/Alembic migration, loopback readiness, unauthorized 401, authorized 200, clean stop — passed.
- Release bundle — `PaperLens.app` built with `com.paperlens.app`, version `0.1.0`, generated icon, embedded backend/Node/frontend resources, and no detected secret strings — passed.
- Real app launch — Tauri window rendered the existing PaperLens landing UI; dynamic ports, Application Support directories, desktop logs, and child readiness were observed.
- Desktop auth regression — CORS preflight, token rejection, and token acceptance covered by backend tests.
- Process lifecycle — backend/frontend process groups were terminated on close with no remaining PaperLens sidecars — passed.
- Desktop Rust helper tests — `cargo test` passed (2 tests covering loopback free-port selection and URL encoding).
- One-button run action — `./script/build_and_run.sh --verify` built and launched the final bundle to `desktop_ready`; fresh startup sample was 15 seconds.
- Port conflict — an occupied `127.0.0.1:18000` was bypassed with dynamic ports `50148`/`50149`.
- Crash detection — terminating the supervised backend recorded `backend_stopped`, followed by clean app shutdown.
- Bundle footprint — 219 MB; observed resident sample was approximately 102 MB Tauri shell, 124 MB backend process group, and 94 MB Next.js server.
- Detailed macOS commands and known boundaries are recorded in [docs/macos.md](macos.md).

- `.venv/bin/python -m unittest discover -s backend/tests` — 11 tests passed.
- `.venv/bin/python -m compileall -q backend/app backend/tests` — passed.
- `npm run typecheck` — passed.
- `npm run lint` — passed.
- `npm run build` — passed.
- Live arXiv service and FastAPI endpoint checks for `1706.03762` — completed successfully.
- `.venv/bin/python -m unittest discover -s backend/tests` — 62 tests passed, including Phase 11 security/recovery/idempotency coverage.
- Live Phase 3 check for `1706.03762` — Phase 2 response remained 17 sections; normalized document returned 22 sections, 538 paragraphs, and evidence API returned HTTP 200.
- Frontend typecheck/lint/build — passed after evidence drawer integration.
- `.venv/bin/python -m unittest discover -s backend/tests` — 23 tests passed.
- Live Phase 4 safe path — arXiv ingestion and extract API returned HTTP 200 with `FAILED`/`NO_EVIDENCE` states under `AI_PROVIDER=none`; no fake claims created.
- Mocked provider tests — schema retry, prompt-injection/grounding rejection, partial failure, cache reuse, numeric fidelity, and analysis API passed.
- Live arXiv structural integration with a dynamic mock provider — 17 legacy sections, 22 normalized sections, 538 paragraphs, persisted PaperIR, and valid evidence references.
- `.venv/bin/python -m unittest discover -s backend/tests` — 26 tests passed, including ReaderResponse, source-PDF safety, and visualization-planner coverage.
- `npm run typecheck` — passed after clearing ignored stale `.next` declarations.
- `npm run lint` — passed.
- `npm run build` — passed with `/papers/[paperId]` dynamic reader route.
- `npm audit --omit=dev` — three high-severity findings remain in `postcss`/`sharp` through Next 15; remediation requires a breaking Next 16 upgrade, so no force fix was applied.
- Live arXiv reader smoke test — `1706.03762` returned HTTP 200 for extraction, reader, evidence, and PDF source; reader reported 22 normalized sections and 538 paragraphs.
- `.venv/bin/python -m unittest discover -s backend/tests` — 33 tests passed, including all verification statuses, deterministic validation, prompt-injection handling, numeric fidelity, cache invalidation, persistence, unavailable-provider behavior, and API coverage.
- `npm run typecheck` — passed with verification view models and reader integration.
- `npm run lint` — passed.
- `npm run build` — passed with verification summary/badges in the dynamic reader route.
- Live external verification — not run; no AI credentials configured. The no-credential path persists safe `UNVERIFIED` results.
- `.venv/bin/python -m unittest discover -s backend/tests` — 46 tests passed, including all Phase 1–7 regressions plus Phase 8 artifact persistence, semantic cache/retrieval, RRF hybrid, evaluation, workspace, comparison, citation-graph, and multi-document collision coverage.
- `.venv/bin/python -m compileall -q backend/app backend/tests` — passed after Paper Chat integration.
- `npm run typecheck` — passed after clearing stale generated `.next/* 2` artifacts from the unrelated backup copy.
- `npm run lint` — passed.
- Live external Paper Chat generation — not run; no AI credentials configured. Retrieval remains locally testable and mocked generation is covered.
- Live retrieval smoke for `1706.03762` — temporary in-memory ingest returned 538 normalized paragraphs. Attention queries ranked application/multi-head attention passages on pages 5; dataset queries surfaced the WMT 2014 training passage on page 7; results queries surfaced narrative/table-result passages on pages 9–10; contribution queries ranked the introduction contribution passage on page 1. No live external chat generation was attempted.
- `npm run typecheck` — passed with Phase 8 workspace/comparison models and artifact reader sections.
- `npm run lint` — passed with Phase 8 workspace/comparison pages.
- Semantic live-provider benchmark — not run; default `EMBEDDING_PROVIDER=none` keeps lexical retrieval active. Deterministic hash-provider cache and hybrid tests passed.
- Phase 9 backend tests — passed, including planner/discovery normalization, dedup/ranking, cross-paper identity, citation validation, and run/event persistence.
- Phase 9 frontend typecheck/lint/build — passed with `/research` and `/research/{run_id}` routes.
- Live discovery and live AI synthesis — not run; tests use bounded arXiv Atom mocks and deterministic no-credential behavior.
- Phase 10 metric/schema/fixture tests — passed with deterministic offline runners; generated reports are marked `PRELIMINARY`.
- Full live benchmark — not run; no external AI, embedding, arXiv acquisition, or paid evaluation is invoked by default.
- Phase 11 dependency audit — `npm audit --omit=dev` clean after Next.js 16.3.1 migration (network audit rerun with registry access).
- Phase 11 frontend gates — `npm run typecheck`, `npm run lint`, `npm run build`, and `npm run test:e2e` passed.
- Phase 11 compile/evaluation smoke — passed after middleware, migration, recovery, provider, and resource-limit changes.
- Phase 11 local performance sample (fixture, 40–50 iterations, TestClient): `/health/live` p50 1.297 ms / p95 1.783 ms; document reader endpoint p50 2.734 ms / p95 3.325 ms; BM25 retrieval p50 1.220 ms / p95 1.438 ms. These are local reference measurements, not production SLAs.
- Phase 12 backend regression suite — 67 tests passed; compileall and evaluation smoke passed.
- Phase 13A backend regression suite — 70 tests passed, including two-user account/session lifecycle, workspace/paper/document/evidence/PDF/chat/research IDOR isolation, anonymous shared-mode 401 behavior, and hash-only session persistence.
- Phase 13A migration smoke — Alembic upgrade on the existing local database passed; fresh schema inspection found users, auth_sessions, audit_log, and owner_id columns with deterministic legacy backfill.
- Phase 13A frontend gates — credentials-enabled API client typecheck, lint, and production build passed.
- Phase 12 frontend typecheck, lint, production build, and Playwright — passed; 3 browser tests passed.
- Real PostgreSQL 15.17 migration upgrade/current and base→head migration drill — passed; container PostgreSQL 16 Compose migration/readiness — passed.
- PostgreSQL persistence smoke covered paper/document/evidence, PaperIR, verification, chat, workspace, research run, embeddings, and idempotency — passed.
- Production-like Docker images built and ran as non-root; Compose frontend/backend/PostgreSQL health checks passed; deployment smoke passed.
- npm audit — 0 vulnerabilities; pip-audit — no known vulnerabilities; Trivy 0.57.1 HIGH/CRITICAL scans — 0 findings for both rebuilt images; secret scan found no committed secrets.
- Bounded load probe at concurrency 4: health/live p50 2.638 ms/p95 18.954 ms, health/ready p50 4.775 ms/p95 6.422 ms; PostgreSQL-backed reader p50 38.446 ms/p95 60.722 ms; evidence p50 6.411 ms/p95 8.167 ms; all error rates 0.0%.

## Known Problems

- Metrics are process-local and should be scraped per worker or replaced with a shared collector before horizontal scaling.
- PostgreSQL compatibility remains SQLAlchemy-portable but a live PostgreSQL integration run is environment dependent.
- Browser tests use deterministic API mocks; deployment-specific origin/proxy/PDF smoke tests remain required.
- Figure/table/equation/reference extraction is deterministic and source-first; image bytes and visual interpretation remain unavailable.
- No AI credentials are configured, so live external model extraction was not run.
- Source-region PDF highlighting is intentionally deferred; page navigation is supported.
- Verification uses concise provider rationales only; raw model reasoning is never exposed.
- Paper Chat citations use only current retrieved Evidence Registry IDs; history is reference context, never evidence, and old sessions are frozen across document replacement.
- Comparison does not rank papers unless structured comparability is explicit; results retain paper-specific context.
- Citation graph matching is local, preferring exact arXiv IDs with normalized-title fallback; no external citation discovery is attempted.
- Phase 9 discovery currently ships with official arXiv Atom only; DOI/index providers and live AI synthesis remain optional future adapters.
- Report claims are intentionally `UNVERIFIED` on the deterministic path; broad scientific quality metrics require the Phase 10 benchmark fixtures.
- Phase 10 results are intentionally `PRELIMINARY`: corpus metadata is identifier-only, annotation coverage is a starter JSONL, and offline fixture scores are not live system quality claims.
- Phase 15B now records 35 exact versioned arXiv PDF snapshots, SHA-256 source hashes, 35 production-ingested PaperLens documents, 34,117 Evidence Registry rows, paper-separated DEV/FINAL splits, and a frozen real BM25 envelope. Phase 15C adds a 160-case schema/evidence audit, explicit reviewer metadata fields, and a minimal local review CLI. Real ledgers remain DRAFT with zero human reviewers; semantic/hybrid and provider-backed verification/chat/agent runs are still intentionally not measured.
- HTTPS edge termination remains provider-specific; the local Compose harness is HTTP and must sit behind managed TLS/reverse-proxy ingress for public beta.
- Metrics and beta rate limits remain process-local; add shared collection/edge limiting before horizontal scaling.
- Local development without authentication intentionally uses the deterministic legacy principal; staging/production require registered sessions. The desktop token is a local-only development principal and is rejected as an authentication bypass when shared auth is required.

## Phase 14 Additions

- Manual and research-triggered PDF ingestion share `IsolatedPaperParser`, a
  fresh child-process boundary around native PyMuPDF traversal.
- Byte/signature checks happen before child startup; page limits precede text
  traversal; total/per-page text and image-xref budgets stop work incrementally.
- Parent-enforced wall-clock timeout, cancellation cleanup, bounded parser
  concurrency, safe error taxonomy, parse metrics, and structured events are
  active. Normalization/evidence persistence is staged until parsing succeeds.
- Unix CPU/address-space limits are best effort and platform dependent; docs
  state the remaining native-parser and process-local metric limitations.

## Important Decisions

- Keep SQLAlchemy engine/session wiring behind `SQLDatabase`; SQLite is the local default and PostgreSQL remains portable.
- Use `arxiv:<canonical-id>` as the unique source identity and hash it into a stable internal paper ID; versions remain distinct.
- Keep arXiv transport constrained to expected hosts and generated endpoints; never accept an arbitrary download URL.
- Keep frontend loading state tied to the single actual ingestion request; no fake timed progress.
- Keep Phase 2's legacy section response stable while the normalized document adds paragraph-level provenance.
- Replace a paper's active normalized document transactionally on re-normalization; never mix evidence versions.
- Keep `PaperIR` semantic content empty or explicitly stateful when no relevant evidence or provider output is available; never fabricate claims.
- Keep semantic output provider-neutral, schema-validated, and evidence-validated before persistence.
- Keep explicit author statements distinct from model-inferred interpretations in data and UI.
- Cache analysis by document hash, prompt/schema version, provider, and model.
- Keep reader responses compact: semantic PaperIR and document metadata load initially; evidence bodies and source passages load on demand.
- Serve PDFs only through an ownership-checked API route rooted under `PAPERLENS_STORAGE_PATH`; never expose local filesystem paths.
- Keep visualization planning deterministic and renderer-neutral; React Flow/Recharts/KaTeX consume validated persisted data only.
- Keep verification separate from extraction so claim text remains immutable and verifier/prompt/model changes are auditable.
- Require deterministic evidence/document/numeric checks before provider calls; failures become `UNVERIFIED`, not `UNSUPPORTED`.
- Cache verification by claim/evidence/document/provider/model/prompt/schema versions and hide stale results from the current reader.
- Research execution is database-authoritative: `research_execution_attempts` stores hashed claim tokens, bounded leases, heartbeats, retry classification, and attempt history; stale workers are fenced before run, report, event, workspace, or child-record writes.
- Execute requests enqueue and return `202`; `ResearchWorker` polls the database for both server and desktop modes. Cancellation is durable and dominant, and terminal runs are never reclaimed.

## Next Recommended Task

Phase 15 measurement is not closed yet. Phase 15D now provides explicit
review/exclusion states, append-only annotation change logging, and a read-only
25/50/75/100% progress report. The next task is genuine human review of the
real ledgers; only after that may later work configure an intended
embedding/provider path, freeze verification/chat/agent predictions, and run
one FINAL offline report without tuning on FINAL.

Phase 15E-P now adds a separate provisional DEV evaluator and embedding
architecture audit. The report contract is explicit (`PROVISIONAL`, `DRAFT`,
zero human reviewers, not publishable); FINAL rows are excluded before
scoring, the historical BM25 DEV baseline is preserved, and semantic/Hybrid
plus provider-backed verification/chat/agent lanes remain `NOT_RUN` because
no real providers are configured. The current artifacts are intentionally
uncommitted and Phase 15E-P/15 remain open.

Phase 15E-R audits the actual runtime and provider configuration without
contacting external services or exposing secrets. PaperLens now has a genuine
key-free Ollama path for generation and embeddings; prompt hashes and a
provisional retrieval/RRF/generation/schema configuration hash remain
recorded. Semantic, Hybrid, verification, chat, and durable-agent lanes stay
`NOT_RUN` until an explicit DEV run; Phase 15E-R is not closed.

Phase 15E-S audits local runtime enablement without installing a broad ML
stack or changing provider abstractions. Ollama is installed with `qwen3:4b`
and `nomic-embed-text`; real local AI and 768-dimensional embedding smoke
tests pass through the existing adapters. Ollama uses Metal when available
and can fall back to CPU. The optional MLX/Qwen path remains discoverable but
is not used when its device import fails. Semantic, Hybrid, verification,
chat, and durable-agent lanes remain `NOT_RUN` until an explicit DEV run. The
Phase 15E-S artifacts are provisional, uncommitted, DRAFT-gold, and
non-publishable; Phase 15E-S and Phase 15 overall remain open.

## Phase 16A — staging closure validation (not closed)

Real Playwright Chromium coverage and the supported Tauri arm64 package were
executed from `/Users/shriprasad/Documents/Projects/PaperLens`. The browser
auth/workspace/real-ingestion/reader/evidence/chat/citation/failure/reload
path passed through the research status assertion. The packaged app built,
launched its bundled backend/frontend on dynamic loopback ports, reused local
Ollama configuration, and wrote `database_ready backend_ready` plus
`frontend_ready desktop_ready` logs. The original durable `PARTIAL` run was
classified as legitimate degraded behavior after a safe source-save failure.
Two fresh runs preserved valid reports/evidence but ended `PARTIAL` because
the fixed 180-second per-paper Ollama analysis step timed out. No model,
prompt, quality, or budget tuning was performed. Phase 16A and Phase 16 remain
open because a fresh `COMPLETED` happy-path agent run was not proven; Phase 15
remains `NOT CLOSED` with DRAFT annotations and zero human reviewers.
