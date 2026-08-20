# PaperLens Architecture

Phase 2 now implements the first vertical slice while keeping later semantic stages separate:

```text
arXiv input
        ↓
identifier normalization
        ↓
arXiv metadata client + PDF downloader
        ↓
PyMuPDF section parser
        ↓
normalized paper + SQLAlchemy persistence
        ↓
FastAPI + Next.js reader shell
        ↓
Structured document and evidence (next phase)
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
