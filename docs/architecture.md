# PaperLens Architecture

Phase 6 extends the Phase 2–5 vertical slice with claim-level faithfulness verification while keeping parser, extraction, verification, and rendering stages separate:

```text
arXiv input
        ↓
identifier normalization
        ↓
arXiv metadata client + PDF downloader
        ↓
PyMuPDF section parser
        ↓
DocumentNormalizer
        ↓
StructuredDocument
        ├── Sections → Paragraphs
        └── EvidenceRegistry → Evidence
        ↓
normalized paper/document + SQLAlchemy persistence
        ↓
FastAPI + Next.js reader shell
        ↓
Evidence-grounded extractors → PaperIR
        ↓
VisualizationSpec + typed Reader API
        ↓
Next.js visual reader + evidence/PDF interaction
        ↓
PaperIR claim collection
        ↓
Evidence resolver + deterministic validation
        ↓
FaithfulnessVerifier → VerificationResult persistence
        ↓
Reader verification badges and summary
```

The current runtime has two independently deployable surfaces:

- `backend/app` exposes the FastAPI boundary and owns configuration and persistence wiring.
- `frontend/app` contains the Next.js App Router shell and does not make semantic claims about papers.

`SQLDatabase` owns SQLAlchemy engine/session wiring and currently defaults to SQLite for local development. The model keeps paper metadata and sections in separate tables, with a unique `source_identity` for idempotency. The stable internal ID is `paper_` plus the first 16 hex characters of SHA-256(`arxiv:<canonical-id>`); versioned arXiv identifiers intentionally have distinct identities because their source content may differ.

PDFs are stored as `data/papers/<paper-id>/source.pdf` (configurable through `PAPERLENS_STORAGE_PATH`) and are excluded from Git. The arXiv client only accepts `arxiv.org`/`export.arxiv.org` hosts and constructs the metadata/PDF endpoints itself, preventing arbitrary URL downloads.

## Structured document and evidence

`PyMuPDFPaperParser.parse_document` emits the parser-neutral `ParsedPaper`/`RawSection`/`RawParagraph` representation. `DocumentNormalizer` then creates `StructuredDocument`, `PaperSection`, and `PaperParagraph` models without interpretation or rewriting. The legacy `parse` method remains intact for the Phase 2 API response, which currently returns 17 sections for the integration paper; the normalized document can expose finer paragraph-level structure.

Paragraph IDs are deterministic within a document (`sec_001`, `para_0001`) and evidence IDs are deterministic (`ev_0001`). The document ID is `doc_` plus the first 16 hex characters of SHA-256(`paper_id:source_hash`). Paragraph content hashes use SHA-256 of the normalized source text. Page numbers and bounding boxes are copied only when PyMuPDF supplies them; missing provenance remains `null`.

The database stores `structured_documents`, `structured_document_sections`, `structured_document_paragraphs`, and `evidence` as related tables. A paper has one active normalized document: re-normalization transactionally replaces the previous document and all of its evidence, preventing stale mappings or orphan records. Phase 4 semantic claims can reference evidence IDs without coupling to parser objects.

Figures, tables, equations, and references are source-first parser artifacts. PyMuPDF caption/label extraction preserves page and region metadata, structured table rows are only emitted when delimiters make them reliable, equations remain raw expressions, and references retain raw text plus deterministic arXiv/DOI/URL matches. Each artifact receives an Evidence Registry ID and is persisted in `document_artifacts`; image bytes are not exposed as an arbitrary file endpoint. Phase 4 populates the semantic portions of `PaperIR` through the evidence-grounded extraction flow below; parser output itself remains source-preserving and non-interpretive.

## Evidence-grounded extraction

Phase 4 adds the following bounded flow:

```text
StructuredDocument
        ↓
SectionClassifier (deterministic headings first)
        ↓
EvidenceSelector (target section subsets)
        ↓
Focused Extractors + AIProvider
        ↓
Pydantic schema validation
        ↓
Evidence ID validation
        ↓
PaperIR + extraction states
        ↓
SQLAlchemy analysis cache
```

