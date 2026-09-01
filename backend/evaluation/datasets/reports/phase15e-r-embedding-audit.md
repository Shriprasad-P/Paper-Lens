# PaperLens Phase 15E-S Local Runtime and Embedding Architecture Audit

> **EVALUATION STATUS: PROVISIONAL · ANNOTATIONS: DRAFT · HUMAN REVIEWERS: 0 · FINAL DATASET USED: NO · TUNING: NONE · PUBLISHABLE QUALITY CLAIMS: NO · NOT FINAL**

Status: **NOT_CONFIGURED**  
Provider: `none`  
Model: `none`  
Embedding provenance hash: `not available (no real model)`  
Embedding config hash: `85fe1e70e745c29830adfe2230d79042abc672964d7a47d6ecd277f04139ef04`  
Device used: `NOT_RUN`
Run eligibility: **BLOCKED_WITHOUT_REAL_PROVIDER**

No real embedding provider is configured; hash-v1 is test-only and excluded.

| Concern | Existing PaperLens behavior |
|---|---|
| Interface | `backend/app/retrieval/embeddings.py: EmbeddingProvider, cosine_similarity, create_embedding_provider`; async `embed_texts(list[str])` and `embed_query(str)` |
| Storage | evidence_embeddings JSON vectors keyed by paper/document/evidence/model/version |
| Dimensionality | Configured provider dimension is persisted per vector; no real dimension is claimed here (`None`) |
| Normalization / similarity | not configured / not configured |
| Batching | embed_texts(list[str]) |
| Caching | model/version/document/evidence hash must match; stale evidence is re-embedded |
| Document/evidence binding | retrieval filters one paper/document and stores both IDs |
| Fallback | HashEmbeddingProvider(hash-v1) exists for deterministic tests only; excluded from benchmark claims |
| Local runtimes | {'sentence_transformers': False, 'transformers': False, 'torch': False, 'mlx': False, 'mlx_lm': False, 'numpy': False, 'onnxruntime': False} |
| Local model runtime | /Users/shriprasad/miniconda3/bin/mlx_lm (0.31.3) |
| Metal/device probe | UNAVAILABLE — MLX core is present, but the mlx-lm runtime import failed before model loading; no usable local inference path is available in this execution context. |
| Embedding model selection | none; no supported local embedding model |

The audit records the existing product path and does not introduce a second embedding subsystem or run a benchmark model.
