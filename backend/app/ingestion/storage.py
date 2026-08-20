"""Safe deterministic paper storage boundary.

The beta ships with a durable local-volume provider. The service only depends on
this small interface, so a signed object-storage provider can be introduced by a
deployment adapter without changing ingestion or route semantics.
"""

from __future__ import annotations

import re
from typing import Protocol
from pathlib import Path

_SAFE_PART = re.compile(r"[^A-Za-z0-9._-]+")


class StorageProvider(Protocol):
    def save_pdf(self, paper_id: str, content: bytes) -> Path:
        """Persist source bytes and return an internal path for the parser."""

    def open(self, path: Path):
        """Open a stored object for a backend-authorized response."""

    def exists(self, path: Path) -> bool:
        """Return whether an object exists."""

    def delete(self, path: Path) -> None:
        """Delete one object during safe maintenance."""


class LocalStorage:
    def __init__(self, root: str | Path = "data/papers") -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def save_pdf(self, paper_id: str, content: bytes) -> Path:
        """Store bytes using a fixed filename under a sanitized paper directory."""

        safe_id = _safe_part(paper_id)
        destination = self.root / "papers" / safe_id / "source.pdf"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return destination

    def open(self, path: Path):
        return path.open("rb")

    def exists(self, path: Path) -> bool:
        return path.is_file()

    def delete(self, path: Path) -> None:
        path.unlink(missing_ok=True)


# Backwards-compatible name retained for Phase 1–11 imports and callers.
PaperStorage = LocalStorage


def _safe_part(value: str) -> str:
    return _SAFE_PART.sub("_", value).strip("._") or "paper"
