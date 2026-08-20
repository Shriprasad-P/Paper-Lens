# PaperLens migrations

Production starts with `PAPERLENS_AUTO_CREATE_SCHEMA=false` and expects the
database to be upgraded explicitly:

```bash
alembic upgrade head
```

Set `PAPERLENS_DATABASE_URL` before running Alembic. Local development keeps
automatic table creation enabled by default for backwards compatibility. The
initial migration is intentionally deterministic and uses the canonical
SQLAlchemy metadata; future schema changes must add a new revision rather than
mutating startup behavior.
