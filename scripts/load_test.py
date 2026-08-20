#!/usr/bin/env python3
"""Small, dependency-free beta load probe for cheap read-only endpoints."""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def one(url: str) -> tuple[float, bool]:
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            response.read()
            ok = 200 <= response.status < 300
    except (OSError, urllib.error.HTTPError):
        ok = False
    return (time.perf_counter() - started) * 1000, ok


def percentile(values: list[float], fraction: float) -> float:
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * fraction))]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--path", action="append", default=None)
    parser.add_argument("--requests", type=int, default=40)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    if args.requests <= 0 or args.concurrency <= 0 or args.requests > 500:
        parser.error("requests must be 1..500 and concurrency must be positive")
    paths = args.path or ["/health/live", "/health/ready"]
    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for path in paths:
            samples = list(pool.map(lambda _: one(args.base_url.rstrip("/") + path), range(args.requests)))
            durations = [duration for duration, _ in samples]
            errors = sum(not ok for _, ok in samples)
            results.append({"path": path, "concurrency": args.concurrency, "requests": args.requests, "p50_ms": round(percentile(durations, 0.50), 3), "p95_ms": round(percentile(durations, 0.95), 3), "error_rate": round(errors / args.requests, 4)})
    print(json.dumps(results, indent=2, sort_keys=True))
    return 1 if any(item["error_rate"] for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
