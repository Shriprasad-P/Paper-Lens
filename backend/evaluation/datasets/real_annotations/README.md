# Real-ledger review workflow

These JSONL files are the Phase 15C real-paper ledgers. They are currently
`DRAFT`; the repository contains no claimed human review. Every selected
evidence ID resolves to the frozen document/evidence export under
`../corpus/`.

Review one item locally with:

```bash
PYTHONPATH=backend python -m evaluation.review_cli retrieval real-retrieval-001 \
  --reviewer-id reviewer_local
```

The utility displays the case, cited evidence, and nearby same-section
context; accepts revised evidence IDs/labels/answerability, records a note and
UTC timestamp, and atomically marks the item `REVIEWED`. Use `--show-only` to
inspect without editing and `--refresh-manifest` to refresh exact ledger
hashes/counts after a review batch. `--freeze` requires every row to carry
reviewer metadata and notes, then prevents further edits until a new benchmark
version is created. Run the read-only `review_audit.json` generator (or rebuild
it from the ledgers) after edits. Metrics intended for publication must invoke
the reviewed-only guard; draft items are never silently promoted.

`human_review_rubric.json` defines the 0–2 human dimensions. If one reviewer
is used, record `reviewer_count: 1` and `review_type: single-reviewer`; never
claim inter-rater agreement without an independent second reviewer.
