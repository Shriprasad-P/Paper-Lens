# Phase 15 public-paper corpus

`../datasets/manifest.json` is the frozen **candidate** manifest for the
first PaperLens quality run. It contains 35 stable arXiv identifiers spanning
NLP, computer vision, machine learning, systems, security, HCI, and
information retrieval. Structural tags deliberately cover short and long
papers, two-column layouts, equations, tables, figures, numeric results,
references, and explicit limitations.

The candidate manifest remains `identifier_only_public_candidates`, but the
Phase 15B real snapshot corpus is now persisted at
`../datasets/corpus/`. It contains 35 exact versioned PDFs, per-file source
SHA-256 values, parser/document hashes, durable PaperLens source/document IDs,
and 34,117 Evidence Registry rows. `manifest.json` is the canonical identity
record; `documents.json`, `evidence.jsonl`, and `ingestion.json` are the
resolved production exports. `validate_real_corpus_manifest` checks PDF,
document, evidence, split, and hash drift fail-closed.

The real corpus is still preliminary: the 60 retrieval, 50 verification, 40
chat, and 10 agent ledgers are DRAFT programmatic seeds with zero human
reviewers. A changed arXiv version is a new corpus record; it must never
silently overwrite an annotated version.

Selection policy: include a representative spread of paper structure and
research content, not only papers that are easy for lexical retrieval. The
DEV and FINAL paper lists are explicit in the manifest. Tuning is permitted
only against DEV; FINAL is inspected once after implementation is frozen.

No private documents, provider keys, raw hidden prompts, or provider-generated
labels belong in this directory.
