# Phase 17A — unmocked unified Interactive Paper closure

**Phase 17A: CLOSED. Phase 17 V1: CLOSED. Phase 15 overall: NOT CLOSED.**

This report records live browser proof only. It does not rewrite Phase 16
history and does not claim Phase 15 quality or FINAL metrics.

## Environment

| Item | Observed |
| --- | --- |
| Baseline commit | `fb6fd1e51abdcd3faec69d877c5f83eec05bb2e5` (`feat: add unified interactive paper reader`) |
| Branch | `main` |
| Working tree at baseline | Clean (Phase 17 V1 already committed). Phase 17A edits are left uncommitted. |
| Python | 3.14.7 (`.venv`) |
| Node | v24.13.0 |
| Playwright | 1.62.1 |
| PostgreSQL | 15.17 (Homebrew), disposable cluster `127.0.0.1:55433`, database `paperlens_phase17a`, migrated to `0004_phase17_interactive_paper` |
| Ollama | 0.32.11 |
| Generation | `qwen3:4b` id `359d7dd4bcda`, blob `sha256-3e4cb14174460404e7a233e531675303b2fbf7749c02f91864fe311ab6344e4f` |
| Embeddings | `nomic-embed-text:latest` id `0a109f422b47`, blob `sha256-970aa74c0a90ef7482477cf803618e776e173c007bf957f635f1015bfcfef0e6`, 768-d |
| External AI providers | none |
| Rust | rustc/cargo 1.92.0 |

## Staging topology

```text
Playwright Chromium
        |
        v
   Next.js frontend (127.0.0.1:13000, NEXT_PUBLIC_AUTH_REQUIRED=true)
        |
        v
   FastAPI (127.0.0.1:18080) ------> Ollama loopback
        |
        v
    PostgreSQL 55433 <------- independent research worker
        |
        v
   /tmp/paperlens-phase17a-storage (Phase 14 isolated parser children)
```

Credentials: runtime-only `PAPERLENS_E2E_PASSWORD` (not stored in the repo).
The spec registers a disposable `phase17a-*@example.test` account through the
normal UI. Auth was not weakened.

## Live command

```bash
PAPERLENS_E2E_PASSWORD=… \
PLAYWRIGHT_BASE_URL=http://127.0.0.1:13000 \
PLAYWRIGHT_SKIP_WEBSERVER=1 \
PHASE17A_OBSERVATIONS_PATH=/tmp/paperlens-phase17a-observations.json \
npx playwright test e2e/unified-paper.spec.ts --project=chromium
```

Result: **1 passed** in 2.9 minutes. The spec does not mock backends, Ollama,
or InteractivePaper JSON.

Paper artifacts (gitignored Playwright output) live under
`frontend/test-results/` on failure; the passing run did not retain a failure
trace. Console/network notes were attached as `phase17a-observations`.

## Paper

| Item | Observed |
| --- | --- |
| Identifier | `1406.2661` (Goodfellow et al., Generative Adversarial Networks) |
| PaperLens ID | `paper_5d57429b9ca8546f` |
| Document ID | `doc_105dc35283648993` |
| Source hash | `ff5819e3a7b713c3bd3107b7de3d51fe0a347aa5d8444f0efdcf2345ef0a8b63` |
| Document hash | `61e128288cba84bb26949e62c6eef5334c5aebb33da6fba17f1f70d6ae332a3a` |
| Ingestion | Fresh ingest for the E2E principal (COMPLETED) |
| Evidence count | 337 |
| Schema | `interactive-paper-v1` |
| Provider/model | `ollama` / `qwen3:4b` |
| Generation mode | `assembler` |
| Cache key | distinct per paper; 6 InteractivePaper rows / 6 papers / 6 cache keys |
| Blocks | 8 (`overview`, `problem`, `motivation`, `equation_explanation`, `experiment`, `result`, `figure_explanation`) |

## Browser results

| Check | Result |
| --- | --- |
| Login | PASS |
| Workspace create/own | PASS |
| Real ingest/open | PASS |
| InteractivePaper load | PASS |
| Outline navigation + hash | PASS (`#block_results` survived reload) |
| Simplified content | PASS (`block_overview`) |
| Inline visualization | PASS, type `pipeline`, reconstructed |
| Node interaction + evidence | PASS |
| Edge interaction | PASS; inferred relationship labeled |
| Equation KaTeX | PASS |
| Equation simple explanation / terms | NOT_APPLICABLE (persisted equation had no explanation/terms; not fabricated) |
| Equation evidence | PASS |
| Node–equation link | NOT_APPLICABLE |
| Figure | PASS (original figure, not a reconstruction masquerading as original) |
| Table | NOT_APPLICABLE (pipeline did not select an important table) |
| Result block | PASS |
| Limitation block | NOT_APPLICABLE |
| Contextual Ask PaperLens | PASS, status `ANSWERED`, local qwen3:4b |
| Chat citation | PASS |
| Reload/rehydration | PASS; no duplicate cache-key collision |
| Responsive 390×844 | PASS after PDF overlay fix |
| Controlled failure | PASS (invalid arXiv id → error card, no traceback) |
| Logout | PASS |
| Protected route after logout | PASS |
| Two-user browser | COVERED BY EXISTING PHASE 16 HTTP/BACKEND EVIDENCE plus new InteractivePaper 404 IDOR assertions |

## Console / network

Uncaught page errors: none. 401s are expected (session check, post-logout).
422 is the controlled invalid ingest. `net::ERR_ABORTED` on `/source` is the
PDF iframe being cancelled when the source panel closes; not treated as a
product defect.

## Defects fixed for closure

1. Visual edges serialized as JSON `from`/`to` via FastAPI aliases, so the
   frontend never recognized selected edges. Serialize `source`/`target`;
   select nodes/edges by id.
2. Source analysis collapsed once assembler blocks existed, hiding Analyze
   (needed for PaperIR-backed diagrams). Keep it open until analysis exists.
3. Desktop-open PDF stayed a full-viewport overlay after shrinking to a
   mobile width, blocking the outline toggle. Close the source panel below
   761px unless the user reopens it.

## Regression

- Backend: 119 tests OK, 1 skipped (clean environment).
- Frontend: typecheck, lint, production build PASS.
- Mocked Playwright `paperlens.spec.ts`: 5 passed.
- Live `unified-paper.spec.ts`: 1 passed.
- `cargo test` / `cargo check`: PASS.
- `git diff --check`: clean.

## Phase 15

annotations = DRAFT; human reviewers = 0; DEV metrics = PROVISIONAL;
FINAL = NOT RUN; publishable quality claims = NO.
