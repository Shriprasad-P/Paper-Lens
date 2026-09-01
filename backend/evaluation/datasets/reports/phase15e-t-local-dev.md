# PaperLens Phase 15E-T — Local DEV Evaluation

> EVALUATION STATUS: PROVISIONAL · ANNOTATIONS: DRAFT · HUMAN REVIEWERS: 0 · EMBEDDINGS: nomic-embed-text · GENERATION: qwen3:4b via Ollama · FINAL DATASET USED: NO · TUNING: NONE · PUBLISHABLE QUALITY CLAIMS: NO

Phase 15E-T: **CLOSED**
Phase 15 overall: **NOT CLOSED**

## Retrieval comparison (PROVISIONAL DEV / DRAFT GOLD)

| Metric | BM25 | Semantic | Hybrid/RRF |
|---|---:|---:|---:|
| recall_at_1 | 0.8750 | 0.9583 | 0.9792 |
| recall_at_3 | 0.9375 | 0.9792 | 0.9792 |
| recall_at_5 | 0.9792 | 0.9792 | 0.9792 |
| mrr | 0.9122 | 0.9688 | 0.9792 |
| ndcg_at_5 | NOT RUN | 0.9715 | 0.9792 |

## Local runtime

- Ollama: `ollama version is 0.32.11`; external provider calls: **0**.
- Generation: `qwen3:4b` digest `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`; quantization `Q4_K_M`.
- Embeddings: `nomic-embed-text` digest `0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f`, dimension **768**, normalized **L2**; device **Metal when available; CPU fallback via Ollama**.
- Embedding config hash: `c924faa3b558349cda83d8e4868afe2767dc83388459ae5d5c10b0a1d4768c50`
- Provisional config hash: `85594a429437abf60fed74dbe36622dc4e0219606dc65f7bdda50d6aabc68e26`

## Lanes

- Verification: **MEASURED_PROVISIONAL**, metrics are PROVISIONAL / DRAFT GOLD.
- Chat: **MEASURED_PROVISIONAL**, human score `null`, review `NOT_REVIEWED`.
- Agent: **MEASURED_PROVISIONAL** — 

- Validation: backend **106 passed / 1 skipped**; Rust **2 passed**.

## Frozen artifacts

- semantic: `backend/evaluation/datasets/predictions/phase15e-t-semantic-dev.json` (SHA-256 `50908a900a3518887b6138c6fc394797575f59f634d533daf1dd00fe67b245e7`)
- hybrid: `backend/evaluation/datasets/predictions/phase15e-t-hybrid-dev.json` (SHA-256 `d45fa41798c2b668ffc3c516e1fe1c68d46ba965160dc79e264c370dc714527d`)
- verification: `backend/evaluation/datasets/predictions/phase15e-t-verification-dev.json` (SHA-256 `1c217aa87f4097fa1b509938b20eb796f8f093cf4502d27322755190253a6cfb`)
- chat: `backend/evaluation/datasets/predictions/phase15e-t-chat-dev.json` (SHA-256 `80fe609d060a071ec8fbf6ac07736f1261e839e6a8790761ded16257bac270c8`)
- agent: `backend/evaluation/datasets/predictions/phase15e-t-agent-dev.json` (SHA-256 `2ce27b3eb421e2e25482c82b8b1742ca89f048f4e963075e11b52b1f993ac1c2`)

Offline reproduction: **{'semantic': {'prediction_hash': '50908a900a3518887b6138c6fc394797575f59f634d533daf1dd00fe67b245e7', 'metrics': {'recall_at_1': 0.9583333333333334, 'ndcg_at_1': 0.9583333333333334, 'recall_at_3': 0.9791666666666666, 'ndcg_at_3': 0.9714777031994054, 'recall_at_5': 0.9791666666666666, 'ndcg_at_5': 0.9714777031994054, 'mrr': 0.96875}}, 'hybrid': {'prediction_hash': 'd45fa41798c2b668ffc3c516e1fe1c68d46ba965160dc79e264c370dc714527d', 'metrics': {'recall_at_1': 0.9791666666666666, 'ndcg_at_1': 0.9791666666666666, 'recall_at_3': 0.9791666666666666, 'ndcg_at_3': 0.9791666666666666, 'recall_at_5': 0.9791666666666666, 'ndcg_at_5': 0.9791666666666666, 'mrr': 0.9791666666666666}}, 'verification': {'prediction_hash': '1c217aa87f4097fa1b509938b20eb796f8f093cf4502d27322755190253a6cfb', 'metrics': {'accuracy': 0.1282051282051282, 'macro_f1': 0.045454545454545456, 'per_label': {'SUPPORTED': {'precision': 0.0, 'recall': 0.0, 'f1': 0.0, 'support': 0.0}, 'PARTIALLY_SUPPORTED': {'precision': 0.0, 'recall': 0.0, 'f1': 0.0, 'support': 0.0}, 'CONTRADICTORY': {'precision': 0.0, 'recall': 0.0, 'f1': 0.0, 'support': 0.0}, 'UNSUPPORTED': {'precision': 0.0, 'recall': 0.0, 'f1': 0.0, 'support': 0.0}, 'UNVERIFIED': {'precision': 1.0, 'recall': 0.1282051282051282, 'f1': 0.22727272727272727, 'support': 39.0}}, 'false_support_rate': 0.8717948717948718, 'false_rejection_rate': 0.0, 'numeric_fidelity': 1.0}}, 'chat': {'prediction_hash': '80fe609d060a071ec8fbf6ac07736f1261e839e6a8790761ded16257bac270c8', 'metrics': {'citation_precision': 0.47413793103448276, 'required_evidence_coverage': 0.5517241379310345, 'unsupported_claim_rate': None, 'abstention_behavior': {'insufficient_evidence': 4, 'generation_failed': 3}, 'numeric_fidelity': 0.7586206896551724}}, 'agent': {'prediction_hash': '2ce27b3eb421e2e25482c82b8b1742ca89f048f4e963075e11b52b1f993ac1c2', 'metrics': {'completion_rate': 1.0, 'evidence_id_validity': 1.0, 'citation_validity': 1.0, 'ingestion_success': 1.0, 'duplicate_source_rate': 0.0, 'average_iterations': 2.0, 'provider_calls': 96, 'duration': 88.173}}, 'all_provider_calls_disabled': True}**
FINAL touched: **False** · Tuning: **NONE** · Phase 15 overall: **NOT CLOSED**
