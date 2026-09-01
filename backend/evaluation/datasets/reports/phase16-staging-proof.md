# PaperLens Phase 16 — staging / public-beta proof

**Result: NOT CLOSED.** This is an evidence report, not a claim that PaperLens
is ready for a broad public beta. The real browser flow and packaged macOS
bundle were exercised, but the strict browser happy-path research assertion
and both fresh agent closure runs ended `PARTIAL` because local-model paper
analysis exceeded the configured 180-second per-paper step timeout. No P0
blocker was observed; public upload-based parser-failure injection remains
unavailable.

The machine-readable source is
[`phase16-staging-proof.json`](./phase16-staging-proof.json). All changes remain
uncommitted as requested; no push, pull request, or attribution was created.

## 1. Baseline and staging topology

| Item | Observed |
| --- | --- |
| Baseline commit | `a9dacee5ceb0b28183efd35580c5856f07559aff` |
| Working tree | Intentionally dirty (50 modified/untracked paths); no Phase 16 commit |
| Validation runtime | Python 3.14.2 in `.venv`; baseline capture recorded system Python 3.13.9 |
| Frontend / Rust | Node v26.7.0; rustc 1.92.0 |
| Host | macOS 26.6.2, arm64 |
| AI runtime | Ollama 0.32.11; `qwen3:4b` and `nomic-embed-text` |
| Database | PostgreSQL 15.17, disposable cluster on `127.0.0.1:55432` |
| API | Independent FastAPI/uvicorn process, `127.0.0.1:18080` |
| Worker | Independent `app.research.worker` process; API worker disabled |
| Storage | Persistent local path `/tmp/paperlens-phase16-storage` for this disposable proof |

```text
Browser / desktop launcher
            |
            v
       Next.js frontend (13000)
            |
            v
       FastAPI API (18080) ------> Ollama (loopback)
            |
            v
        PostgreSQL <------------- independent research worker
            |
            v
     persistent paper/artifact storage
            |
            v
     isolated Phase 14 PDF parser children
```

The reproducible startup sequence is documented in
[`docs/phase16-staging.md`](../../../../docs/phase16-staging.md), and the deterministic
operator smoke procedure is
[`phase16_staging_smoke.py`](../../phase16_staging_smoke.py). The smoke run
passed readiness, authentication, workspace creation, document access, a
terminal durable worker run, Ollama embedding, and Ollama generation without
credentials stored in source.

## 2. Database, durability, and lifecycle

- A fresh PostgreSQL database migrated successfully through
  `0003_phase13b_durable_execution`. The final schema contains 26 public
  application tables, including users/sessions, ownership, queue attempts,
  events, reports, evidence, and chat. Evaluation files did not become product
  tables.
- API restart and PostgreSQL stop/start preserved the authenticated user,
  workspace, ingested paper, reader payload, source artifact, and research-run
  terminal state. Liveness stayed 200 during the database outage; readiness
  returned 503 and recovered to 200 after PostgreSQL restarted.
- A real arXiv paper (`1406.2661`, PaperLens ID
  `paper_6ec7b69be1767e34`) reached `COMPLETED`. The isolated parser produced
  20 sections, 253 paragraphs, 3 figures, 2 tables, 18 equations, and 61
  references. Its evidence and 337 embeddings survived restart.
- PostgreSQL audit after the crash/concurrency exercises found 1,419/1,419
  distinct evidence IDs, 866/866 distinct embedding IDs, one durable agent
  report, and no duplicate final output or corrupt terminal row.

## 3. Worker and agent proof

- The independent worker claimed and executed API-created run
  `research_9b3340ee1f2e477a90078dd1fe231c8e`. Durable planning, discovery,
  candidate selection, ingestion, analysis, verification, and report events
  were present. The terminal run was `PARTIAL`: one real discovered source
  failed to save (`2109.03378`, safe error `The paper could not be saved.`)
  while two papers completed. This is legitimate degraded-run behavior and
  the report contains only the two ingested papers' registry-grounded data.
- Phase 16A rerun `research_999b1e1582754abcafe148afe4fdf77f` ingested three
  selected papers with zero ingestion failures, saved one report, and ended
  `PARTIAL` after two paper analyses exceeded the fixed 180-second
  `research_step_timeout` (the durable events record empty `TimeoutError`
  messages). A second fresh run `research_62d2ae9d763c461d938160c88d696026`
  repeated the expected terminal semantics: three papers and one report,
  with two analysis timeouts and one cached analysis. No state-machine or
  publication race was observed; each run had one report and valid evidence.
- Lease recovery on PostgreSQL passed: after attempt 1 expired, another worker
  reclaimed attempt 2; the stale worker’s completion returned false. The
  database contained the expected `LOST`, `CLAIMED`, and `LEASE_EXPIRED` fence
  evidence.
