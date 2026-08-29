from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

import pymupdf

from backend.app.ingestion.errors import (
    PaperParseError,
    PdfMalformedError,
    PdfParseFailedError,
    PdfParseTimeoutError,
    PdfTextLimitError,
    PdfTooLargeError,
    PdfTooManyPagesError,
)
from backend.app.ingestion.isolation import IsolatedPaperParser
from backend.app.ingestion.parser import PyMuPDFPaperParser
from backend.app.ingestion.raw import ParsedPaper, RawParagraph, RawSection


def _pdf(path: Path, pages: list[str]) -> None:
    document = pymupdf.open()
    for value in pages:
        page = document.new_page()
        page.insert_text((72, 72), value)
    document.save(path)
    document.close()


def _parsed() -> ParsedPaper:
    return ParsedPaper(
        parser_name="fixture",
        sections=[
            RawSection(
                title="Fixture",
                level=1,
                order=0,
                paragraphs=[RawParagraph(text="A bounded parser result.", page=1)],
            )
        ],
        page_count=1,
    )


class SlowParser:
    async def parse_document(self, file_path: str | Path) -> ParsedPaper:
        await asyncio.sleep(0.4)
        return _parsed()


class CrashParser:
    async def parse_document(self, file_path: str | Path) -> ParsedPaper:
        raise RuntimeError("native parser detail must stay private")


class Phase14IsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_signature_and_byte_limits_reject_before_child(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "random.bin"
            path.write_bytes(b"not a pdf")
            parser = IsolatedPaperParser(parser=SlowParser(), max_bytes=1_000)
            with self.assertRaises(PdfMalformedError):
                await parser.parse_document(path)
            self.assertEqual(parser.active_processes, 0)

            path.write_bytes(b"%PDF-" + b"x" * 20)
            limited = IsolatedPaperParser(parser=SlowParser(), max_bytes=10)
            with self.assertRaises(PdfTooLargeError):
                await limited.parse_document(path)
            self.assertEqual(limited.active_processes, 0)
            self.assertEqual(limited.metrics["completed"], 0)

    async def test_truncated_and_zero_page_documents_fail_safely(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            valid = Path(directory) / "valid.pdf"
            _pdf(valid, ["valid text"])
            truncated = Path(directory) / "truncated.pdf"
            truncated.write_bytes(valid.read_bytes()[:32])
            parser = IsolatedPaperParser(timeout_seconds=5)
            with self.assertRaises(PaperParseError):
                await parser.parse_document(truncated)

            empty = Path(directory) / "empty.pdf"
            empty.write_bytes(b"%PDF-1.4\n%%EOF\n")
            with self.assertRaises(PaperParseError):
                await parser.parse_document(empty)

    async def test_page_limit_precedes_text_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pages.pdf"
            _pdf(path, ["first page", "second page"])
            parser = IsolatedPaperParser(
                parser=PyMuPDFPaperParser(max_page_count=1),
                timeout_seconds=5,
            )
            with self.assertRaises(PdfTooManyPagesError):
                await parser.parse_document(path)

    async def test_text_budget_is_enforced_during_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "text.pdf"
            _pdf(path, ["a long first page with more than ten characters", "a second page"])
            parser = IsolatedPaperParser(
                parser=PyMuPDFPaperParser(max_text_chars=10),
                timeout_seconds=5,
            )
            with self.assertRaises(PdfTextLimitError):
                await parser.parse_document(path)

    async def test_timeout_terminates_child_and_crash_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.pdf"
            path.write_bytes(b"%PDF-1.7 fixture")
            parser = IsolatedPaperParser(parser=SlowParser(), timeout_seconds=0.05)
            with self.assertRaises(PdfParseTimeoutError):
                await parser.parse_document(path)
            self.assertEqual(parser.active_processes, 0)
            self.assertEqual(parser.metrics["timeouts"], 1)

            crashed = IsolatedPaperParser(parser=CrashParser(), timeout_seconds=2)
            with self.assertRaises(PdfParseFailedError):
                await crashed.parse_document(path)
            self.assertEqual(crashed.active_processes, 0)

            recovered = IsolatedPaperParser(parser=_FastParser(), timeout_seconds=2)
            result = await recovered.parse_document(path)
            self.assertEqual(result.parser_name, "fixture")

    async def test_cancellation_terminates_child(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.pdf"
            path.write_bytes(b"%PDF-1.7 fixture")
            parser = IsolatedPaperParser(parser=SlowParser(), timeout_seconds=5)
            task = asyncio.create_task(parser.parse_document(path))
            await asyncio.sleep(0.05)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(parser.active_processes, 0)

    async def test_parser_children_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.pdf"
            path.write_bytes(b"%PDF-1.7 fixture")
            parser = IsolatedPaperParser(parser=SlowParser(), timeout_seconds=5, concurrency=2)
            results = await asyncio.gather(*(parser.parse_document(path) for _ in range(6)))
            self.assertEqual(len(results), 6)
            self.assertLessEqual(parser.max_active_processes, 2)

    async def test_supervision_does_not_block_the_event_loop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.pdf"
            path.write_bytes(b"%PDF-1.7 fixture")
            parser = IsolatedPaperParser(parser=SlowParser(), timeout_seconds=5)
            task = asyncio.create_task(parser.parse_document(path))
            await asyncio.sleep(0.03)
            self.assertFalse(task.done())
            await task


class _FastParser:
    async def parse_document(self, file_path: str | Path) -> ParsedPaper:
        return _parsed()


if __name__ == "__main__":
    unittest.main()
