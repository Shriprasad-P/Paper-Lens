# PaperLens Architecture

Phase 3 extends the Phase 2 vertical slice with a source-preserving document layer while keeping semantic stages separate:

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
PaperIR and verification (later phase)
        ↓
VisualizationSpec and deterministic reader (later phase)
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

Figures, tables, equations, and references have typed models but remain empty in the current parser because reliable extraction is not yet implemented. `PaperIR` is an empty typed semantic shell with explicit extraction states; no AI-generated content is created in Phase 3.
