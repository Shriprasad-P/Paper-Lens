# PaperLens Phase 15E-S

> **PROVISIONAL DEV EVALUATION**

> **EVALUATION STATUS: PROVISIONAL**  
> **ANNOTATIONS: DRAFT**  
> **HUMAN REVIEWERS: 0**  
> **FINAL DATASET USED: NO**  
> **TUNING: NONE**  
> **PUBLISHABLE QUALITY CLAIMS: NO**  
> **NOT PUBLISHABLE**  
> **NOT FINAL**

Evaluation status: **PROVISIONAL**  
Annotation status: **DRAFT**  
DEV cases: retrieval 48, verification 39, chat 29, agent 5

## Retrieval comparison (PROVISIONAL DEV / DRAFT GOLD)

| Lane | Recall@1 | Recall@3 | Recall@5 | MRR | nDCG@5 |
|---|---:|---:|---:|---:|---:|
| BM25 | 0.8750 | 0.9375 | 0.9792 | 0.9122 | 0.9287 |
| Semantic | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| Hybrid | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN |

Historical all-split BM25 baseline (preserved, not recomputed): Recall@1 0.9000 · Recall@3 0.9500 · Recall@5 0.9833 · MRR 0.9297. The DEV evaluator did not inspect FINAL aggregates.

## Provider and embedding status

- Embedding: **CONFIGURED_NOT_RUN** — Provider is configured but must be exercised in a separately approved run.
- Embedding provenance hash: `not available (no real model)`.
- Embedding config hash: `c1af21462bed70684f96985afd3b3a1f377f7f5936cf24c08ff478283036ccf0`; device `NOT_RUN`; records embedded `0`.
- Generation: **CONFIGURED_NOT_RUN** — provider `ollama`, model `qwen3:4b` (intended `qwen3:4b`).
- Generation provider available: **True**; model configured: **True**.
- Local generation runtime: **ollama** ; model `qwen3:4b`; revision `none`; quantization `none`.
- Local server: **AVAILABLE** at `http://127.0.0.1:11434/v1`; AIProvider base URL is `http://127.0.0.1:11434/v1`; PaperLens AIProvider smoke test **NOT_RUN**.
- MLX/Metal probe: **SKIPPED_OLLAMA_SELECTED** — Ollama is selected; the optional MLX probe was skipped to avoid competing for Metal memory.
- Prompt hashes: `{'verification': '36c8cf0592b6f840dbfaa1147ee7498a9fd5e97a8b557945f237f62719ed83d7', 'chat': '17471bff55a550c60002b261f8c3652a03ab1583e0adcd7c51bcb993b89d6d7c', 'agent_planning': '65cb336063b03d03f57d79697c358ae4dfbe878abe09240319d3f22756bb061c', 'agent_synthesis': 'dcc95fdc2417f3dd5fd8fde6e758569c7f96186d012e75cd932a69a8dc570938'}`.
- Verification, chat, and agent lanes: **NOT RUN**; no provider calls were made.
- Human chat and agent scores: **null / NOT_REVIEWED**.

## Reproducibility and safety

- Corpus hash: `eb3925e01260897f383c9832e1c564aeff7197e192a62d19ce63cc0f1a0309c1`
- Benchmark hash: `7c3428d3e3f673b4cd67b89a50c3cdf046854ccd8bfd37017aa891079cd4c244`
- BM25 prediction hash: `8c7873a127e65393f1ecc6cfe76e2d1c8c97f72b105bce3e2515630393f9bcb5`
- Provisional evaluation config hash: `79fd714b22d9325c6573d21136ac9952967a0dbf6c48833234ade0a0867828a6`
- Offline reproduction: **PASS for report construction and BM25 prediction hash; provider lanes NOT_RUN**
- Tuning performed: **NONE**
- FINAL touched: **False**
- Phase 15E-P: **NOT CLOSED**; Phase 15E-R: **NOT CLOSED**; Phase 15E-S: **NOT CLOSED**; Phase 15 overall: **NOT CLOSED**
- Architecture decision: Use the existing provider-neutral path with local Ollama (qwen3:4b for generation and nomic-embed-text for embeddings); Ollama can fall back to CPU when Metal is unavailable.

Quality values in this report are engineering diagnostics only. DRAFT annotations, zero human reviewers, and unavailable provider lanes prevent publishable claims.
