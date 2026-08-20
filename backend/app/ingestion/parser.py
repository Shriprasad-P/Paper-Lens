"""Paper parser interface and a lightweight PyMuPDF implementation."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path

from ..models.document import SourceRegion
from ..models.paper import ParsedSection
from .errors import PaperParseError
from .raw import ParsedPaper, RawParagraph, RawSection


class PaperParser(ABC):
    @abstractmethod
    async def parse(self, file_path: str | Path) -> list[ParsedSection]:
        """Parse a PDF into normalized sections."""

    async def parse_document(self, file_path: str | Path) -> ParsedPaper:
        """Return parser-neutral provenance when an adapter supports it."""

        sections = await self.parse(file_path)
        return ParsedPaper.from_legacy_sections(sections, parser_name=self.__class__.__name__)


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

    async def parse_document(self, file_path: str | Path) -> ParsedPaper:
        try:
            import pymupdf

            document = pymupdf.open(str(file_path))
            try:
                sections = _sections_from_pages(document)
                page_count = len(document)
            finally:
                document.close()
        except Exception as exc:  # PyMuPDF exposes several parser-specific errors.
            raise PaperParseError("The paper was retrieved, but its structure could not be extracted reliably.") from exc

        if not any(section.paragraphs for section in sections):
            raise PaperParseError("The paper was retrieved, but its structure could not be extracted reliably.")
        return ParsedPaper(
            sections=sections,
            page_count=page_count,
            parser_name="pymupdf",
            parser_version=getattr(pymupdf, "__version__", None),
        )


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


def _sections_from_pages(document: object) -> list[RawSection]:
    sections: list[RawSection] = []
    current = RawSection(title="Document", level=1, order=0)
    sections.append(current)

    for page_index, page in enumerate(document, start=1):
        blocks = page.get_text("blocks", sort=True)
        for block in blocks:
            if len(block) < 7 or block[6] != 0:
                continue
            raw_text = str(block[4] or "")
            region = _region(page_index, block)
            pending: list[str] = []

            def flush_paragraph() -> None:
                text = _clean_block(" ".join(pending))
                if text:
                    current.paragraphs.append(
                        RawParagraph(text=text, page=page_index, source_region=region)
                    )
                    current.page_start = current.page_start or page_index
                    current.page_end = page_index
                pending.clear()

            for raw_line in raw_text.splitlines():
                line = " ".join(raw_line.split()).strip()
                if not line:
                    flush_paragraph()
                    continue
                if _is_heading(line):
                    flush_paragraph()
                    current = RawSection(
                        title=line,
                        level=_heading_level(line),
                        order=len(sections),
                        page_start=page_index,
                        page_end=page_index,
                    )
                    sections.append(current)
                else:
                    pending.append(line)
            flush_paragraph()

    return [section for section in sections if section.paragraphs or section.title != "Document"]


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


def _region(page: int, block: tuple[object, ...]) -> SourceRegion:
    return SourceRegion(page=page, x0=float(block[0]), y0=float(block[1]), x1=float(block[2]), y1=float(block[3]))


def _heading_level(line: str) -> int:
    match = re.match(r"^(\d+(?:\.\d+)*)", line)
    return match.group(1).count(".") + 1 if match else 1


def _is_heading(line: str) -> bool:
    normalized = line.rstrip(":").strip().lower()
    if normalized in _KNOWN_HEADING:
        return True
    if len(line) > 110 or len(line.split()) > 14:
        return False
    return bool(_NUMBERED_HEADING.match(line))


def _clean_block(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
