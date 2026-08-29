# Annotation policy

Annotations are evaluator-only gold data. They are never sent to retrieval,
generation, or provider prompts at runtime.

For each paper, reviewers bind claims, retrieval queries, verification items,
and chat questions to the exact `document_id` and evidence IDs. Retrieval
queries cover factual, method, metric, limitation, terminology/equation,
table/numeric, and multi-passage questions. Verification labels distinguish
`SUPPORTED`, `PARTIALLY_SUPPORTED`, `UNSUPPORTED`, `CONTRADICTORY`, and the
safe default `UNVERIFIED`; the rationale and numeric facts are required for a
reviewed item.

`DRAFT` records are infrastructure only. `REVIEWED` means one human reviewer
completed the rubric. `ADJUDICATED` means disagreements were resolved by a
recorded adjudicator. One reviewer is reported as single-reviewer annotation,
never as inter-annotator agreement.
