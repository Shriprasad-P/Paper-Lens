# PaperLens release security record

Release: `0.1.0-beta`
Validation date: 2026-08-20 (local release candidate)

## Scans

- npm production audit: `npm audit --omit=dev` — **0 vulnerabilities**.
- Backend dependency scan: `.venv/bin/pip-audit -r backend/requirements.txt` —
  **No known vulnerabilities found**.
- Container scan: Trivy 0.57.1, HIGH/CRITICAL, `--ignore-unfixed` on the
  rebuilt backend and frontend images — **0 findings in each image**.
- Secret scan: tracked `.env` check plus credential-pattern scan — **no
  committed secrets detected**. `.env.example` is the only tracked env file.

## Controls

The release uses explicit CORS, conservative security headers, bounded JSON/PDF
resources, arXiv-host SSRF checks, request IDs, structured logs, server-side
beta limits, non-root containers, and environment-only credentials. Source PDFs
are backend-authorized and are never globally public by default.

## Accepted beta risks

Metrics and rate limits are process-local, local-volume storage requires a
durable deployment volume, live provider behavior is optional, and the
evaluation benchmark remains `PRELIMINARY`. Add an edge rate limit, centralized
metrics, and an object-storage adapter before horizontal scaling.
