# PaperLens production guide

Phase 11 keeps production deployment deliberately small: FastAPI, Next.js,
and PostgreSQL are the supported production surfaces. SQLite remains the
development default. No Redis or external queue is required by the current
execution model.

## Configuration

Copy `.env.example` and set at least:

- `PAPERLENS_ENVIRONMENT=production`
- `PAPERLENS_DATABASE_URL` to PostgreSQL
- `PAPERLENS_STORAGE_PATH` to a durable, writable volume
- `PAPERLENS_FRONTEND_ORIGINS` to explicit HTTPS browser origins
- `PAPERLENS_AUTO_CREATE_SCHEMA=false`
- provider variables only when new extraction/chat/research generation is
  desired; reader, ingestion, lexical retrieval, and existing persisted work
  remain available without credentials

Secrets are environment-only. The API validates URLs, CORS origins, limits,
and production migration settings at startup.

## Database and startup

Install backend dependencies, set the database URL, and run the explicit
migration before starting the API:

```bash
alembic upgrade head
uvicorn app.main:app --app-dir backend --workers 2
```

The application does not create tables in production. Readiness does not run
migrations; it checks database connectivity and the configured storage
directory. Use `GET /health/live` for process liveness and `GET /health/ready`
for traffic readiness.

## Frontend

```bash
cd frontend
npm ci
npm run build
npm run start
```

Set `NEXT_PUBLIC_API_BASE_URL` to the API origin at build time. It is not
hard-coded to localhost in deployment configuration.

## Operations and retention

Source PDFs under `PAPERLENS_STORAGE_PATH` and the database are persistent
application data and must be backed up together. Temporary evaluation output,
Playwright artifacts, `.next`, and local runtime databases are ignored by Git.
Failed ingestion records remain diagnosable; cleanup is an explicit operator
action. Research runs interrupted by a restart are marked `INTERRUPTED` and are
never automatically rerun.

## Known limitations

Metrics are process-local and should be scraped per worker or replaced with a
shared collector before horizontal scaling. PostgreSQL compatibility is kept
behind SQLAlchemy but a live PostgreSQL integration run is environment
dependent. Playwright coverage uses deterministic API mocks and does not
replace a deployment-specific smoke test.