`AIProvider` is vendor-neutral; `OpenAICompatibleProvider` owns HTTP, authentication, model, timeout, and bounded schema-retry behavior. Runtime configuration comes from `AI_PROVIDER`, `AI_MODEL`, `AI_API_KEY`, `AI_BASE_URL`, `AI_REQUEST_TIMEOUT`, and `AI_MAX_RETRIES`. No credentials are returned to the frontend or written to logs.

The section classifier uses heading rules for obvious labels and only invokes AI for ambiguous headings. Evidence selection limits each extractor to relevant paragraph evidence rather than sending the complete document. Prompt files under `backend/app/prompts/` explicitly treat paper text as untrusted source material and forbid following instructions embedded in it.

Every semantic payload is validated against supplied evidence IDs after provider parsing. Missing or unknown IDs fail that component; they never become normal PaperIR claims. `AUTHOR_EXPLICIT` and `MODEL_INFERRED` origins are preserved in the models and frontend. Extractors run independently, so a failed component records `FAILED` while successful components remain persisted. Empty relevant evidence is recorded as `NO_EVIDENCE`.

Analysis cache keys hash document hash, extractor prompt/schema versions, provider, and model. One active analysis is stored per paper and replaced when the cache key changes. Without configured credentials, extraction safely persists failure/no-evidence states; no fake semantic content is generated.

## Visual reader

Phase 5 adds a compact reader boundary rather than sending all paragraph evidence to the browser:

```text
PaperIR + StructuredDocument metadata
        ↓
GET /api/papers/{paper_id}/reader
        ↓
typed ReaderResponse + VisualizationSpec[]
        ├── overview and semantic sections
        ├── deterministic method-flow spec
        ├── deterministic numeric-result chart/table specs
        └── source availability metadata
```

`ReaderResponse` contains paper metadata, section/paragraph counts, parsed reference summaries when available, persisted `PaperIR`, visualization specs, and a source endpoint. Evidence bodies remain lazy through `GET /api/papers/{paper_id}/evidence/{evidence_id}`. The frontend caches evidence records for the current session and opens all evidence IDs linked to a claim in one drawer.

The method graph transformation is frontend application code: `MethodIR` steps become deterministic top-to-bottom React Flow nodes and persisted relations become edges. A textual outline remains alongside the graph for keyboard and no-graph fallback use. Result visualization is deterministic: comparable numeric results may become a bar chart, a single numeric result a metric view, and mixed/non-numeric results a table/text view. No runtime AI call is used for rendering.

`GET /api/papers/{paper_id}/source` serves only a completed paper's persisted PDF after ownership and storage-root validation. The reader uses the browser's established PDF viewer in a split view and navigates to evidence pages with `#page=N`. Source-region coordinates remain visible as preserved provenance but are not highlighted until coordinate mapping is reliable across PDF rendering scales.

## Claim verification and faithfulness

Phase 6 keeps verification separate from the original extracted claims:

```text
PaperIR Claim
      ↓
Evidence Resolver
      ↓
Deterministic Validation
      ↓
FaithfulnessVerifier
      ↓
VerificationResult
      ↓
Versioned persistence/cache
      ↓
Visual Reader
```

`VerificationStatus` is categorical (`SUPPORTED`, `PARTIALLY_SUPPORTED`, `UNSUPPORTED`, `CONTRADICTORY`, or `UNVERIFIED`). Origin (`AUTHOR_EXPLICIT` versus `MODEL_INFERRED`) remains a separate dimension. The verifier receives one claim, its origin, structured numeric context when available, and only the linked evidence records; paper text is explicitly treated as untrusted data in `faithfulness_verifier.md`.

The verification service collects stable application-generated claim IDs from PaperIR, including the fixed `method_001` summary ID and existing extractor IDs for problem, gaps, contributions, steps, equations, experiments, results, limitations, and future work. Before any provider call it checks claim/evidence presence, paper ownership, current document identity, non-empty source text, and exact structured numeric value presence. Invalid or unavailable inputs become `UNVERIFIED` without being mislabeled `UNSUPPORTED`.

