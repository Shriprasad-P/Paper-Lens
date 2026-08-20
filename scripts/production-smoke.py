#!/usr/bin/env python3
"""Bounded deployment smoke checks; never invokes AI providers."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def get(url: str) -> tuple[int, dict[str, object] | None]:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            body = response.read().decode("utf-8")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = None
            return response.status, payload
    except urllib.error.HTTPError as exc:
        return exc.code, None


def main() -> int:
    backend = os.getenv("PAPERLENS_BACKEND_URL", "http://localhost:8000").rstrip("/")
    frontend = os.getenv("PAPERLENS_FRONTEND_URL", "http://localhost:3000").rstrip("/")
    checks = [("frontend", frontend + "/"), ("live", backend + "/health/live"), ("ready", backend + "/health/ready"), ("version", backend + "/health/version"), ("capabilities", backend + "/api/capabilities")]
    failed = False
    for name, url in checks:
        status, payload = get(url)
        ok = 200 <= status < 300
        print(json.dumps({"check": name, "url": url, "status": status, "ok": ok, "payload": payload}, sort_keys=True))
        failed |= not ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
