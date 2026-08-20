"""Safe deterministic local PDF storage."""

from __future__ import annotations

import re
from pathlib import Path

_SAFE_PART = re.compile(r"[^A-Za-z0-9._-]+")


class PaperStorage:
    def __init__(self, root: str | Path = "data/papers") -> None:
        self.root = Path(root)

    def save_pdf(self, paper_id: str, content: bytes) -> Path:
        """Store bytes using a fixed filename under a sanitized paper directory."""

        safe_id = _SAFE_PART.sub("_", paper_id).strip("._") or "paper"
        destination = self.root / safe_id / "source.pdf"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return destination
