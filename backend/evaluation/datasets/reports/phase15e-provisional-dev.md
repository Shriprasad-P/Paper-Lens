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

- Embedding: **NOT_CONFIGURED** — No real embedding provider is configured; hash-v1 is test-only and excluded.
- Embedding provenance hash: `not available (no real model)`.
- Embedding config hash: `85fe1e70e745c29830adfe2230d79042abc672964d7a47d6ecd277f04139ef04`; device `NOT_RUN`; records embedded `0`.
- Generation: **NOT_CONFIGURED** — provider `openai_compatible`, model `none` (intended `gpt-4o-mini`).
- Generation provider available: **False**; model configured: **False**.
- Local generation runtime: **mlx-lm** 0.31.3; model `/Users/shriprasad/Documents/Research-Paper/models/mlx-Qwen2.5-7B-Instruct-a09a35458c702b33eeacc393d103063234e8bc28-bf16-v3`; revision `unknown-local-export`; quantization `none`.
- Local server: **NOT_STARTED** at `http://127.0.0.1:8001/v1`; AIProvider base URL is `https://api.openai.com/v1`; PaperLens AIProvider smoke test **NOT_RUN**.
- MLX/Metal probe: **UNAVAILABLE** — MLX core is present, but the mlx-lm runtime import failed before model loading; no usable local inference path is available in this execution context.
- Prompt hashes: `{'verification': '36c8cf0592b6f840dbfaa1147ee7498a9fd5e97a8b557945f237f62719ed83d7', 'chat': '17471bff55a550c60002b261f8c3652a03ab1583e0adcd7c51bcb993b89d6d7c', 'agent_planning': '65cb336063b03d03f57d79697c358ae4dfbe878abe09240319d3f22756bb061c', 'agent_synthesis': 'dcc95fdc2417f3dd5fd8fde6e758569c7f96186d012e75cd932a69a8dc570938'}`.
- Verification, chat, and agent lanes: **NOT RUN**; no provider calls were made.
- Human chat and agent scores: **null / NOT_REVIEWED**.

## Reproducibility and safety

- Corpus hash: `eb3925e01260897f383c9832e1c564aeff7197e192a62d19ce63cc0f1a0309c1`
- Benchmark hash: `7c3428d3e3f673b4cd67b89a50c3cdf046854ccd8bfd37017aa891079cd4c244`
- BM25 prediction hash: `8c7873a127e65393f1ecc6cfe76e2d1c8c97f72b105bce3e2515630393f9bcb5`
- Provisional evaluation config hash: `4afd22ce7d3a6fa0d3609d93817739a51ee1f3bba00e604657cfd515c3401673`
- Offline reproduction: **PASS for report construction and BM25 prediction hash; provider lanes NOT_RUN**
- Tuning performed: **NONE**
- FINAL touched: **False**
- Phase 15E-P: **NOT CLOSED**; Phase 15E-R: **NOT CLOSED**; Phase 15E-S: **NOT CLOSED**; Phase 15 overall: **NOT CLOSED**
- Architecture decision: No supported real local embedding runtime is available. An existing Qwen MLX instruct artifact was discovered, but its runtime cannot acquire Metal here; affected lanes are explicitly NOT_RUN.

Quality values in this report are engineering diagnostics only. DRAFT annotations, zero human reviewers, and unavailable provider lanes prevent publishable claims.
