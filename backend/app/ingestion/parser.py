"""Paper parser interface and a lightweight PyMuPDF implementation."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path

from ..models.document import SourceRegion
from ..models.document import PaperEquation, PaperFigure, PaperReference, PaperTable
from ..models.paper import ParsedSection
from .errors import (
    PaperParseError,
    PdfImageLimitError,
    PdfMalformedError,
    PdfTextLimitError,
    PdfTooManyPagesError,
)
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
    """Extract a paper in one bounded, page-by-page traversal.

    The parser is deliberately synchronous internally.  ``IsolatedPaperParser``
    runs it in a fresh child process, so native traversal never executes in the
    FastAPI event loop or shares its address space.
    """

    def __init__(
        self,
        *,
        max_page_count: int = 500,
        max_text_chars: int = 5_000_000,
        max_text_chars_per_page: int | None = None,
        max_images_per_page: int = 100,
        max_total_images: int = 1_000,
    ) -> None:
        self.max_page_count = max(1, int(max_page_count))
        self.max_text_chars = max(1, int(max_text_chars))
        self.max_text_chars_per_page = max_text_chars_per_page
        self.max_images_per_page = max(0, int(max_images_per_page))
        self.max_total_images = max(0, int(max_total_images))

    async def parse(self, file_path: str | Path) -> list[ParsedSection]:
        """Legacy section API backed by the same single parse pass."""

        parsed = await self.parse_document(file_path)
        return [
            ParsedSection(
                title=section.title,
                order=section.order,
                text="\n".join(paragraph.text for paragraph in section.paragraphs),
            )
            for section in parsed.sections
            if section.paragraphs
        ]

    async def parse_document(self, file_path: str | Path) -> ParsedPaper:
        """Parse metadata, text, and source artifacts in one traversal."""

        try:
            import pymupdf

            document = pymupdf.open(str(file_path))
            try:
                page_count = len(document)
                if page_count > self.max_page_count:
                    raise PdfTooManyPagesError("The paper exceeds the configured page-count limit.")

                sections: list[RawSection] = [RawSection(title="Document", level=1, order=0)]
                current = sections[0]
                figures: list[PaperFigure] = []
                tables: list[PaperTable] = []
                equations: list[PaperEquation] = []
                total_chars = 0
                total_images = 0

                for page_number, page in enumerate(document, start=1):
                    page_chars = 0
                    # We do not decode embedded images.  Counting xrefs is cheap
                    # and bounds future image work without creating raster bytes.
                    image_count = len(page.get_images(full=True))
                    if self.max_images_per_page and image_count > self.max_images_per_page:
                        raise PdfImageLimitError("The paper exceeds the configured per-page image limit.")
                    total_images += image_count
                    if self.max_total_images and total_images > self.max_total_images:
                        raise PdfImageLimitError("The paper exceeds the configured image limit.")

                    blocks = page.get_text("blocks", sort=True)
                    for block in blocks:
                        if len(block) < 7 or block[6] != 0:
                            continue
                        raw_text = str(block[4] or "")
                        text = _clean_block(raw_text)
                        if not text:
                            continue
                        page_chars += len(text)
                        total_chars += len(text)
                        if self.max_text_chars_per_page and page_chars > self.max_text_chars_per_page:
                            raise PdfTextLimitError("The paper exceeds the configured per-page text limit.")
                        if total_chars > self.max_text_chars:
                            raise PdfTextLimitError("The paper exceeds the configured extracted-text limit.")
                        region = _region(page_number, block)
                        pending: list[str] = []

                        def flush_paragraph() -> None:
                            paragraph_text = _clean_block(" ".join(pending))
                            if paragraph_text:
                                current.paragraphs.append(
                                    RawParagraph(text=paragraph_text, page=page_number, source_region=region)
                                )
                                current.page_start = current.page_start or page_number
                                current.page_end = page_number
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
                                    page_start=page_number,
                                    page_end=page_number,
                                )
                                sections.append(current)
                            else:
                                pending.append(line)
                        flush_paragraph()

                        figure_match = _FIGURE_CAPTION.match(text)
                        if figure_match:
                            number = figure_match.group("number")
                            figures.append(
                                PaperFigure(
                                    id=f"figure_{len(figures) + 1:03d}",
                                    label=f"Figure {number}",
                                    number=number,
                                    caption=figure_match.group("caption") or None,
                                    page=page_number,
                                    source_region=region,
                                )
                            )
                        else:
                            table_match = _TABLE_CAPTION.match(text)
                            if table_match:
                                number = table_match.group("number")
                                headers, rows = _parse_table_rows(raw_text)
                                tables.append(
                                    PaperTable(
                                        id=f"table_{len(tables) + 1:03d}",
                                        label=f"Table {number}",
                                        number=number,
                                        caption=table_match.group("caption") or None,
                                        page=page_number,
                                        raw_text=text,
                                        headers=headers,
                                        rows=rows,
                                        source_region=region,
                                    )
                                )
                            elif _looks_like_equation(text):
                                label_match = _EQUATION_LABEL.search(text)
                                label = (label_match.group("paren") or label_match.group("bracket")) if label_match else None
                                expression = _EQUATION_LABEL.sub("", text).strip()
                                equations.append(
                                    PaperEquation(
                                        id=f"equation_{len(equations) + 1:03d}",
                                        raw_text=expression,
                                        label=label,
                                        page=page_number,
                                        source_region=region,
                                    )
                                )

                sections = [section for section in sections if section.paragraphs or section.title != "Document"]
                references = _references_from_sections(sections)
            finally:
                document.close()
        except PaperParseError:
            raise
        except Exception as exc:  # PyMuPDF exposes several parser-specific errors.
            raise PdfMalformedError("The paper could not be parsed safely.") from exc

        if not any(section.paragraphs for section in sections):
            raise PdfMalformedError("The paper could not be parsed safely.")
        return ParsedPaper(
            sections=sections,
            page_count=page_count,
            parser_name="pymupdf",
            parser_version=getattr(pymupdf, "__version__", None),
            figures=figures,
            tables=tables,
            equations=equations,
            references=references,
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


_FIGURE_CAPTION = re.compile(r"^(?:figure|fig\.?)[\s._-]*(?P<number>[A-Za-z]?\d+[A-Za-z]?)\s*[:.)-]?\s*(?P<caption>.*)$", re.IGNORECASE)
_TABLE_CAPTION = re.compile(r"^table[\s._-]*(?P<number>[A-Za-z]?\d+[A-Za-z]?)\s*[:.)-]?\s*(?P<caption>.*)$", re.IGNORECASE)
_EQUATION_LABEL = re.compile(r"(?:\((?P<paren>\d+(?:\.\d+)*)\)|\[(?P<bracket>\d+(?:\.\d+)*)\])\s*$")
_ARXIV_RE = re.compile(r"(?<!\d)(\d{4}\.\d{4,5})(?:v\d+)?\b", re.IGNORECASE)
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s)]+", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def _looks_like_equation(text: str) -> bool:
    if len(text) > 240 or "=" not in text:
        return False
    if _URL_RE.search(text) or text.lower().startswith(("http", "where ", "email ")):
        return False
    return bool(re.search(r"[A-Za-z]\s*=|=\s*[A-Za-z0-9(]", text))


def _parse_table_rows(text: str) -> tuple[list[str], list[list[str]]]:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) < 2:
        return [], []
    rows: list[list[str]] = []
    for line in lines[1:]:
        delimiter = "|" if "|" in line else "\t" if "\t" in line else None
        if delimiter is None:
            return [], []
        cells = [cell.strip() for cell in line.split(delimiter)]
        if len(cells) < 2:
            return [], []
        rows.append(cells)
    header_delimiter = "|" if "|" in lines[0] else "\t" if "\t" in lines[0] else None
    headers = [cell.strip() for cell in lines[0].split(header_delimiter)] if header_delimiter else []
    return (headers if len(headers) >= 2 else []), rows


def _references_from_sections(sections: list[RawSection]) -> list[PaperReference]:
    references: list[PaperReference] = []
    in_references = False
    for section in sections:
        title = section.title.lower()
        if "reference" in title or "bibliograph" in title:
            in_references = True
        if not in_references:
            continue
        for paragraph in section.paragraphs:
            raw = paragraph.text.strip()
            if not raw:
                continue
            arxiv_match = _ARXIV_RE.search(raw)
            doi_match = _DOI_RE.search(raw)
            url_match = _URL_RE.search(raw)
            year_match = _YEAR_RE.search(raw)
            references.append(PaperReference(id=f"reference_{len(references) + 1:03d}", order=len(references), raw_text=raw, year=int(year_match.group(0)) if year_match else None, doi=doi_match.group(0).rstrip(".,") if doi_match else None, arxiv_id=arxiv_match.group(1) if arxiv_match else None, url=url_match.group(0).rstrip(".,") if url_match else None))
    return references