Results are stored separately in `claim_verifications`; the original PaperIR statement is never overwritten. Cache keys include document hash, claim hash, ordered evidence-content hash, provider/model, prompt version, and schema version. The verification API exposes `POST /api/papers/{paper_id}/verify` and `GET /api/papers/{paper_id}/verification`; the reader displays categorical badges, a count summary, and a manual verify/reverify action. Unsupported or contradictory claims are visually marked and excluded from the prominent overview cards and numeric charts.

## Evidence-grounded Paper Chat

Phase 7 reuses the Phase 3 Evidence Registry for one chat namespace per paper:

```text
question → history resolver → query normalizer → BM25 evidence retrieval
         → bounded context → structured AIProvider output
         → citation/document validation → persisted chat turn → reader UI
```

`BM25EvidenceRetriever` (`bm25-v1`) indexes only paragraph `Evidence.source_text` plus section titles and returns provider-neutral `RetrievedEvidence`. Scientific tokens such as `BERT`, `F1`, `ResNet-50`, and `GPT-4` are preserved. Section intent contributes a small ranking boost without hard filtering. `CHAT_RETRIEVAL_TOP_K` defaults to 8, `CHAT_MAX_CONTEXT_CHARS` defaults to 12,000, and an in-process cache is keyed by paper/query/limit/section hint. Scores rank passages; they are not calibrated probabilities. Empty or below-threshold retrieval becomes explicit insufficient evidence without an AI call.

`PaperChatService` may use recent turns to resolve pronouns, but history is labeled context and never evidence. Sessions persist their `document_id` and `document_hash`; historical sessions remain readable after re-ingestion, while new turns are frozen until a new session is created. The provider receives `paper_chat.md`, the question, bounded history, and delimited `[EVIDENCE ev_…]` passages. Structured claims are accepted only when every factual claim cites a supplied current-paper ID. Missing, fabricated, outside-context, wrong-document, or numerically unfaithful citations are rejected and persisted as a failure state. Missing credentials never trigger general-knowledge fallback.

The reader's optional Paper Chat panel renders plain text, explicit insufficient/failure states, and compact citation buttons. Citations reuse the existing evidence drawer and set the existing PDF viewer to the cited page; no second provenance or navigation system is introduced.

## Advanced research intelligence

Phase 8 keeps lexical retrieval as the safe baseline and adds an optional semantic lane:

```text
Evidence Registry → BM25 (default)
                  ↘ provider-neutral embeddings → SQLite cache → cosine ranking
BM25 + semantic ranks → reciprocal-rank fusion (hybrid-rrf-v1)
```

`EmbeddingProvider` is intentionally vendor-neutral. `RetrievalMethod` exposes `LEXICAL`, `SEMANTIC`, and `HYBRID`; the default is lexical. The deterministic `HashEmbeddingProvider` supports local evaluation; unavailable providers raise a safe error and Paper Chat falls back to BM25. Embeddings are keyed by paper, document, model/version, and SHA-256 evidence text, so document replacement invalidates stale vectors without cross-paper leakage. `RetrievalCase`/`evaluate_retriever` report deterministic Recall@K, MRR, and Hit@K values; no quality claim is made without a measured fixture.

Persistent `WorkspaceRecord`/`WorkspacePaperRecord` models support the `/workspaces` UI and allow the same paper in multiple workspaces. Comparison IR aligns only persisted PaperIR dimensions, retains paper/document/evidence identity, marks missing or mismatched datasets/metrics/results as partial or not comparable, and never emits an unsupported winner. Legacy per-document section/evidence IDs are namespaced on collision when multiple documents share one database.

The citation graph is bounded to extracted references and papers already in the local database. Exact arXiv IDs are preferred, with normalized reference-title matching as a deterministic fallback; matched papers create `CITES` edges and unmatched references remain reference nodes. It does not perform external literature discovery in Phase 8.

