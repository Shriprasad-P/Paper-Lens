# PaperLens operations guide

## Health and tracing

- `/health/live` only verifies that the process can answer.
- `/health/ready` verifies the database and paper-storage directory.
- `/health/version` returns the release version, Git SHA, and build timestamp.
- `/api/capabilities` returns safe feature flags and supported input types.
- `/metrics` exposes bounded Prometheus text without paper content.
- Every response includes `X-Request-ID`; callers may provide a safe ID using
  the same header.

Logs are one-line JSON events with method, path, status, duration, and request
ID. They intentionally omit request bodies, PDF contents, authorization
headers, and provider credentials.

## PDF parsing boundary

Uploaded and discovered PDFs are byte-checked while downloading, then parsed by
a fresh, short-lived child process. The API process never traverses a PDF with
PyMuPDF. `PDF_MAX_BYTES` is checked before the child starts; the child checks
`PDF_MAX_PAGES` before page traversal and enforces incremental text and image
budgets. `PDF_PARSE_TIMEOUT_SECONDS` is enforced by the parent, which
terminates and, when necessary, force-kills the child. `PDF_PARSE_CONCURRENCY`
bounds active parser children. Failed, timed-out, malformed, and over-budget
parses leave no completed document; a temporary failed source is removed.

The parser applies best-effort Unix CPU/address-space limits when configured.
macOS may reject an address-space limit for an already mapped interpreter, so
byte/page/text/image budgets, process isolation, and the wall-clock timeout
remain the portable controls. Isolation reduces the blast radius of malformed
native input; it is not a guarantee against every native parser exploit.

Structured events and `/metrics` expose only safe parse counts, durations,
limit rejections, and active-child gauges. They never include PDF bytes or
extracted paper text.

The minimum beta alert set is: readiness failures, sustained 5xx responses,
database health failures, storage write/read failures, and provider failure
spikes. Route platform logs and `/metrics` to the hosting provider's collector;
do not pretend process-local counters are globally aggregated.

Expensive public operations have server-side process-local limits controlled by
`PAPERLENS_RATE_LIMIT_*`. In production the current defaults are four ingestion
requests, six AI requests, twenty chat turns, and two research-run creations per
client IP per minute. An HTTPS edge should enforce the shared limit when more
than one backend process is used.

## Common failures

- `REQUEST_TOO_LARGE`: lower the payload or review the configured JSON limit.
- `PDF_TOO_LARGE`, `PDF_TOO_MANY_PAGES`, `PDF_TEXT_LIMIT_EXCEEDED`,
  `PDF_IMAGE_LIMIT_EXCEEDED`: the paper exceeded a configured bounded-ingestion
  budget; review the corresponding `PDF_*` setting.
- `PDF_PARSE_TIMEOUT`, `PDF_MEMORY_LIMIT`, `PDF_MALFORMED`, or
  `PDF_PARSE_FAILED`: the isolated parser rejected or could not safely process
  the document. Verify the source and retry; native parser details are not
  returned to clients.
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

Research execution is recovered by the database-polled worker. Start one or
more bounded workers with `python -m backend.app.research.worker`; each worker
claims queued work with a lease, heartbeats while active, and is automatically
replaced after expiry. Repeated execute requests are safe because enqueue and
claim are idempotent. Inspect the run event timeline for `CLAIMED`,
`LEASE_EXPIRED`, `RETRY_SCHEDULED`, `CANCELLATION_REQUESTED`, and terminal
events. Never manually mark a run complete or reuse a claim token.

Restarts convert unfinished ingestion to diagnosable `FAILED` records. Legacy
stage-only research runs become recoverable `INTERRUPTED` records; durable
attempts are re-queued only after their lease expires. Completed documents,
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

## Release order and rollback

1. Build and scan immutable images tagged with the release Git SHA.
2. Back up PostgreSQL and verify the source storage volume is durable.
3. Run `alembic upgrade head` as a one-shot migration job.
4. Deploy the backend image and wait for `/health/ready`.
5. Deploy the frontend built with the matching `NEXT_PUBLIC_API_BASE_URL`.
6. Run `scripts/production-smoke.py`, then the bounded user-path smoke.

Rollback the frontend and backend to the previous immutable image tag. Do not
automatically downgrade migrations: if a schema revision is not backward
compatible, stop traffic and restore the database backup into a controlled
environment before deciding on remediation.