- Two workers claimed distinct queued runs atomically. Attempt numbering and
  terminal states were unique; a third queued run was later picked up.
- Cancellation passed with a real running run: `CANCEL_REQUESTED`, lease and
  cancellation events were durable, and the final state was `CANCELLED` with no
  report overwrite.

## 4. Security and local-only inference

- Registration, login, session cookie, logout, revoked-cookie rejection, and
  protected-route rejection passed under staging auth (`HttpOnly`, explicit
  path/max-age; HTTPS `Secure` was not applicable to the local HTTP proof).
  Expired-session and disabled-user cases were not exercised.
- User B received 404 for User A’s workspace, reader, source, evidence, and
  attachment attempts. Anonymous reader/source/evidence access returned 401.
- Unknown-origin credentialed mutation returned 403. Wildcard origins were
  not enabled. A traversal request such as
  `/api/papers/<id>/source/../../etc/passwd` returned 404.
- Generation and embeddings used only loopback Ollama. Ollama reported the
  models available and the direct embedding/generation smoke passed. External
  AI provider calls were **0**. arXiv discovery HTTP traffic was expected
  source retrieval, not an AI provider fallback.
- Three concurrent local generation requests all succeeded in 16.868 seconds;
  the observed small-machine envelope is three simultaneous requests, not a
  scale guarantee.

## 5. End-to-end product paths

| Path | Result |
| --- | --- |
| Login → workspace → real paper → parser → reader/evidence/embeddings | PASS |
| Hybrid/RRF chat → qwen3:4b → citation | PASS; `ANSWERED` in 7.29s, citation `ev_0005` resolved to page 1 / `sec_002` |
| Research request → independent worker → durable report | PASS as a flow; terminal runs were honestly `PARTIAL` |
| Cancellation during execution | PASS; terminal `CANCELLED`, no late report |
| Reader/source ownership and IDOR | PASS |
| Refresh/reopen after API/PostgreSQL restart | PASS for HTTP durable state; browser reload during a live run rehydrated its durable `PARTIAL` state |

The chat path exposed and fixed a product compatibility issue during this
phase: hybrid RRF scores are rank-fusion scores, not cosine scores, so they are
no longer incorrectly rejected by the cosine relevance threshold. The focused
regression test is included in the backend suite.

## 6. Failure-injection matrix

| Failure | Expected behavior | Observed | Status |
| --- | --- | --- | --- |
| API restart | Durable state survives | Paper, reader, auth, and run state reloaded | PASS |
| Worker crash | Lease recovery | Attempt became `LOST`; second worker reclaimed; stale finalize fenced | PASS |
| PostgreSQL restart | Readiness fails then recovers | 503 while stopped, 200 after restart; reader data intact | PASS |
| Ollama unavailable | Safe AI failure | Not conclusively injected; desktop daemon auto-restarted before a request | SKIPPED |
| PDF parser failure | API remains alive; no false success | Real source failure became failed candidate and overall `PARTIAL` | PASS |
| Invalid session | Rejection | Revoked/anonymous protected routes returned 401 | PASS |
| Foreign resource | 404/deny | User B received 404 across resource/file paths | PASS |
| Research cancellation | `CANCELLED`, no late report | Durable cancellation and lease-expiry events; no report | PASS |
| Research rate limit | 429 with retry hint | Third request returned 429 with `Retry-After: 59` | PASS |

Malformed, oversized, page/text-limit, and parser-timeout injections were not
available through the current public staging API (there is no upload endpoint);
the isolated parser and limit behavior remain covered by the regression suite.

## 7. Frontend, desktop, and operations

- Frontend typecheck, lint, and optimized Next.js production build passed.
- Rust tests passed (2/2), and `cargo check` passed after a clean rebuild. The
  supported Tauri build produced an arm64 bundle at
  `desktop/src-tauri/target/release/bundle/macos/PaperLens.app` (211 MB).
  The packaged executable launched, created its Application Support
  database/log/papers/artifacts/cache directories, started its bundled
  backend and Next.js runtime on dynamic loopback ports, and served frontend
  and `/health/ready` requests. Logs recorded `database_ready backend_ready`
  and `frontend_ready desktop_ready`. The bundle is ad-hoc signed; paid
  distribution signing/notarization is not configured.
- `/metrics` returned 200 with parse, active, and provider counters. Metrics
  and rate limiting remain process-local and need an edge/shared layer before
  horizontal scaling.
- The staging environment template now explicitly distinguishes development
  SQLite defaults from PostgreSQL/Ollama staging, including origins, auth,
  persistent storage, migrations, and the separate worker setting.
