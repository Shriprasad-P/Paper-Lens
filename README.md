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

Phase 5 reader endpoints are:

```text
GET /api/papers/{paper_id}/reader
GET /api/papers/{paper_id}/source
```

Open the visual reader at `http://localhost:3000/papers/{paper_id}`. It loads compact persisted PaperIR metadata, fetches evidence passages only when requested, and opens the persisted PDF through the ownership-checked source endpoint.

Phase 6 verification endpoints are:

```text
POST /api/papers/{paper_id}/verify
GET  /api/papers/{paper_id}/verification
```

Verification is claim-level and persisted separately from PaperIR. It reports categorical support (`SUPPORTED`, `PARTIALLY_SUPPORTED`, `UNSUPPORTED`, `CONTRADICTORY`, `UNVERIFIED`) and never requires runtime AI to render the reader. Without verifier credentials, claims remain explicitly `UNVERIFIED` rather than receiving fabricated support.

Phase 7 Paper Chat endpoints are:

```text
POST /api/papers/{paper_id}/chat/sessions
GET  /api/papers/{paper_id}/chat/sessions/{session_id}
POST /api/papers/{paper_id}/chat/sessions/{session_id}/messages
```

Chat retrieves only bounded paragraph evidence from the current paper using deterministic BM25 ranking. Every assistant turn is persisted with document-bound citations; insufficient retrieval and missing AI credentials remain explicit safe states. `CHAT_RETRIEVAL_TOP_K`, `CHAT_MAX_CONTEXT_CHARS`, `CHAT_MIN_RELEVANCE`, and `CHAT_MAX_QUESTION_CHARS` tune the boundary.

Phase 8 research-intelligence endpoints are:

```text
POST /api/workspaces
GET  /api/workspaces
GET  /api/workspaces/{workspace_id}
POST /api/workspaces/{workspace_id}/papers/{paper_id}
POST /api/workspaces/{workspace_id}/compare
GET  /api/papers/{paper_id}/citation-graph
```

Phase 8 extracts source-first figure, table, equation, and reference artifacts into the Evidence Registry. `RETRIEVAL_MODE` supports `LEXICAL`, `SEMANTIC`, and `HYBRID`; BM25 remains the default, while optional provider-neutral semantic embeddings use a local SQLite cache and reciprocal-rank fusion when `HYBRID_RETRIEVAL_ENABLED=true` or hybrid mode is selected. The workspace UI provides persistent paper sets, evidence-preserving comparison IR, and bounded citation-graph matching over the local corpus. `EMBEDDING_PROVIDER=hash` is available for deterministic local evaluation; the default `none` provider never makes a network call.

Relevant environment variables are documented in `.env.example`: database URL, arXiv timeout, local PDF storage path, PDF size limit, and frontend origin.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The reader shell is available at `http://localhost:3000`.
The workspace shell is available at `http://localhost:3000/workspaces`.

### Phase 9 Research Agent

The research shell is available at `http://localhost:3000/research`. It creates a persistent, bounded run and reports observable planning, official arXiv discovery, candidate normalization/ranking, ingestion, extraction, synthesis, and verification events.

```text
POST /api/research/runs
GET  /api/research/runs/{run_id}
POST /api/research/runs/{run_id}/execute
POST /api/research/runs/{run_id}/cancel
GET  /api/research/runs/{run_id}/report
```

Without credentials, planning and ranking remain deterministic, arXiv metadata is discovery-only, reports cite only persisted Evidence Registry tuples, and claims remain `UNVERIFIED`. Defaults are bounded by `RESEARCH_MAX_SEARCH_QUERIES=6`, `RESEARCH_MAX_CANDIDATES=30`, `RESEARCH_MAX_INGESTED_PAPERS=8`, `RESEARCH_MAX_ITERATIONS=3`, and ingestion concurrency `2`.

### Phase 10 Evaluation

Evaluation is offline-first and separate from production services. The versioned corpus manifest, annotation schemas, pure metrics, fixture runners, and report writer live under `backend/evaluation/`.

```bash
python -m backend.evaluation.run smoke --output-dir /tmp/paperlens-evaluation
python -m backend.evaluation.run all --output-dir /tmp/paperlens-evaluation
python -m backend.evaluation.run all --live --output-dir /tmp/paperlens-evaluation
```

The first two commands make no network or paid-provider calls. Reports record reproducibility metadata and remain `PRELIMINARY` until reviewed annotations and frozen production predictions are available. See [docs/evaluation.md](docs/evaluation.md) for corpus, metrics, failure taxonomy, and live/offline policy.

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
