"""Deterministic, credential-free-by-source staging smoke checks.

The operator supplies credentials at runtime; this module never contains a
password, token, or API key.  It intentionally exercises the public HTTP
surface and loopback Ollama endpoints rather than reaching into application
objects, so it can be run against an independently started staging stack.

Example::

    PYTHONPATH=backend python -m evaluation.phase16_staging_smoke \
      --base-url http://127.0.0.1:18080 \
      --origin http://127.0.0.1:13000 \
      --email "$PAPERLENS_SMOKE_EMAIL" \
      --password "$PAPERLENS_SMOKE_PASSWORD" \
      --paper-id paper_... \
      --worker-run-id research_...

The command prints a JSON result and exits non-zero if a required check fails.
Ollama checks are optional only when ``--skip-ollama`` is explicitly passed.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class Check:
    name: str
    status: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


def _model_names(payload: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for item in payload.get("models", []):
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            names.add(item["name"])
    return names


def _has_model(names: set[str], requested: str) -> bool:
    return requested in names or requested.split(":", 1)[0] in {n.split(":", 1)[0] for n in names}


def _check_http(response: httpx.Response, expected: int) -> str:
    if response.status_code != expected:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:240]}")
    return "ok"


def run(args: argparse.Namespace) -> tuple[list[Check], bool]:
    checks: list[Check] = []
    ok = True
    headers = {"Origin": args.origin}
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=args.timeout) as client:
        for path in ("/health/live", "/health/ready"):
            try:
                _check_http(client.get(path, headers=headers), 200)
                checks.append(Check(path, "PASS", "HTTP 200"))
            except Exception as exc:  # pragma: no cover - exercised by staging
                checks.append(Check(path, "FAIL", str(exc)))
                ok = False

        try:
            login = client.post(
                "/api/auth/login",
                json={"email": args.email, "password": args.password},
                headers=headers,
            )
            _check_http(login, 200)
            checks.append(Check("authentication", "PASS", "login and session cookie accepted"))
        except Exception as exc:
            checks.append(Check("authentication", "FAIL", str(exc)))
            return checks, False

        try:
            _check_http(client.get("/api/auth/me", headers=headers), 200)
            workspace = client.post(
                "/api/workspaces",
                json={"name": "Phase 16 smoke workspace"},
                headers=headers,
            )
            _check_http(workspace, 201)
            workspace_id = workspace.json().get("id", "")
            listed = client.get("/api/workspaces", headers=headers)
            _check_http(listed, 200)
            checks.append(Check("workspace", "PASS", f"created {workspace_id}"))
        except Exception as exc:
            checks.append(Check("workspace", "FAIL", str(exc)))
            ok = False

        if args.paper_id:
            try:
                reader = client.get(f"/api/papers/{args.paper_id}/reader", headers=headers)
                _check_http(reader, 200)
                checks.append(Check("document-reader", "PASS", f"paper {args.paper_id}"))
            except Exception as exc:
                checks.append(Check("document-reader", "FAIL", str(exc)))
                ok = False

        if args.worker_run_id:
            try:
                run_response = client.get(f"/api/research/runs/{args.worker_run_id}", headers=headers)
                _check_http(run_response, 200)
                payload = run_response.json().get("run", {})
                state = payload.get("execution_state")
                if state not in {"COMPLETED", "FAILED", "CANCELLED"}:
                    raise RuntimeError(f"run is not terminal: {state}")
                checks.append(Check("durable-worker", "PASS", f"{args.worker_run_id}: {state}"))
            except Exception as exc:
                checks.append(Check("durable-worker", "FAIL", str(exc)))
                ok = False

        if not args.skip_ollama:
            try:
                ollama_url = args.ollama_url.rstrip("/")
                tags = client.get(f"{ollama_url}/api/tags")
                _check_http(tags, 200)
                names = _model_names(tags.json())
                if not _has_model(names, args.generation_model):
                    raise RuntimeError(f"generation model missing: {args.generation_model}")
                if not _has_model(names, args.embedding_model):
                    raise RuntimeError(f"embedding model missing: {args.embedding_model}")
                embed = client.post(
                    f"{ollama_url}/api/embed",
                    json={"model": args.embedding_model, "input": "PaperLens Phase 16 smoke"},
                )
                _check_http(embed, 200)
                vectors = embed.json().get("embeddings", [])
                if not vectors or not vectors[0]:
                    raise RuntimeError("Ollama returned no embedding vector")
                chat = client.post(
                    f"{ollama_url}/api/chat",
                    json={
                        "model": args.generation_model,
                        "messages": [{"role": "user", "content": "Reply with exactly OK."}],
                        "stream": False,
                        "think": False,
                    },
                )
                _check_http(chat, 200)
                if not chat.json().get("message", {}).get("content"):
                    raise RuntimeError("Ollama returned no generation content")
                checks.append(
                    Check(
                        "ollama-local-inference",
                        "PASS",
                        f"generation={args.generation_model}; embedding={args.embedding_model}; external=0",
                    )
                )
            except Exception as exc:
                checks.append(Check("ollama-local-inference", "FAIL", str(exc)))
                ok = False

    return checks, ok


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--origin", default="http://127.0.0.1:13000")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--paper-id")
    parser.add_argument("--worker-run-id")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--generation-model", default="qwen3:4b")
    parser.add_argument("--embedding-model", default="nomic-embed-text")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--skip-ollama", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    checks, ok = run(build_parser().parse_args(argv))
    print(json.dumps({"ok": ok, "checks": [check.as_dict() for check in checks]}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
