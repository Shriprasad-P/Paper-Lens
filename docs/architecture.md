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

Figures, tables, equations, and references have typed models but remain empty in the current parser because reliable source extraction is not yet implemented. Phase 4 now populates the semantic portions of `PaperIR` through the evidence-grounded extraction flow below; parser output itself remains source-preserving and non-interpretive.

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
