# PaperLens Phase 15B Evaluation Report

Generated: 2026-08-29T12:22:15.835862+00:00

**Overall status: NOT CLOSED** — draft-ledger diagnostics are not product-quality claims.

## 65-point report

1. Baseline commit: `78a14a16e221eaf818b0626d0ce2a4b000abf166`; working tree intentionally uncommitted.
2. Retained paper count: 35.
3. Excluded papers: none; no objective exclusion was needed.
4. Exact arXiv versions: 1406.2661v1, 1502.03167v3, 1505.00387v2, 1512.03385v1, 1602.07360v4, 1603.00856v3, 1611.03530v2, 1703.06103v4, 1704.04861v1, 1706.02216v4, 1706.03762v7, 1709.07876v3, 1711.05101v3, 1802.05352v3, 1804.06439v3, 1805.02262v1, 1807.01587v3, 1810.04805v2, 1902.06705v2, 1904.08375v2, 1905.11946v5, 1909.02130v1, 2001.08361v1, 2003.08934v2, 2005.11401v4, 2006.03031v2, 2101.03961v3, 2104.07653v2, 2106.09685v2, 2108.07258v3, 2201.07243v2, 2203.11171v4, 2301.08727v2, 2302.01318v1, 2303.08774v6.
5. PDF source hashes: every retained PDF has a persisted SHA-256 in the corpus manifest and was rechecked.
6. PaperLens document hashes: every retained document has a frozen normalized_document_hash.
7. Evidence counts: 34117 registry records across 35 documents.
8. Benchmark hash: `7c3428d3e3f673b4cd67b89a50c3cdf046854ccd8bfd37017aa891079cd4c244`; corpus hash `eb3925e01260897f383c9832e1c564aeff7197e192a62d19ce63cc0f1a0309c1`.
9. DEV paper list/count: 24 — arxiv_1406_2661, arxiv_1502_03167, arxiv_1505_00387, arxiv_1512_03385, arxiv_1602_07360, arxiv_1603_00856, arxiv_1611_03530, arxiv_1703_06103, arxiv_1704_04861, arxiv_1706_02216, arxiv_1706_03762, arxiv_1709_07876, arxiv_1711_05101, arxiv_1802_05352, arxiv_1804_06439, arxiv_1805_02262, arxiv_1807_01587, arxiv_1810_04805, arxiv_1902_06705, arxiv_1904_08375, arxiv_1905_11946, arxiv_1909_02130, arxiv_2001_08361, arxiv_2003_08934.
10. FINAL paper list/count: 11 — arxiv_2005_11401, arxiv_2006_03031, arxiv_2101_03961, arxiv_2104_07653, arxiv_2106_09685, arxiv_2108_07258, arxiv_2201_07243, arxiv_2203_11171, arxiv_2301_08727, arxiv_2302_01318, arxiv_2303_08774.
11. Retrieval reviewed query count: 0; 60 real-evidence cases exist but are DRAFT.
12. Retrieval reviewer count: 0.
13. BM25 Recall@1/@3/@5/MRR/nDCG@5: 0.9000/0.9500/0.9833/0.9297/0.9430 over 60 DRAFT cases.
14. Semantic Recall@1/@3/@5/MRR/nDCG@5: NOT RUN; no real embedding provider, and hash-v1 is excluded.
15. Hybrid Recall@1/@3/@5/MRR/nDCG@5: NOT RUN because semantic retrieval is unavailable.
16. Primary retrieval configuration: production BM25EvidenceRetriever, bm25-v1, top-10 ranking.
17. Retrieval error analysis: {'lexical_or_embedding_miss': 1}; numeric cases are present in the draft ledger.
18. Verification reviewed count: 0/50.
19. Verification label distribution: UNVERIFIED=50 (safe draft placeholder).
20. Verification accuracy: NOT MEASURED; no human gold.
21. Verification macro F1: NOT MEASURED.
22. Per-label verification metrics: NOT MEASURED.
23. False-support rate: NOT MEASURED.
24. False-rejection rate: NOT MEASURED.
25. Numeric-case count: 12 verification, 8 chat, and 10 retrieval drafts; values are explicit but unreviewed.
26. Numeric fidelity: NOT MEASURED; no provider predictions.
27. Chat reviewed count: 0/40.
28. Chat citation precision: NOT MEASURED.
29. Chat required-evidence coverage: NOT MEASURED.
30. Chat unsupported-claim rate: NOT MEASURED.
31. Chat abstention accuracy: NOT MEASURED.
32. Chat numeric fidelity: NOT MEASURED.
33. Human chat score: NOT MEASURED; reviewer count is zero.
34. Agent task count: 10 bounded DRAFT tasks (5 DEV, 5 FINAL).
35. Agent human-review count: 0.
36. Agent completion rate: NOT MEASURED.
37. Agent evidence-grounded completion: NOT MEASURED.
38. Agent unsupported-claim rate: NOT MEASURED.
39. Agent source relevance: NOT MEASURED.
40. Agent duplicate-source rate: NOT MEASURED.
41. Agent ingestion success: corpus ingestion is 35/35; agent-run ingestion is NOT MEASURED.
42. Agent average iterations/provider calls: NOT MEASURED.
43. Provider/model configuration: local retrieval-only run, provider none, zero LLM calls.
44. Embedding configuration: embedding_provider=none; no semantic model/revision is claimed.
45. DEV baseline: Recall@1/@3/@5 0.8750/0.9375/0.9792, MRR 0.9122, nDCG@5 0.9287 on 48 DRAFT cases.
46. Improvement made: none; no tuning round was run.
47. System freeze point: source/document/evidence exports and retrieval envelope are hash-frozen; no quality tuning was performed.
48. FINAL result: BM25 on 12 DRAFT cases, Recall@1/@3/@5 1.0000/1.0000/1.0000, MRR 1.0000, nDCG@5 1.0000; not publishable.
49. Prediction hashes: retrieval `ab51abfee8e981ad3d1798b6f279ae18b22156fa0d119102d317f128fd3fb52b`; verification/chat/agent NOT GENERATED.
50. Annotation hashes: retrieval `5a19b320755b47dc6d9a3d89dc439ad62100365004208556b59b14603cdd4fbf`, verification `a4ae45bed74e4db4bf74d0bed9c6e002f28441e2527440a833fa20b079ced5be`, chat `81645d25a5697308f54e541c4c6c1b425070623d11c018604f90d4244d743bd9`, agent `c0e16130be483227c9dd82c78f16c1bed904493e7afc675b13c95bf112829892`; all DRAFT.
51. Representative real successes: ranked evidence is preserved for successful BM25 cases; no reviewed success gallery is claimed.
52. Representative real failures: rank@5 misses remain in frozen predictions; other real failures await provider runs.
53. Publishable claim table: no claims are publishable; real BM25 values are DRAFT diagnostics only.
54. Approximate evaluation cost: local PDF acquisition/parse and BM25 only; provider cost $0, tokens 0.
55. Latency context: no provider or product-quality latency claim was made.
56. Offline reproducibility: PASS for the measured BM25 lane from frozen inputs without network/provider calls.
57. Backend full-suite: 97 tests passed, 1 optional PostgreSQL test skipped; latest rerun remains green after validator changes.
58. Phase 13A regression: PASS in the full backend suite.
59. Phase 13B regression: PASS in the full backend suite.
60. Phase 14 regression: PASS in the full backend suite.
61. Files changed: real corpus PDFs/metadata/exports, draft ledgers/rubric, ingestion/retrieval runners, provenance/validation, docs, and validator test.
62. Files intentionally not modified: portfolio publication claims, Phase 16, and unrelated product architecture.
63. Remaining limitations: zero human review; no provider-backed verification/chat/agent predictions; no real semantic/hybrid lane; no reviewed FINAL quality run.
64. Working-tree status: dirty and intentionally uncommitted; no commit, push, PR, branch, or attribution was created.
65. Phase 15: NOT CLOSED. Phase 15B has real corpus/provenance/BM25 progress, but human-reviewed gold and real verification/chat/agent/embedding FINAL evidence are unmet.

