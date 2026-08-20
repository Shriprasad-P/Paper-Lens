# PaperLens Build Plan

## Current Phase

Phase 2 — arXiv Ingestion

## Current Milestone

End-to-end arXiv ingestion with normalized sections, persistence, API response, and frontend rendering.

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

## Current

- [x] Install project dependencies in an isolated `.venv` and frontend workspace.

## Later

- [ ] Normalize parsed documents with stable paragraph/section IDs and register evidence.
- [ ] Add semantic extraction with typed PaperIR components.
- [ ] Add deterministic visual reader and evidence drawer.
- [ ] Add verification, retrieval, and paper-grounded chat.
- [ ] Consider animation only after the reader is stable.

## Blockers

- Frontend dependency audit reports 3 high-severity transitive findings; review before deployment.

## Explicitly Out of Scope for Current Phase

- Semantic extraction, vector search, chat, generated code, animations, and distributed workers.
