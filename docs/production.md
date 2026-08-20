# PaperLens production guide

Phase 12 keeps production deployment deliberately small: FastAPI, Next.js,
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

`APP_ENV`/`DATABASE_URL`/`FRONTEND_ORIGIN` aliases are accepted for hosting
platforms that reserve the `PAPERLENS_*` namespace. Release diagnosis uses
`PAPERLENS_RELEASE_VERSION`, `PAPERLENS_BUILD_SHA`, and
`PAPERLENS_BUILD_TIMESTAMP`; `/health/version` exposes only those safe values.
The public `/api/capabilities` response tells the frontend whether AI,
semantic retrieval, and the Research Agent are enabled. With no live key, the
beta keeps ingestion, the reader, evidence, PDF viewing, and BM25 available
while AI controls are hidden or disabled.

## Database and startup

Install backend dependencies, set the database URL, and run the explicit
migration before starting the API:

```bash
alembic upgrade head
uvicorn app.main:app --app-dir backend --workers 2
```

For a reproducible local production-like stack (PostgreSQL, durable named
volumes, explicit migration service, health-gated startup), use:

```bash
docker compose up --build
python3 scripts/production-smoke.py
```

The compose stack is a local/staging harness, not a hosted production
provider. Put an HTTPS edge (managed TLS, reverse proxy, or platform ingress)
in front of the frontend and API in a real beta environment. The edge must
forward only from configured trusted infrastructure; do not accept arbitrary
`X-Forwarded-*` headers from the public internet.

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

The frontend image uses Next.js standalone output and contains only the
production server, static assets, and runtime dependencies. The backend image
runs as a non-root user; neither image contains `.env` files, runtime PDFs,
databases, Playwright output, or the unrelated `frontend/app/page 2.tsx` file.

Release flow is immutable: CI runs the quality gates, builds images tagged by
Git SHA, scans them, and publishes only when the repository's release policy
enables the registry credentials. Staging promotion is an explicit workflow
step; production is never an unsafe credentialless auto-deploy.

## Operations and retention

Source PDFs under `PAPERLENS_STORAGE_PATH` and the database are persistent
application data and must be backed up together. Temporary evaluation output,
Playwright artifacts, `.next`, and local runtime databases are ignored by Git.
Failed ingestion records remain diagnosable; cleanup is an explicit operator
action. Research runs interrupted by a restart are marked `INTERRUPTED` and are
never automatically rerun.

Safe maintenance commands are provided in `scripts/maintenance.py`:

```bash
python3 scripts/maintenance.py recover
python3 scripts/maintenance.py cleanup-temp       # dry run
python3 scripts/maintenance.py cleanup-temp --apply
```

The beta retention policy is documented in `docs/beta-support.md`: source PDFs,
normalized documents, analyses, chat sessions, research runs, and workspaces
are retained until an operator-approved cleanup policy exists. Back up the
database and source volume together. `scripts/backup-postgres.sh` and
`scripts/restore-postgres.sh` exercise a restore into a separate database.

## Known limitations

Metrics are process-local and should be scraped per worker or replaced with a
shared collector before horizontal scaling. PostgreSQL compatibility is kept
behind SQLAlchemy; the release checklist requires a real PostgreSQL run.
Playwright coverage uses deterministic API mocks and does not replace a
deployment-specific smoke test. A small beta limiter is process-local: the
edge must add a shared IP/session limit before horizontal scaling.