## Per-paper snapshot identity

| arXiv version | title | PDF SHA-256 | PaperLens document hash | evidence |
|---|---|---|---|---|
| `1406.2661v1` | Generative Adversarial Networks | `ff5819e3a7b713c3bd3107b7de3d51fe0a347aa5d8444f0efdcf2345ef0a8b63` | `fe485327ec57f6f92134d3668967c7f04244ee6f12de38419677ad275feeca59` | 337 |
| `1502.03167v3` | Batch Normalization: Accelerating Deep Network Training by Reducing Internal Covariate Shift | `bdc69e0b568f41d8d3181cc9077a461f58fcdd1c70c9f49efe60a05ee6109655` | `05cc6c815a4dded2def1ff9311a0a88573617c4f359d44dadd5e1690e5bd8253` | 456 |
| `1505.00387v2` | Highway Networks | `ff433aab020c62f784ba66ce031669538e3dde1769bb2d326ba0ebed5e822faa` | `e5b7728feba1981ca71c7b617ddc33640441eb11c749a562fff3c95c051b45b3` | 268 |
| `1512.03385v1` | Deep Residual Learning for Image Recognition | `1e0651b6810ecba34a3dbc5b5b0209226f889004607c1f203540a48d64e5a93a` | `893c8d9ee7b8e21de2ec9ed60c2e268e0544a68cde245ee3d006721c63b85e57` | 665 |
| `1602.07360v4` | SqueezeNet: AlexNet-level accuracy with 50x fewer parameters and <0.5MB model size | `cbca3e2a3e93317534336896b2678f0ba75b898b272fdd864312311a7e23291e` | `6b52a1455a28076ed6ec076923a6e9e9c95f8fe2d66661d3e382c37b6d8fdc05` | 461 |
| `1603.00856v3` | Molecular Graph Convolutions: Moving Beyond Fingerprints | `816a722de230d1ff7a8fc64921e2fa8dce502e83b786be75f6ac10e0b54e6cae` | `f5ce4ac471eb8896110f31e350b64c7f9da72c934d6857368719d7fbcb177dcb` | 1333 |
| `1611.03530v2` | Understanding deep learning requires rethinking generalization | `a71f1294a021cebc6939ec977fc073b6d7b4f183950eba761ec55364d30b729f` | `07228291b179905e138399a04909ae746a66cb9820d7d86990b32b9926753a75` | 519 |
| `1703.06103v4` | Modeling Relational Data with Graph Convolutional Networks | `7f2fa4aa0ac16f46f9d2459ff432d740b5ac8c36bcea598ba95ec34ef1d126bd` | `42ff23fd5a9c60505a2b0bfd23465cde3100a0cf3a4fca34d2dd06a43c0066d4` | 298 |
| `1704.04861v1` | MobileNets: Efficient Convolutional Neural Networks for Mobile Vision Applications | `9fd87b02ecc96c1ecf2b8c2166faf969a2acb187ab3e1e9333b26d226387ff55` | `2ab02169a4520a1d7c91d77fcf7019cc235f520b5dd504c1e01692a69cbf359c` | 290 |
| `1706.02216v4` | Inductive Representation Learning on Large Graphs | `e1f354eb12011cde24af1eb500d72463fc971b09d26b55688c7f918a86e31ce8` | `2e983368880035564846db61216db1726fdd566fb2e51cf350dbd733ceebf6fb` | 667 |
| `1706.03762v7` | Attention Is All You Need | `bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697` | `26fa33c9679a9dccffb4e5cc5840d55f5e1e70f88b9ac82c361fbd7bfd03591f` | 931 |
| `1709.07876v3` | Fast, Robust, and Versatile Event Detection through HMM Belief State Gradient Measures | `4b0c648b33d6835b3d0ae9651a410f3a5bf871a64ca8afe044f4fa6a3bce5788` | `82f0e4e14de6ee766d5c4357480e19ad3cf341aa176cd8fc3196f9dc6fd20b0d` | 428 |
| `1711.05101v3` | Decoupled Weight Decay Regularization | `9d5af48931e773d6983d167e15c06ef594475b751c1f263827f5ed3c7a00d0d8` | `b9e9416a947d12f239b6ddb96aa3551ee18b3e489226b9aa3dc67805683f3c68` | 436 |
| `1802.05352v3` | Gibbs Partitions, Riemann-Liouville Fractional Operators, Mittag-Leffler Functions, and Fragmentations Derived From Stable Subordinators | `2e12542dfbe2d6ce879f6dea15814a97fdc2eccd3867cc0df09dc2cf80e4e0d7` | `345123942470e776aae8d7cccaa460b567e59c80035ef4e1572b85e1f8815378` | 5017 |
| `1804.06439v3` | Personalized neural language models for real-world query auto completion | `400e02a3d2030452bca54b12a371198f8a3cd2215e19c14400f15729faea8c5f` | `fd06af0de7565c1bda86fe44483b2b0813b04180defd4d1282802a98fff3f0d8` | 197 |
| `1805.02262v1` | Construction of the Literature Graph in Semantic Scholar | `c388a8aec010d9d45eba85dd06f81e8412e60e643bea99c173842d2caf3e5850` | `8614f7593f600ac72ba3f378cd841b9c5d95ca1fb168b64570b41dde3c49d12a` | 283 |
| `1807.01587v3` | Is the Big Rip unreachable? | `1ce53b64dc454bf1d819f03c413c040c3ae9ed3e3dde4ae393c63ab76dfa77f5` | `515fcdf7ea22b0da135ccf68dc381f00b758e413a742a97996c7a13cc4e69df6` | 263 |
| `1810.04805v2` | BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding | `5692a5514787a8c6727b4ff3b726a3385798bc68e12138d1d4af83947e2acf6e` | `54f2491f5dde0532d4c828f1cd0bad31590a42746b661db0e30ecfc729f5f2dc` | 750 |
| `1902.06705v2` | On Evaluating Adversarial Robustness | `418ab1586fcee19234214c48385a8f37040acea7de120ec0da413344bb9c63db` | `1f8bbe748bd8209bf59208f73353c93e232429607aa5750f1d54d21e9e5a06b1` | 559 |
| `1904.08375v2` | Document Expansion by Query Prediction | `ae7ba200f53ac3beb3d9c9c6797226ffd4029b9cb6bd3495e3b65169554c55e5` | `a83b5a1ea063adc731c9642f06ea1f36c183e8abcc6e8691cfccbd999fa11a91` | 211 |
| `1905.11946v5` | EfficientNet: Rethinking Model Scaling for Convolutional Neural Networks | `af6b1bd620f81bfaea81edf8227484588e1fcc2427d6b5020fa17454d7566c70` | `d28cb53cd483235b58ede63116c9e7d1cb3f8225c5cb581fd6315be0faf00483` | 610 |
| `1909.02130v1` | Noise and spectral stability of deep-UV gas-filled fiber-based supercontinuum sources driven by ultrafast mid-IR pulses | `d87d742de3c8945a6e1920831521ca8833d83b33d2a373c520e07c00d4c55448` | `a54079da705af8bdced4062b9497334ac261ad92871b40d2c1b72aa0c1da558e` | 337 |
| `2001.08361v1` | Scaling Laws for Neural Language Models | `a41bd7877fd1a6bcbba096b2619618bd2f90e02488f2365644903eb2f7c6a494` | `9774ff1f5f1af61adf1099330f1504816503472b490a028fb693dd052fe37c35` | 1262 |
| `2003.08934v2` | NeRF: Representing Scenes as Neural Radiance Fields for View Synthesis | `c7fc70b38f84cb2e42890a69a7c9b9c26ded464b221e0355031004f24fb8e727` | `9ab61afe12e014d137e819170acc2fa107395ff59555e613f09d895506f6d25e` | 862 |
| `2005.11401v4` | Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks | `23e3249e9a1e75418d82efecab0ea8c4d033b89c93742f63208d47ce01f21233` | `4800493c5bee8bd80e3ee909db1e0e3cd2aac536ab817186b29d5de64bc0eec8` | 598 |
| `2006.03031v2` | Nimble: Efficiently Compiling Dynamic Neural Networks for Model Inference | `e9db7bdd8670226700eccbbd1841a8531ab4ab1154d3158ac34f0cf3f4eeba3e` | `5bbcc5ae62db916cc20ba1f39492db8ba33354d083c1d5ccd0fbd84934a36633` | 479 |
| `2101.03961v3` | Switch Transformers: Scaling to Trillion Parameter Models with Simple and Efficient Sparsity | `f340f6ace31abf7d0730ef461404279f40d3c890e9cc2daeb7068b3304afdbd6` | `42ffa0eb58feedb2fc354062ff80f07bf9eb89bc088b3ecbf41b76cd919b40e4` | 1028 |
| `2104.07653v2` | Quantifying entanglement of two-qubit Werner states | `c1485f4c4349307ba87fe4e0c196b224037ea40e56208420c29ac5acbe29ceac` | `bf91122cfbeae86d7bdd26f7804ab89a9931559a8de806d83e33190c83068096` | 638 |
| `2106.09685v2` | LoRA: Low-Rank Adaptation of Large Language Models | `e9a0d3128767db616085dc0f4e6e455e672e89af823e8ed1282793682787395a` | `6cbafa00a1112a3472778965a8100d19a0eb77ebb3f695c5a8d317b5d4a08306` | 1080 |
| `2108.07258v3` | On the Opportunities and Risks of Foundation Models | `05e867e3c710a3b0c0e13eb372d013c3511f2ee114bace5ca5c402d6341e92dd` | `b95cc3b96990b7f34d55f3fc2911053c955f39a919aff62616c3edf701e10aea` | 4886 |
| `2201.07243v2` | Primordial black holes from an electroweak phase transition | `d66db391c923a70146386c53b4d8e28a824549f04d8bf5638dc8b4729b1cf300` | `4a9213e41f0c9a4c1218a775d7a82905773098987a7438a4bbf5a447000afd50` | 913 |
| `2203.11171v4` | Self-Consistency Improves Chain of Thought Reasoning in Language Models | `1a49ce0373afc89d2d6e97fb1aa8230f6b818c70590d732a3187f753f4df6aba` | `34a896ae0525bd4303e06e9a2f83af3dfb888538056417e1ac83d15956d5df2d` | 1226 |
| `2301.08727v2` | Neural Architecture Search: Insights from 1000 Papers | `b57ae6d6321a7c065e1a62320db8224dd768ffe5b4f47b796b6f5cea84169ed3` | `2b81090bbc507bbdea454034f17a6eb08e1185980872f0fb1bbc00d61de5d00a` | 1991 |
| `2302.01318v1` | Accelerating Large Language Model Decoding with Speculative Sampling | `ffa03c6ae46f3122570bacd7da358cae8659b6421162bbc25088622fd4889c37` | `7bdd220ef7631bf1508d8dedfc38de08aaae913eb61d62d85184362dc11f6cc5` | 371 |
| `2303.08774v6` | GPT-4 Technical Report | `c33a66dadca2388d7b172d6293b00dc32b71110c6f38fafe0d41112e61be7774` | `a424b3325c020d2b630184cbfce60da93501a042998ca0b2d4698720c0318485` | 3467 |

Structured records: `backend/evaluation/datasets/corpus/manifest.json`, `documents.json`, `evidence.jsonl`, and `ingestion.json`. Draft ledgers/rubric: `backend/evaluation/datasets/real_annotations/`.
