# PaperLens Build Plan

## Current Phase

Phase 8 — Advanced Research Intelligence

## Current Milestone

Source-first artifacts, optional hybrid retrieval, persistent research workspaces, evidence-safe comparison, and a bounded citation graph.

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

## Current

- [x] Install project dependencies in an isolated `.venv` and frontend workspace.

## Later

- [ ] Begin Phase 9 — Research Agent and Literature Discovery.
- [ ] Consider animation only after the reader is stable.

## Blockers

- Frontend dependency audit reports 3 high-severity transitive findings; review before deployment.

## Explicitly Out of Scope for Current Phase

- External literature discovery, autonomous research agents, multi-paper chat, generated code, animations, and distributed workers.
- Image understanding or arbitrary image/file serving; artifacts remain caption/table/equation/reference evidence.
- Live external AI extraction without configured credentials.
