# PaperLens Engineering Rules

## Core

PaperLens is an evidence-grounded research-paper visualization platform.
Every semantic interpretation must remain traceable to paper evidence. Never fabricate research content.

## Engineering

- Inspect existing code before editing.
- Prefer the smallest coherent change.
- Keep parser, extraction, verification, and rendering separated.
- Use typed boundaries between pipeline stages.
- Do not couple business logic directly to one LLM provider.
- Do not let the LLM generate arbitrary frontend code.
- Run relevant validation before declaring completion.
- Preserve unrelated user changes.

## Scope

Do not add infrastructure before it is required. Defer Redis, workers, vector databases, Manim, and microservices until their phase.

## Validation

- Backend: `python -m unittest discover -s backend/tests`
- Frontend: `npm run typecheck`, `npm run lint`, and tests when present

Read and maintain `docs/agent-state.md` and `docs/build-plan.md`.
