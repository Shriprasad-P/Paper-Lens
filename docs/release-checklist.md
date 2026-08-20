# PaperLens v0.1.0-beta release checklist

Use this checklist for every staging or public-beta promotion. Record the Git
SHA, image tags/digests, migration revision, and deployment timestamp in the
release record.

## Quality and build

- [ ] Backend unit/regression suite passes.
- [ ] `compileall` and evaluation smoke pass.
- [ ] Frontend typecheck, lint, production build, and Playwright pass.
- [ ] `npm audit --omit=dev` is acceptable.
- [ ] Backend dependency and secret scans are recorded.
- [ ] Container scans are recorded when images are available.

## Database, storage, and release order

- [ ] PostgreSQL version and connectivity are recorded.
- [ ] Empty database migration and upgrade-from-previous-state migration pass.
- [ ] Critical persistence flows pass against PostgreSQL.
- [ ] Source-paper volume is durable, writable, and backed up.
- [ ] Backup restore has been verified against a separate database.
- [ ] Migration runs before backend, backend readiness before frontend.

## Deployment and smoke

- [ ] Immutable backend/frontend images are tagged by Git SHA.
- [ ] HTTPS edge and explicit CORS origins are configured.
- [ ] `GET /health/live`, `GET /health/ready`, and `/health/version` pass.
- [ ] External health checks and minimal alerts are configured.
- [ ] Controlled arXiv `1706.03762` smoke covers ingestion, reader, evidence,
  PDF, and available analysis/chat/research behavior.
- [ ] Beta error UX and request-ID support are verified.
- [ ] Bounded load probe records concurrency, p50, p95, and error rate.

## Rollback and notes

- [ ] Previous frontend/backend image tags are available.
- [ ] Rollback to the previous image has been tested or simulated.
- [ ] Migration downgrade policy is documented; no unsafe automatic downgrade.
- [ ] Release notes and known limitations are published.
- [ ] Benchmark status remains explicitly `PRELIMINARY`.
