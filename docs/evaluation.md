# PaperLens Evaluation & Benchmarking (Phase 15)

PaperLens evaluation is a separate, deterministic measurement system. It must
never turn a fixture score into a product claim. Every publishable number must
be traceable to four frozen inputs: a public-paper corpus, versioned human
annotations, frozen PaperLens predictions, and the exact offline evaluator.

## Audit: before and after

Before Phase 15, `backend/evaluation/` had useful metric functions, structured
result shapes, a report writer, a 35-paper identifier manifest, and synthetic
smoke expansion (60 retrieval, 50 verification, and 40 chat cases). It could
calculate fixture numbers, but did not bind them to document hashes, validate
evidence identity, persist predictions separately, or distinguish reviewed
benchmarks from infrastructure.

After Phase 15, evaluation has explicit schema/provenance fields, fail-closed
validators, SHA-256 helpers, a frozen smoke prediction envelope, DEV/FINAL
corpus declarations, separate quality dimensions, false-support and numeric-
fidelity metrics, retrieval failure categories, and machine-readable
provenance in every report. Phase 15B also records 35 exact arXiv PDF
snapshots, production-ingested document/evidence IDs, and a real BM25 run. The
real annotations remain draft, so no number is called publishable.

## Reproducible commands

Run from the repository root:

```bash
# Validate manifest and annotation ledger without running metrics.
python -m backend.evaluation.run smoke --validate-inputs

# Offline fixture report (no network, AI provider, or paid embedding call).
python -m backend.evaluation.run all --output-dir /tmp/paperlens-evaluation

# One dimension with an explicit split label in provenance.
python -m backend.evaluation.run retrieval --split DEV --output-dir /tmp/paperlens-evaluation

# Run the real BM25 lane against a persisted Phase 14 corpus database.
PYTHONPATH=backend python -m evaluation.real_runner \
  --database-url sqlite:////tmp/paperlens-phase15-real.db
```

The run directory contains `report.json` (source of truth), `report.md`,
`metadata.json`, `provenance.json`, one JSON file per component, and
`manifest-summary.json`. Loading
`backend/evaluation/datasets/predictions/frozen_smoke.json` verifies its
prediction hash before use.

## Dataset and annotation contract

`backend/evaluation/datasets/manifest.json` freezes 35 real public arXiv
identifiers across six domains and explicit DEV and FINAL paper lists. The
Phase 15B corpus at `datasets/corpus/` contains the exact versioned PDFs,
per-file SHA-256 digests, parser/document hashes, durable PaperLens IDs, and
34,117 Evidence Registry records. Validate it with
`validate_real_corpus_manifest` before any run.
`backend/evaluation/corpus/README.md` documents selection and immutable-version
rules.

`annotations.jsonl` and the templates under `datasets/annotations/` and
`datasets/queries/` are evaluator-only. Reviewed retrieval cases target 60–100
queries; verification 50–80 claims; grounded chat 40–60 questions; bounded
research-agent tasks 10–20. Reviewed records require rationale and stable
evidence identity. Provider-generated labels are never gold truth.

`datasets/failures.jsonl` preserves representative synthetic retrieval,
verification, chat, and agent failures. It is included in reports as failure
evidence, never silently discarded after a score is seen.

`datasets/real_annotations/` contains 60 retrieval, 50 verification, 40 chat,
and 10 bounded-agent cases, all tied to real evidence IDs. They are explicitly
`DRAFT` programmatic seeds with zero human reviewers; the rubric and required
adjudication fields are in `human_review_rubric.json`. The validator rejects
unknown papers/evidence IDs, duplicate case IDs, malformed labels, missing
reviewed rationales, and a `VALIDATED` manifest without immutable document
hashes.

Phase 15C adds `backend.evaluation.review_cli`: a minimal local, one-case-at-a-
time workflow that displays the case plus Evidence Registry text and records
reviewer ID, UTC review time, notes, evidence edits, labels, and an explicit
`REVIEWED` state, including nearby evidence from the same section. Use
`--show-only` to inspect without editing and `--refresh-manifest` after a
review batch to refresh counts and exact ledger hashes. `--freeze` refuses to
run until every case has reviewer metadata and notes, then marks the manifest
immutable; later edits require a new benchmark version. `review_audit.json` is
a read-only ledger audit. A reviewed-only run is available with
`evaluation.real_runner --require-reviewed`; it refuses to score pending cases
rather than treating file presence as review. Retrieval inference inputs are
constructed without gold evidence, labels, or reviewer fields.

## Separate dimensions and metrics

- Retrieval reports BM25, Semantic, and Hybrid lanes separately with
  Recall@1/3/5, MRR, binary or graded nDCG, and failure categories (lexical or
  embedding mismatch, chunk/section boundary, table/equation evidence,
  multiple passages, ambiguity, and RRF failure).
- Verification reports accuracy, macro F1, per-label F1, false-support rate,
  false-rejection rate, and UNVERIFIED rate. This is an **evidence-consistency
  assessment**, not a scientific truth oracle; `UNVERIFIED` remains the safe
  default.
- Paper Chat reports citation precision, required-evidence recall, citation
  completeness, unsupported-claim rate, answerable/unanswerable behavior, and
  numeric fidelity (including a strict numeric multiset check). Human
  answer-quality review is separate from automatic metrics.
- Research-agent reports bounded completion, evidence-grounded output,
  unsupported-claim, source-duplicate, ingestion, budget, iteration, and
  provider-call metrics. Fewer calls are not success if grounding collapses.

Human review uses a 0–2 correctness/faithfulness/usefulness rubric plus
citation correctness, completeness, speculation, and notes. A single reviewer
is reported as single-reviewer annotation, not inter-annotator agreement.

## Frozen predictions, providers, and cost

Predictions are stored separately from annotations in an envelope containing
the evaluation schema version, dataset/annotation hashes, PaperLens commit,
provider/model settings, and prediction hash. Offline runs use provider
`none`; live runs require an explicit operator flag and must freeze provider,
model, temperature, prompt version, max tokens, and generation settings. The
runner records provider calls, tokens, cache use, and cost only when supplied;
it never invents billing data. Latency is operational context, not the primary
quality objective.

## DEV/FINAL discipline and baselines

The manifest names DEV and FINAL paper splits. Tune retrieval weights, prompts,
or verification policy only on DEV. Freeze implementation, then run FINAL once.
Meaningful retrieval baselines are BM25, embeddings, and Hybrid/RRF; for
grounding, compare the validated PaperLens path with a no-post-validation path
only when both are reproducible without changing architecture. No competitor-
system theater or cherry-picking difficult examples is allowed.

## Current evidence status

The real Phase 15B BM25 run is in
`datasets/predictions/real_retrieval_result.json` and its frozen prediction
envelope is `predictions/real_bm25.json`. It measures Recall@1/3/5, MRR, nDCG,
and Hit@5 over 60 real-corpus retrieval cases (48 DEV, 12 FINAL). Semantic and
Hybrid are `NOT_RUN` because no real embedding provider was configured; the
hash-v1 test provider is intentionally excluded. Verification, chat, and
agent predictions are not claimed until a production/provider run and human
review exist. Therefore the overall phase remains `PRELIMINARY`, not
`VALIDATED`; difficult cases may not be removed without a benchmark-history
reason.

Phase 13A authentication/tenant isolation, Phase 13B durable execution and
cancellation fencing, Phase 14 PDF isolation/budgets, and existing core
ingestion/retrieval/chat/verification tests remain independent regression gates.
Phase 15 does not weaken those runtime guarantees.
