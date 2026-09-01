# PaperLens Phase 15E-S Local Runtime and Embedding Architecture Audit

> **EVALUATION STATUS: PROVISIONAL · ANNOTATIONS: DRAFT · HUMAN REVIEWERS: 0 · FINAL DATASET USED: NO · TUNING: NONE · PUBLISHABLE QUALITY CLAIMS: NO · NOT FINAL**

Status: **CONFIGURED_NOT_RUN**  
Provider: `ollama`  
Model: `nomic-embed-text`  
Embedding provenance hash: `not available (no real model)`  
Embedding config hash: `c1af21462bed70684f96985afd3b3a1f377f7f5936cf24c08ff478283036ccf0`  
Device used: `NOT_RUN`
Run eligibility: **READY_FOR_SEPARATE_DEV_RUN**

Provider is configured but must be exercised in a separately approved run.

| Concern | Existing PaperLens behavior |
|---|---|
| Interface | `backend/app/retrieval/embeddings.py: EmbeddingProvider, cosine_similarity, create_embedding_provider`; async `embed_texts(list[str])` and `embed_query(str)` |
| Storage | evidence_embeddings JSON vectors keyed by paper/document/evidence/model/version |
| Dimensionality | Configured provider dimension is persisted per vector; no real dimension is claimed here (`768`) |
| Normalization / similarity | l2 / cosine |
| Batching | embed_texts(list[str]) |
| Caching | model/version/document/evidence hash must match; stale evidence is re-embedded |
| Document/evidence binding | retrieval filters one paper/document and stores both IDs |
| Fallback | HashEmbeddingProvider(hash-v1) exists for deterministic tests only; excluded from benchmark claims |
| Local runtimes | {'sentence_transformers': False, 'transformers': False, 'torch': False, 'mlx': False, 'mlx_lm': False, 'numpy': False, 'onnxruntime': False} |
| Local model runtime | /Users/shriprasad/miniconda3/bin/mlx_lm (0.31.3) |
| Metal/device probe | SKIPPED_OLLAMA_SELECTED — Ollama is selected; the optional MLX probe was skipped to avoid competing for Metal memory. |
| Embedding model selection | nomic-embed-text |

The audit records the existing product path and does not introduce a second embedding subsystem or run a benchmark model.
