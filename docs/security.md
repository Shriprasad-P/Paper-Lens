# PaperLens security model

## Network and API controls

- arXiv ingestion accepts identifiers and arXiv URLs only. Metadata and PDF
  downloads use generated official endpoints, allow at most three redirects,
  and reject a final host outside `arxiv.org`/`export.arxiv.org`.
- Persisted source and figure endpoints verify paper/document ownership and
  resolve paths beneath `PAPERLENS_STORAGE_PATH` before serving bytes.
- CORS uses an explicit origin list with credentials; wildcard origins are
  rejected. Responses receive conservative content, framing, referrer, and
  permissions headers.
- JSON requests have a bounded content-length limit. Pydantic bounds questions,
  workspaces, research budgets, retrieval top-K, page counts, and extracted
  text. PDF downloads stream and stop at the configured byte limit.
- Public-beta expensive operations have server-side, per-client-IP rate limits
  for ingestion, AI extraction/verification, chat, and research-run creation.
  The limiter is deliberately process-local and must be paired with an edge
  limit for multi-process deployments.

## Untrusted research content

Paper text, metadata, discovery results, chat history, and provider output are
data, never executable instructions. Prompt templates delimit source material;
claim, citation, numeric, document, and evidence identities are validated before
persistence. Unsupported or unavailable content is represented as
`UNVERIFIED`/insufficient evidence rather than fabricated.

## Secrets and errors

Provider keys are sent only in outbound provider authorization headers and are
never returned to the frontend or logs. API errors expose stable codes and a
request ID, not stack traces, SQL statements, filesystem paths, raw provider
responses, or uploaded PDF contents.

## Dependency and browser posture

Next.js was deliberately migrated from 15.5.x to 16.3.1 with matching
`eslint-config-next`; `npm audit --omit=dev` reports no production findings in
the validated lockfile. Playwright tests use deterministic local mocks and do
not require live credentials. Keep Chromium test artifacts out of commits.

## Remaining risks

Metrics are in-process, trusted-proxy handling is documented but not enabled by
default, and object storage remains a deployment adapter beyond the durable
local-volume beta path. A live PostgreSQL/security scan must be performed in
the target deployment environment. These are explicit release risks, not
reasons to weaken the API's default limits or secret-redaction behavior.
