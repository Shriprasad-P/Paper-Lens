# PaperLens Agent State

## Architecture

Phase 4 vertical slice: Phase 2 arXiv ingestion, Phase 3 StructuredDocument/EvidenceRegistry, and focused provider-neutral research extraction with schema/evidence validation, PaperIR persistence, analysis APIs, and a minimal analysis UI.

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

## Current Phase

Phase 4 — Evidence-Grounded Research Extraction

## Current Task

Complete and validate focused evidence-grounded research extraction.

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

## Known Problems

- `npm install` reports 3 high-severity transitive audit findings; no automatic force-fix was applied.
- Frontend browser-level interaction has not been automated; build/typecheck/lint cover the current shell.
- Figure, table, equation, and reference extraction models exist but are intentionally empty.
- No AI credentials are configured, so live external model extraction was not run.

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

## Next Recommended Task

Phase 5 — Visual Reader.
