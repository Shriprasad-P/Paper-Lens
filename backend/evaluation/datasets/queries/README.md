# Reviewed retrieval-query ledger

The Phase 15 target is 60–100 reviewed queries over the frozen public-paper
corpus. Each JSONL record must contain `case_id`, `paper_id`, `document_id`, a
natural-language question, one or more primary evidence IDs, optional
secondary evidence IDs, category, split, and reviewer notes. Lexical copies
of the evidence text are not acceptable queries.

The checked-in `smoke_cases.json` remains a synthetic plumbing fixture and is
not a reviewed retrieval benchmark.
