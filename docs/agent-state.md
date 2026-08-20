# PaperLens Agent State

## Architecture

Phase 2 vertical slice: FastAPI + SQLAlchemy persistence, constrained arXiv client, deterministic PDF storage, PyMuPDF section parser, and Next.js ingestion/reader UI. Evidence registration and semantic PaperIR components remain Phase 3+.

## Implemented

- Repository engineering rules and project documentation.
- Backend settings, health endpoint, and database abstraction.
- Next.js App Router shell with PaperLens landing page.
- Focused backend unit tests for configuration and persistence.
- arXiv URL/ID normalization with host and path safety checks.
- Metadata/PDF retrieval, PDF validation, section parsing, persistence, idempotency, and typed ingestion API.
- Frontend request states and normalized paper reader view.

## Current Phase

Phase 2 — arXiv Ingestion

## Current Task

Complete and validate the first arXiv ingestion vertical slice.

## Validation

- `.venv/bin/python -m unittest discover -s backend/tests` — 11 tests passed.
- `.venv/bin/python -m compileall -q backend/app backend/tests` — passed.
- `npm run typecheck` — passed.
- `npm run lint` — passed.
- `npm run build` — passed.
- Live arXiv service and FastAPI endpoint checks for `1706.03762` — completed successfully.

## Known Problems

- `npm install` reports 3 high-severity transitive audit findings; no automatic force-fix was applied.
- Frontend browser-level interaction has not been automated; build/typecheck/lint cover the current shell.

## Important Decisions

- Keep SQLAlchemy engine/session wiring behind `SQLDatabase`; SQLite is the local default and PostgreSQL remains portable.
- Use `arxiv:<canonical-id>` as the unique source identity and hash it into a stable internal paper ID; versions remain distinct.
- Keep arXiv transport constrained to expected hosts and generated endpoints; never accept an arbitrary download URL.
- Keep frontend loading state tied to the single actual ingestion request; no fake timed progress.

## Next Recommended Task

Phase 3 — Structured Document + Evidence Registry.
