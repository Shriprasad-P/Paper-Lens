"""Deterministic arXiv input normalization."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

from ..errors import InvalidArxivIdentifierError

_ARXIV_ID = r"(?P<identifier>\d{4}\.\d{4,5})(?P<version>v\d+)?"
_ID_RE = re.compile(rf"^{_ARXIV_ID}$", re.IGNORECASE)
_PATH_RE = re.compile(rf"^/(?:abs|pdf)/{_ARXIV_ID}(?:\.pdf)?/?$", re.IGNORECASE)


class ArxivIdentifier(BaseModel):
    """Canonical arXiv identity, with version kept separate when supplied."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    version: str | None = None

    @property
    def canonical_id(self) -> str:
        return f"{self.id}{self.version or ''}"

    @property
    def source_identity(self) -> str:
        return f"arxiv:{self.canonical_id}"


def normalize_arxiv_input(source: str) -> ArxivIdentifier:
    """Normalize a bare ID or an arXiv abs/pdf URL.

    Only arxiv.org and export.arxiv.org hosts are accepted. This keeps the
    ingestion downloader from becoming a generic user-controlled URL fetcher.
    """

    value = source.strip()
    if not value:
        raise InvalidArxivIdentifierError("Invalid arXiv identifier.")

    match = _ID_RE.fullmatch(value)
    if match:
        return _from_match(match)

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "arxiv.org",
        "www.arxiv.org",
        "export.arxiv.org",
    }:
        raise InvalidArxivIdentifierError("Invalid arXiv identifier.")

    path_match = _PATH_RE.fullmatch(parsed.path)
    if not path_match or parsed.query or parsed.fragment:
        raise InvalidArxivIdentifierError("Invalid arXiv identifier.")
    return _from_match(path_match)


def _from_match(match: re.Match[str]) -> ArxivIdentifier:
    version = match.group("version")
    return ArxivIdentifier(
        id=match.group("identifier"),
        version=version.lower() if version else None,
    )
