#!/usr/bin/env python3
"""Safe beta maintenance operations; destructive cleanup requires --apply."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.config import Settings
from backend.app.db.database import SQLDatabase


def cleanup_temp(root: Path, *, apply: bool) -> int:
    root = root.expanduser().resolve()
    if root == Path("/") or not root.exists() or not root.is_dir():
        raise SystemExit("refusing to clean an invalid storage root")
    candidates = [path for path in root.rglob("*.tmp") if path.is_file()]
    for path in candidates:
        print(f"{'remove' if apply else 'would-remove'} {path}")
        if apply:
            path.unlink(missing_ok=True)
    return len(candidates)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["recover", "cleanup-temp"])
    parser.add_argument("--apply", action="store_true", help="required for cleanup-temp deletion")
    args = parser.parse_args()
    settings = Settings.from_env()
    settings.validate()
    if args.command == "recover":
        database = SQLDatabase(settings.database_url, create_schema=settings.auto_create_schema, pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow, pool_timeout=settings.db_pool_timeout)
        print(database.recover_incomplete_work())
        return 0
    count = cleanup_temp(Path(settings.paper_storage_path), apply=args.apply)
    print(f"{'removed' if args.apply else 'found'} {count} temporary file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
