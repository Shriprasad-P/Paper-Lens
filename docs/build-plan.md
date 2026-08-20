# PaperLens Build Plan

## Current Phase

Phase 5 — Visual Reader

## Current Milestone

Interactive, evidence-linked visual reader over persisted PaperIR and source PDFs.

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
- [x] Add KaTeX equation explorer and safe original-expression fallback.
- [x] Add Recharts numeric result view with table/text fallback.
- [x] Add lazy multi-record evidence drawer and source PDF page navigation.
- [x] Validate reader API/source safety, backend regressions, frontend build, and dependency audit.

## Current

- [x] Install project dependencies in an isolated `.venv` and frontend workspace.

## Later

- [ ] Add verification, retrieval, and paper-grounded chat.
- [ ] Consider animation only after the reader is stable.

## Blockers

- Frontend dependency audit reports 3 high-severity transitive findings; review before deployment.

## Explicitly Out of Scope for Current Phase

- Verification, vector search, paper-grounded chat, generated code, animations, and distributed workers.
- Reliable parser-level figure/table/equation/reference extraction beyond the typed source models.
- Live external AI extraction without configured credentials.
