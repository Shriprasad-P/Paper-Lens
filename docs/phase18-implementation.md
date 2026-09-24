# Phase 18 implementation notes

PaperLens now has the product boundaries required for the Phase 18
reconstruction. The browser enters through account authentication, then
requires a tested owner-bound provider configuration before showing the paper
library. The library accepts arXiv, DOI, PMID/PMCID, scholarly URLs, APA/IEEE
citation text, BibTeX, RIS, and first-class PDF uploads.

## Provider safety

Provider configurations are stored in `ai_provider_configs` with an owner
foreign key. API keys are encrypted with Fernet using
`PAPERLENS_PROVIDER_ENCRYPTION_KEY`; read APIs expose only masked metadata.
Ollama and MLX are loopback-only local providers. Ollama remains key-free and
uses its own Metal/CPU runtime selection; MLX uses an OpenAI-compatible local
server (default `127.0.0.1:8080`). Hosted deployments must use a
server-reachable endpoint rather than pretending to reach a user's localhost.

## Universal resolver

`backend/app/ingestion/resolver.py` classifies inputs deterministically and
normalizes them to `ResolvedPaper`. arXiv uses the existing Atom client;
DOIs use Crossref; PMID/PMCID use NCBI; citation text is parsed conservatively
and checked against Crossref bibliographic candidates. A source without a
lawfully retrievable PDF is never scraped around access controls: the API
returns the upload fallback message.

All successful PDF paths still pass through the Phase 14 isolated parser,
`StructuredDocument`, and `EvidenceRegistry`. Resolver metadata is persisted
in the canonical paper row without replacing the original document.

## Archify integration

The MIT-licensed Archify `v2.16.0` runtime is bundled under
`vendor/archify` at commit
`c826e6c3a7abad19c0f3cd1ca57207d54b1ad8de`. PaperLens builds a validated
`PaperVisualGraph`, converts it to Archify's typed schema, runs the pinned
`archify validate` command, and renders a self-contained HTML artifact through
the pinned `archify render` command. The reader loads that artifact inline;
the PaperLens provenance envelope keeps document/evidence IDs beside (not
inside) Archify's strict schema, so no fake repository source ranges are
created. Rendering is fail-closed and the text/evidence block remains visible
when validation fails.

## Phase status

Phase 18 is intentionally **NOT CLOSED** yet. The owner-selected provider is
now resolved dynamically for each AI request and the setup test performs
bounded generation and embedding probes. The remaining closure proof is a live
browser run against a real local Ollama/MLX completion, inline Archify output,
node/edge evidence navigation, and reload/logout protection. Phase 15 remains
audit-only with no human-review or FINAL quality claim.