- Docker CLI was present, but the Docker daemon was unavailable. Compose was
  statically reviewed; **Docker runtime validation unavailable**.
- Real Playwright browser automation ran against the PostgreSQL/Ollama staging
  API. Login, workspace creation, real `1406.2661` ingestion, reader,
  visualization/evidence interaction, hybrid Paper Chat/citation, controlled
  invalid-ingest failure, research enqueue, and reload were exercised. The
  strict assertion failed only because the run reached the legitimate
  `PARTIAL` terminal state, so the test did not reach its final logout/protected
  route assertions. The browser artifacts (screenshot, video, trace, and
  error context) remain ignored under `frontend/test-results/`.

## 8. Regression and Phase 15 guardrails

| Suite / invariant | Result |
| --- | --- |
| Backend | 107 tests run; 106 passed, 1 skipped; 0 failed |
| Phase 13A auth/ownership/IDOR/CSRF | PASS |
| Phase 13B queue/claims/cancellation/fencing | PASS |
| Phase 14 isolated parser and limits | PASS in regression; valid path PASS in staging |
| Phase 15 provenance/frozen/DRAFT/FINAL protection | PASS |
| Corpus drift | None detected; frozen artifacts not rewritten |
| Frontend | typecheck PASS; lint PASS; production build PASS |
| Rust / desktop code | 2 tests PASS; `cargo check` PASS |
| `git diff --check` | PASS |

Phase 15 quality status is deliberately unchanged:

- annotations: **DRAFT**
- human reviewers: **0**
- DEV evaluation: **PROVISIONAL**
- FINAL evaluation: **NOT RUN**
- publishable benchmark claims: **NO**
- Phase 15 overall: **NOT CLOSED**
- quality tuning in Phase 16: **NONE**

## 9. Findings and recommendation

**P0:** none observed.

**P1:** a local Ollama-backed agent analysis can exceed the fixed per-paper
step timeout, leaving a usable but `PARTIAL` report; the strict COMPLETED
happy-path could not be proven without changing the protected configuration.
The browser test therefore remains intentionally failing at the required
COMPLETED assertion. Public staging also cannot inject malformed/oversized/
timeout uploads.

**P2:** process-local metrics/rate limits, Docker-daemon dependency, and
existing framework deprecation/resource warnings.

**Recommendation:** conditional / not ready to claim full public beta. Phase 16A
and Phase 16 remain **NOT CLOSED** because the required fresh COMPLETED
research-agent happy path was not achieved without changing the protected
model/budget configuration. All changes are intentionally left uncommitted and
unpushed.

## 10. Phase 16A closure-validation detail

| Required field | Evidence |
| --- | --- |
| Original PARTIAL run / classification | `research_9b3340ee1f2e477a90078dd1fe231c8e`; expected degraded terminal state after safe `2109.03378` save failure; report/evidence for two successful papers preserved |
| Fresh runs | `research_999b1e1582754abcafe148afe4fdf77f` and `research_62d2ae9d763c461d938160c88d696026`; both `PARTIAL`, `execution_state=COMPLETED`, one report each |
| Fresh attempts / IDs | Attempt 1 for each run; durable `research_execution_attempts` rows and event sequences persisted; no stale publication |
| Browser framework/result | Playwright Chromium real staging run; core flow and reload reached the research status assertion; strict `COMPLETED` check failed on `PARTIAL` |
| Browser results | Auth/workspace/ingestion/reader/evidence/chat/citation/controlled failure/research enqueue/reload exercised; logout/protected-route assertions were not reached after the required happy-path failure |
| Package mechanism/result | Existing Tauri `npm run desktop:build`; arm64 `.app` built and direct executable launched |
| Package runtime | Bundled backend/frontend ready on dynamic ports; Ollama reuse configured for `qwen3:4b` and `nomic-embed-text`; writable state under `~/Library/Application Support/com.paperlens.app` |
| Packaged functional smoke | Authenticated desktop-token request, real `1406.2661` ingestion, reader reload, 337 persisted 768-dimensional embedding vectors, and real qwen3:4b Paper Chat (`ANSWERED`, valid citations) all passed |
| Package restart/failure boundaries | Clean stop followed by relaunch on new dynamic ports reloaded the ingested paper and embedding cache. Deliberate packaged Ollama outage was not run. |
| Local-only AI | Staging generation/embeddings and packaged configuration point only to loopback Ollama; external AI calls remained 0 |
| Regression gates | Prior Phase 16 suites remain green: backend 107 (106 pass/1 skip), frontend typecheck/lint/build, Rust tests/check; package build PASS; `git diff --check` PASS |
| Final decision | **Phase 16A NOT CLOSED; Phase 16 NOT CLOSED; Phase 15 NOT CLOSED.** No Phase 17 work started. |
