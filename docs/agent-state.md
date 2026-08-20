# PaperLens Agent State

## Architecture

Phase 5 vertical slice: Phase 2 arXiv ingestion, Phase 3 StructuredDocument/EvidenceRegistry, Phase 4 evidence-grounded PaperIR, and a deterministic visual reader with lazy evidence and PDF page navigation.

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

## Current Phase

Phase 5 — Visual Reader

## Current Task

Complete and validate the persisted PaperIR visual reader.

## Validation

- `.venv/bin/python -m unittest discover -s backend/tests` — 11 tests passed.
- `.venv/bin/python -m compileall -q backend/app backend/tests` — passed.
- `npm run typecheck` — passed.
- `npm run lint` — passed.
- `npm run build` — passed.
- Live arXiv service and FastAPI endpoint checks for `1706.03762` — completed successfully.
- `.venv/bin/python -m unittest discover -s backend/tests` — 15 tests passed.
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

## Known Problems

- `npm install` reports 3 high-severity transitive audit findings; no automatic force-fix was applied.
- Frontend browser-level interaction has not been automated; no Playwright setup existed and build/typecheck/lint plus API tests cover the reader boundary.
- Figure, table, equation, and reference extraction models exist but are intentionally empty.
- No AI credentials are configured, so live external model extraction was not run.
- Source-region PDF highlighting is intentionally deferred; page navigation is supported.

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

## Next Recommended Task

Phase 6 — Verification.
