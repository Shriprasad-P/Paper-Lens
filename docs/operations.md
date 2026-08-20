# PaperLens operations guide

## Health and tracing

- `/health/live` only verifies that the process can answer.
- `/health/ready` verifies the database and paper-storage directory.
- `/metrics` exposes bounded Prometheus text without paper content.
- Every response includes `X-Request-ID`; callers may provide a safe ID using
  the same header.

Logs are one-line JSON events with method, path, status, duration, and request
ID. They intentionally omit request bodies, PDF contents, authorization
headers, and provider credentials.

## Common failures

- `REQUEST_TOO_LARGE`: lower the payload or review the configured JSON limit.
- `PAPER_DOWNLOAD_FAILED`/`PDF_INVALID`: verify arXiv availability and the
  persisted storage volume; the record remains `FAILED` and can be retried
  explicitly.
- `PROVIDER_UNAVAILABLE` or `CHAT_UNAVAILABLE`: confirm provider URL, key, and
  quota. Existing reader data and lexical retrieval remain usable.
- `INTERRUPTED` research run: inspect its append-only events, then call the
  execute endpoint explicitly if a rerun is desired.
- readiness `503`: check database connectivity, run `alembic upgrade head`,
  and verify storage permissions.

## Recovery and cleanup

Restarts convert unfinished ingestion to diagnosable `FAILED` records and
active research runs to recoverable `INTERRUPTED` records. Completed documents,
evidence, analyses, verification results, workspaces, and reports are not
deleted. Do not remove source directories without checking the corresponding
database record. Any orphan cleanup should be a reviewed maintenance command.

## Migration troubleshooting

```bash
PAPERLENS_DATABASE_URL=postgresql+psycopg://... alembic current
PAPERLENS_DATABASE_URL=postgresql+psycopg://... alembic upgrade head
```

Back up PostgreSQL before upgrades. The initial migration is additive; future
schema changes must use a new revision. Production startup intentionally fails
when the schema is absent instead of mutating it silently.
