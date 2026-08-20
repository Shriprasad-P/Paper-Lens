# PaperLens Evaluation & Benchmarking (Phase 10)

PaperLens evaluation is deliberately separate from production parsing, extraction, retrieval, chat, verification, and research-agent services. The `backend/evaluation/` package consumes versioned benchmark cases and frozen predictions, computes deterministic metrics, and writes machine-readable JSON plus a concise Markdown report.

## Offline commands

Run from the repository root:

```bash
# Fast deterministic fixture run (no network, AI, or paid embeddings)
python -m backend.evaluation.run smoke --output-dir /tmp/paperlens-evaluation

# One component
python -m backend.evaluation.run retrieval --output-dir /tmp/paperlens-evaluation

# Full offline report
python -m backend.evaluation.run all --output-dir /tmp/paperlens-evaluation

# Explicitly marked live mode (still requires an operator-provided adapter)
python -m backend.evaluation.run all --live --output-dir /tmp/paperlens-evaluation
```

Ordinary commands never acquire papers or call external providers. `--live` is explicit and records the mode in `metadata.json`; this repository does not silently run paid live evaluation.

## Corpus and annotations

`backend/evaluation/datasets/manifest.json` contains a 35-paper identifier-only corpus design spanning NLP, computer vision, machine learning, systems, security, HCI, and information retrieval. Tags describe two-column, long/short, equation-heavy, table-heavy, figure-heavy, numeric, reference-heavy, and limitation coverage. PDFs are intentionally not committed.

`annotations.jsonl` is a versioned JSONL starting point. `BenchmarkPaperAnnotation` supports `DRAFT`, `REVIEWED`, and `ADJUDICATED` status, optional fields, evidence text, page numbers, and section titles. Annotation import/export helpers keep human judgments separate from system predictions. Results remain `PRELIMINARY` until reviewed/adjudicated annotations and frozen production predictions are supplied.

The deterministic loader expands the small smoke seed into at least 50 retrieval cases, 50 verification cases, 30 Paper Chat questions, and several research-agent/synthesis tasks. These are fixture plumbing checks, not claims about live PaperLens quality.

## Metrics

The pure metric module includes Precision@K, Recall@K, Hit@K, MRR, nDCG, F1, confusion matrices, citation validity/completeness, evidence attribution precision/recall/F1, numeric fidelity, latency summaries, boundary F1, ordered section accuracy, artifact set metrics, exact-field accuracy, and lexical claim matching. Metric inputs reject invalid lengths, non-finite values, negative latency, and invalid K. AI-as-judge is not used as ground truth.

The structured runners define parser/section/paragraph/artifact, research extraction, verification, retrieval (BM25/Semantic/Hybrid fixture lanes), Paper Chat, discovery/agent budgets, and cross-paper synthesis result shapes. Missing annotation or live predictions are reported as `not measured`, never fabricated.

## Reproducibility and outputs

Every report records benchmark, dataset, annotation, and metric versions; Git commit; retrieval mode; AI/embedding provider and model; prompt/schema versions; timestamp; seed; and live/offline mode. A run directory contains:

```text
metadata.json
report.json
report.md
retrieval.json
verification.json
...
```

Generated outputs should be written outside the repository or an ignored output directory. Ground truth is never overwritten by predictions.

## Failure analysis and safety

`backend/evaluation/failures.py` provides a shared taxonomy covering parser splits/merges, missed artifacts, wrong/missing evidence, numeric drift, retrieval misses, verifier false support/contradiction, chat hallucination/abstention, discovery duplicates/irrelevance, synthesis unsupported claims, and gap overclaims. Universal-absence gap assertions target zero. Adversarial cases cover prompt injection, fake evidence IDs, wrong-paper citations, numeric manipulation, and cross-document contamination without weakening production validation.

## Current limitations

The corpus is identifier-only, annotation coverage is intentionally preliminary, live AI/embedding/arXiv evaluation is not run by default, and browser automation remains outside the core benchmark. Retrieval latency is marked not measured by the offline fixture runner rather than conflating local fixture time with network-dependent production latency. BM25 remains the production default; no benchmark command changes production configuration automatically.
