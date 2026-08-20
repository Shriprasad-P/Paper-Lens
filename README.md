# PaperLens

Turn research papers into visual, verifiable explanations.

PaperLens is being built as a local-first research-paper ingestion and visualization platform. The application keeps paper parsing, evidence provenance, semantic extraction, verification, and deterministic rendering as separate stages.

## Repository layout

- `backend/` — FastAPI service and portable persistence boundary
- `frontend/` — Next.js reader shell
- `docs/` — architecture and incremental project state

## Local development

Prerequisites: Python 3.11+, Node.js 20+, and npm. The backend uses SQLite by default for local development; PostgreSQL remains the production target behind the SQLAlchemy boundary.

### Backend

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cp .env.example .env
.venv/bin/uvicorn app.main:app --app-dir backend --reload
```

The health endpoint is available at `http://localhost:8000/health`.

The API accepts a supported arXiv URL or identifier:

```bash
curl -X POST http://localhost:8000/api/papers/ingest \
  -H 'Content-Type: application/json' \
  -d '{"source":"https://arxiv.org/abs/1706.03762"}'
```

After ingestion, the normalized source document and paragraph evidence are available through:

```text
GET /api/papers/{paper_id}/document
GET /api/papers/{paper_id}/evidence/{evidence_id}
```

The document layer preserves source text, section/paragraph ordering, page numbers, and parser-provided coordinates. Phase 4 adds optional evidence-grounded research interpretation through the analysis endpoints below.

Phase 4 analysis endpoints are:

```text
POST /api/papers/{paper_id}/extract
GET  /api/papers/{paper_id}/analysis
```

Extraction is provider-neutral and evidence-grounded. Configure an OpenAI-compatible provider with the `AI_*` variables in `.env.example`. Without credentials, the API records safe `FAILED`/`NO_EVIDENCE` component states rather than fabricating analysis.

Relevant environment variables are documented in `.env.example`: database URL, arXiv timeout, local PDF storage path, PDF size limit, and frontend origin.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The reader shell is available at `http://localhost:3000`.

## Validation

```bash
.venv/bin/python -m unittest discover -s backend/tests
.venv/bin/python -m compileall -q backend/app backend/tests
```

When frontend dependencies are installed, also run:

```bash
cd frontend
npm run typecheck
npm run lint
npm run build
```
