# PaperLens security model

## Network and API controls

- Shared/staging/production mode requires a registered account and a durable,
  revocable session. Passwords are stored only as Argon2id hashes when the
  production dependency is available (the local stdlib fallback is salted
  memory-hard scrypt); raw passwords and session tokens are never persisted or
  logged. Sessions use an HttpOnly SameSite cookie (Secure in production), and
  bearer tokens are accepted only as an equivalent opaque session transport.
- User-owned root records (papers, workspaces, chat sessions, and research
  runs) carry an owner ID. Documents, evidence, artifacts, analyses,
  verifications, messages, embeddings, and research child records inherit that
  ownership. Every list/get/mutation/execute query applies the owner predicate
  in the database layer; foreign IDs intentionally return 404.
- Existing local data is deterministically assigned to
  `user_legacy_local` by migration `0002_phase13a_auth_ownership`. Development
  mode uses that explicit local principal; the desktop token maps only to a
  separate trusted desktop-local principal and is not accepted as shared-mode
  authentication.
- Cookie state-changing requests are origin-checked against the explicit CORS
  allow-list. CORS never combines credentials with wildcard origins.

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
- Public-beta expensive operations have server-side, per-principal (or hashed
  session, then client-IP) rate limits for ingestion, AI extraction/verification,
  chat, and research-run creation. The limiter is deliberately process-local and
  must be paired with an edge limit for multi-process deployments.

## Untrusted PDF trust boundary

PDF bytes are untrusted input. arXiv downloads are streamed with a maximum
byte count, bounded redirects, and an allow-listed final host. Before native
parsing, PaperLens checks the actual stored size and `%PDF-` signature. A
short-lived parser subprocess receives only an internal file path and parser
budgets; it receives no session, cookie, provider, or database secrets.

The child performs one authoritative page traversal. It checks page count before
text extraction and stops during traversal when total/per-page text or image
budgets are exceeded. The parent enforces a wall-clock timeout, terminates the
child, force-kills a stuck child where supported, and discards failed output.
The parser concurrency semaphore prevents unbounded process creation. Parsed
output is normalized and persisted only after the complete result and evidence
are ready; a `PARSED` staging row is not visible as a completed paper.

The same isolated parser service is used by manual arXiv ingestion and the
Phase 13B research worker's ingestion path. Existing owner checks and storage
root containment remain authoritative for source/figure serving. Unix CPU and
address-space limits are best effort and platform dependent; process
isolation plus byte/page/text/image budgets and timeout reduce, but do not
eliminate, the blast radius of malformed native PDFs.

## Untrusted research content

Research workers use a database claim token stored only as a SHA-256 hash. The
token is never returned to clients or written to logs. Lease expiry,
cancellation, owner mismatch, or an active-attempt change fences a worker;
guarded writes reject the stale claim. Workers derive the run owner from the
durable row, and provider responses that arrive after a lost claim are not
authoritative.

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