## Evidence-grounded research agent (Phase 9)

Phase 9 adds a persistent, bounded orchestration boundary. A `ResearchRun` stores the immutable question, budgets, status, and timestamps; append-only `ResearchRunEvent` records make every stage observable. `ResearchPlanner` first attempts the configured structured provider and falls back to deterministic query variants when credentials or schema output are unavailable.

```text
question → bounded ResearchPlan → official arXiv Atom discovery
         → normalized/deduplicated PaperCandidate metadata
         → deterministic relevance/diversity selection
         → existing IngestionService (concurrency ≤ 2)
         → existing PaperIR + Evidence Registry
         → cross-paper BM25/semantic/hybrid retrieval
         → citation-validating ResearchReportIR
```

Only official arXiv generated identifiers are sent to ingestion; discovery metadata is never treated as evidence. Candidate, query, plan, event, and report records are persisted. The agent stops after at most three iterations, when coverage is sufficient, or when refinement produces no new candidates. Cancellation is checked at each stage boundary. Failed providers and individual paper failures produce partial results instead of fabricated papers.

Cross-paper citations use the composite `(paper_id, document_id, evidence_id)` identity. Report validation rejects unknown papers, mismatched documents, missing registry evidence, and numeric values absent from the cited source text. Agreement, contradiction, and gap sections are explicitly `CROSS_PAPER_INFERRED` and remain `UNVERIFIED`; contradiction detection requires comparable metric/context and does not claim universal absence. Prompt/search injection is source data, never executable instructions, and no general-knowledge fallback is used.

## Evaluation and benchmarking (Phase 10)

Evaluation is a separate boundary and never writes back into production claims:

```text
versioned manifest + annotations + frozen predictions
                  ↓
          offline component runner
                  ↓
          pure metric implementations
                  ↓
       versioned JSON + Markdown report
```

`backend/evaluation/` contains Pydantic schemas, identifier-only corpus metadata, JSONL annotation import/export, parser/extraction/retrieval/verification/chat/research-agent/synthesis runners, a failure taxonomy, and report writers. The standard runner is deterministic and offline; live mode is explicit and recorded in reproducibility metadata. Missing annotations or predictions produce `not measured`, not fabricated quality values. BM25, semantic, and hybrid lanes use the same retrieval cases; the production default remains unchanged.

## Production hardening (Phase 11)

The API now has a typed, validated runtime boundary. `Settings.validate()` checks
environment, database/provider URLs, explicit CORS origins, production
migration policy, and positive resource limits. Request middleware generates or
propagates safe `X-Request-ID` values, records bounded process-local metrics,
and emits one-line structured request events. Security headers, credentialed
explicit CORS, JSON body limits, and stable error envelopes are applied before
routes. `/health/live`, `/health/ready`, and `/metrics` are separate operational
surfaces.

The arXiv client streams PDF bytes, caps content length, validates the PDF
signature/content type, bounds redirects to official hosts, and the parser
rejects papers over configured page/text limits. Storage endpoints resolve paths
under the configured paper root. AI provider failures have normalized codes and
bounded exponential jittered retries only for transient failures; missing
credentials preserve safe degraded behavior.

Startup recovery is explicit: unfinished paper ingestion becomes diagnosable
`FAILED`, while active research runs become recoverable `INTERRUPTED` records
with an append-only event. No expensive work is automatically rerun. SQLite
enables foreign keys, busy timeouts, WAL, and pre-ping; PostgreSQL remains the
production target. Production disables automatic schema creation and uses
`alembic upgrade head` from the migration scaffold. Critical document/evidence,
analysis, verification, workspace, and research writes remain transactionally
bounded and idempotent.

Browser hardening uses Playwright with deterministic API mocks for reader/source
PDF, evidence drawer, Paper Chat entry, workspaces, research entry, and
ingestion failure states. CI separates backend, evaluation smoke, frontend, and
browser gates. See `docs/production.md`, `docs/operations.md`, and
`docs/security.md` for deployment and incident guidance.
