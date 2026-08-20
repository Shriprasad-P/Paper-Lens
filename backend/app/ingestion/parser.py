"""Paper parser interface and a lightweight PyMuPDF implementation."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path

from ..models.paper import ParsedSection
from .errors import PaperParseError


class PaperParser(ABC):
    @abstractmethod
    async def parse(self, file_path: str | Path) -> list[ParsedSection]:
        """Parse a PDF into normalized sections."""


class PyMuPDFPaperParser(PaperParser):
    """Extract page text and practical heading-based sections."""

    async def parse(self, file_path: str | Path) -> list[ParsedSection]:
        try:
            import pymupdf

            document = pymupdf.open(str(file_path))
            try:
                text = "\n".join(page.get_text("text") for page in document)
            finally:
                document.close()
        except Exception as exc:  # PyMuPDF exposes several parser-specific errors.
            raise PaperParseError("The paper was retrieved, but its structure could not be extracted reliably.") from exc

        if not text.strip():
            raise PaperParseError("The paper was retrieved, but its structure could not be extracted reliably.")
        return _sections_from_text(text)


_NUMBERED_HEADING = re.compile(r"^\d+(?:\.\d+)*[.)]?\s+\S.{1,100}$")
_KNOWN_HEADING = {
    "abstract",
    "introduction",
    "background",
    "related work",
    "method",
    "methods",
    "methodology",
    "experiments",
    "experimental results",
    "results",
    "discussion",
    "limitations",
    "conclusion",
    "conclusions",
    "references",
}


def _sections_from_text(text: str) -> list[ParsedSection]:
    sections: list[ParsedSection] = []
    current_title = "Document"
    current_lines: list[str] = []

    def flush() -> None:
        body = _clean_block("\n".join(current_lines))
        if body:
            sections.append(ParsedSection(title=current_title, order=len(sections), text=body))

    for raw_line in text.splitlines():
        line = " ".join(raw_line.split()).strip()
        if not line:
            continue
        if _is_heading(line):
            flush()
            current_title = line
            current_lines = []
        else:
            current_lines.append(line)
    flush()
    return sections


def _is_heading(line: str) -> bool:
    normalized = line.rstrip(":").strip().lower()
    if normalized in _KNOWN_HEADING:
        return True
    if len(line) > 110 or len(line.split()) > 14:
        return False
    return bool(_NUMBERED_HEADING.match(line))


def _clean_block(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
