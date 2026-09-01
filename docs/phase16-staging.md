# Phase 16 staging runbook

This runbook describes the smallest production-like PaperLens topology used
for the Phase 16 proof. It keeps the API and durable research worker in
separate processes and uses PostgreSQL rather than SQLite.

## Topology

```text
Browser / desktop launcher
            |
            v
       Next.js frontend
            |
            v
       FastAPI API  ------> Ollama (qwen3:4b, nomic-embed-text)
            |
            v
        PostgreSQL <------- independent Phase 13B research worker
            |
            v
   local persistent paper/artifact storage
            |
            v
   isolated PDF parser child processes
```

## Reproduce staging locally

1. Install Python dependencies, Node, Rust, PostgreSQL, and Ollama. Start
   Ollama and verify both `qwen3:4b` and `nomic-embed-text` are present. Metal
   acceleration is used automatically when available; Ollama's CPU path is
   the fallback.
2. Create an empty PostgreSQL database and set the staging variables in
   `.env` using the staging reference block in `.env.example`. Use an explicit
   frontend origin and a writable persistent `PAPERLENS_STORAGE_PATH`.
3. Run `PYTHONPATH=backend python -m alembic upgrade head` once before starting
   the API. Staging must use `PAPERLENS_AUTO_CREATE_SCHEMA=false`.
4. Start the API independently, for example:

   ```bash
   PYTHONPATH=backend uvicorn backend.app.main:app --host 127.0.0.1 --port 18080
   ```

5. In a second terminal, start the worker with the same environment and
   `PAPERLENS_RESEARCH_WORKER_ENABLED=true`:

   ```bash
   PYTHONPATH=backend python -m app.research.worker
   ```

6. Start the frontend separately with `npm run dev -- --hostname 127.0.0.1
   --port 13000`, or use the desktop launcher for the local desktop flow.
7. Run the deterministic HTTP/Ollama smoke check. Credentials are supplied at
   runtime and are never stored in the repository:

   ```bash
   PYTHONPATH=backend python -m evaluation.phase16_staging_smoke \
     --base-url http://127.0.0.1:18080 \
     --origin http://127.0.0.1:13000 \
     --email "$PAPERLENS_SMOKE_EMAIL" \
     --password "$PAPERLENS_SMOKE_PASSWORD"
   ```

The compose file remains a static production packaging profile; its runtime
validation requires a Docker daemon. The Phase 16 proof records that runtime
limitation rather than treating a missing daemon as a successful container
test.
