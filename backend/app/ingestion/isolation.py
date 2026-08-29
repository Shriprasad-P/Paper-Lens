"""Isolated, bounded execution for untrusted PDF parsing.

The parent process performs only cheap file checks and supervises a short-lived
child.  The child owns every native PyMuPDF call and returns a serialized,
parser-neutral result; it never receives authentication or database context.
"""

from __future__ import annotations

import asyncio
import math
import multiprocessing
import pickle
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

try:  # resource is Unix-only; byte/page/text/time controls remain portable.
    import resource
except ImportError:  # pragma: no cover - exercised on Windows only.
    resource = None  # type: ignore[assignment]

from .errors import (
    PaperParseError,
    PdfMalformedError,
    PdfMemoryLimitError,
    PdfParseFailedError,
    PdfParseTimeoutError,
    PdfTooLargeError,
)
from .parser import PaperParser, PyMuPDFPaperParser
from .raw import ParsedPaper
from ..models.paper import ParsedSection


def _apply_child_limits(*, memory_limit_bytes: int | None, cpu_limit_seconds: float | None) -> None:
    """Apply best-effort Unix child limits without making macOS startup brittle."""

    if resource is not None and memory_limit_bytes and hasattr(resource, "RLIMIT_AS"):
        try:
            resource.setrlimit(resource.RLIMIT_AS, (int(memory_limit_bytes), int(memory_limit_bytes)))
        except (OSError, ValueError):
            # macOS may reject RLIMIT_AS for an already mapped interpreter.  The
            # parent still enforces byte/page/text/time budgets and process kill.
            pass
    if resource is not None and cpu_limit_seconds and hasattr(resource, "RLIMIT_CPU"):
        try:
            seconds = max(1, int(math.ceil(cpu_limit_seconds)))
            resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds))
        except (OSError, ValueError):
            pass


def _child_parse(
    file_path: str,
    parser: PaperParser,
    memory_limit_bytes: int | None,
    cpu_limit_seconds: float | None,
    connection: Any,
) -> None:
    """Run one parser pass and send only safe structured data to the parent."""

    try:
        _apply_child_limits(memory_limit_bytes=memory_limit_bytes, cpu_limit_seconds=cpu_limit_seconds)
        parse_document = getattr(parser, "parse_document", None)
        if callable(parse_document):
            parsed = asyncio.run(parse_document(file_path))
        else:
            sections = asyncio.run(parser.parse(file_path))
            parsed = ParsedPaper.from_legacy_sections(sections, parser_name=parser.__class__.__name__)
        if not isinstance(parsed, ParsedPaper):
            parsed = ParsedPaper.from_legacy_sections(parsed, parser_name=parser.__class__.__name__)
        connection.send({"ok": True, "payload": parsed.model_dump(mode="json")})
    except PaperParseError as exc:
        connection.send({"ok": False, "code": getattr(exc, "code", "PDF_PARSE_FAILED")})
    except MemoryError:
        connection.send({"ok": False, "code": "PDF_MEMORY_LIMIT"})
    except BaseException:
        # Never serialize native exception strings or traceback content.
        try:
            connection.send({"ok": False, "code": "PDF_PARSE_FAILED"})
        except Exception:
            pass
    finally:
        try:
            connection.close()
        except Exception:
            pass


class IsolatedPaperParser(PaperParser):
    """Run a parser in a bounded, short-lived child process."""

    def __init__(
        self,
        parser: PaperParser | None = None,
        *,
        max_bytes: int = 50 * 1024 * 1024,
        max_page_count: int = 500,
        max_text_chars: int = 5_000_000,
        max_text_chars_per_page: int | None = None,
        max_images_per_page: int = 100,
        max_total_images: int = 1_000,
        timeout_seconds: float = 120.0,
        memory_limit_bytes: int | None = None,
        cpu_limit_seconds: float | None = None,
        concurrency: int = 2,
    ) -> None:
        self.max_bytes = max(1, int(max_bytes))
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.memory_limit_bytes = memory_limit_bytes
        self.cpu_limit_seconds = cpu_limit_seconds
        self._gate = asyncio.Semaphore(max(1, int(concurrency)))
        self.active_processes = 0
        self.max_active_processes = 0
        self.metrics: Counter[str] = Counter()
        if parser is None:
            parser = PyMuPDFPaperParser(
                max_page_count=max_page_count,
                max_text_chars=max_text_chars,
                max_text_chars_per_page=max_text_chars_per_page,
                max_images_per_page=max_images_per_page,
                max_total_images=max_total_images,
            )
        self.parser = parser

    async def parse(self, file_path: str | Path) -> list[ParsedSection]:
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
        path = Path(file_path)
        self.metrics["started"] += 1
        started = time.perf_counter()
        try:
            try:
                size = path.stat().st_size
            except OSError as exc:
                self.metrics["process_failed"] += 1
                raise PdfParseFailedError("The paper could not be parsed safely.") from exc
            if size > self.max_bytes:
                self.metrics["byte_limit_rejected"] += 1
                raise PdfTooLargeError("The paper exceeds the configured size limit.")
            try:
                with path.open("rb") as source:
                    magic = source.read(5)
            except OSError as exc:
                self.metrics["process_failed"] += 1
                raise PdfParseFailedError("The paper could not be parsed safely.") from exc
            if magic != b"%PDF-":
                raise PdfMalformedError("The paper could not be parsed safely.")

            async with self._gate:
                self.active_processes += 1
                self.max_active_processes = max(self.max_active_processes, self.active_processes)
                try:
                    parsed = await self._run_child(path)
                finally:
                    self.active_processes -= 1
            self.metrics["completed"] += 1
            return parsed
        except PaperParseError as exc:
            self.metrics["rejected"] += 1
            if getattr(exc, "code", "") == "PDF_TOO_MANY_PAGES":
                self.metrics["page_limit_rejected"] += 1
            elif getattr(exc, "code", "") == "PDF_TEXT_LIMIT_EXCEEDED":
                self.metrics["text_limit_rejected"] += 1
            elif getattr(exc, "code", "") == "PDF_IMAGE_LIMIT_EXCEEDED":
                self.metrics["image_limit_rejected"] += 1
            elif getattr(exc, "code", "") == "PDF_PARSE_TIMEOUT":
                self.metrics["timeouts"] += 1
            raise
        finally:
            self.metrics["duration_ms_total"] += int((time.perf_counter() - started) * 1000)

    async def _run_child(self, path: Path) -> ParsedPaper:
        method = _preferred_start_method(self.parser)
        context = multiprocessing.get_context(method)
        parent, child = context.Pipe(duplex=False)
        process = context.Process(
            target=_child_parse,
            args=(str(path), self.parser, self.memory_limit_bytes, self.cpu_limit_seconds, child),
            name="paperlens-pdf-parser",
        )
        try:
            process.start()
            child.close()
        except Exception as exc:
            parent.close()
            try:
                child.close()
            except Exception:
                pass
            self.metrics["process_failed"] += 1
            raise PdfParseFailedError("The paper parser process could not be started.") from exc

        deadline = time.monotonic() + self.timeout_seconds
        result: dict[str, Any] | None = None
        try:
            while process.is_alive() or parent.poll():
                if parent.poll():
                    try:
                        result = parent.recv()
                    except (EOFError, OSError):
                        result = None
                    break
                if time.monotonic() >= deadline:
                    await self._terminate(process)
                    raise PdfParseTimeoutError("The paper parser exceeded its time limit.")
                await asyncio.sleep(0.02)

            if result is None:
                await asyncio.to_thread(process.join, 0.2)
                self.metrics["process_failed"] += 1
                if process.exitcode in {-9, 137}:
                    raise PdfMemoryLimitError("The paper parser exceeded its memory limit.")
                raise PdfParseFailedError("The paper parser process failed safely.")
            if not result.get("ok"):
                raise _error_from_code(str(result.get("code", "PDF_PARSE_FAILED")))
            try:
                return ParsedPaper.model_validate(result["payload"])
            except Exception as exc:
                self.metrics["process_failed"] += 1
                raise PdfParseFailedError("The paper parser returned an invalid result.") from exc
        except asyncio.CancelledError:
            await self._terminate(process)
            self.metrics["process_failed"] += 1
            raise
        finally:
            if process.is_alive():
                await self._terminate(process)
            else:
                await asyncio.to_thread(process.join, 0.2)
            parent.close()

    async def _terminate(self, process: multiprocessing.Process) -> None:
        if not process.is_alive():
            await asyncio.to_thread(process.join, 0.2)
            return
        process.terminate()
        await asyncio.to_thread(process.join, 0.3)
        if process.is_alive() and hasattr(process, "kill"):
            process.kill()
            await asyncio.to_thread(process.join, 0.3)


def _error_from_code(code: str) -> PaperParseError:
    from .errors import (
        PdfImageLimitError,
        PdfMalformedError,
        PdfMemoryLimitError,
        PdfParseTimeoutError,
        PdfTooManyPagesError,
        PdfTextLimitError,
        PdfUnsupportedError,
    )

    errors: dict[str, type[PaperParseError]] = {
        "PDF_MALFORMED": PdfMalformedError,
        "PDF_TOO_MANY_PAGES": PdfTooManyPagesError,
        "PDF_TEXT_LIMIT_EXCEEDED": PdfTextLimitError,
        "PDF_IMAGE_LIMIT_EXCEEDED": PdfImageLimitError,
        "PDF_PARSE_TIMEOUT": PdfParseTimeoutError,
        "PDF_MEMORY_LIMIT": PdfMemoryLimitError,
        "PDF_UNSUPPORTED": PdfUnsupportedError,
        "PDF_PARSE_FAILED": PdfParseFailedError,
    }
    error_type = errors.get(code, PdfParseFailedError)
    return error_type("The paper could not be parsed safely.")


def _preferred_start_method(parser: object) -> str:
    """Prefer spawn for production-safe defaults; fork only for test adapters
    that intentionally use a local, non-picklable parser object."""

    methods = multiprocessing.get_all_start_methods()
    if "spawn" in methods:
        main_file = getattr(sys.modules.get("__main__"), "__file__", "")
        if (getattr(sys, "frozen", False) or not main_file or str(main_file).startswith("<")) and "fork" in methods:
            return "fork"
        try:
            pickle.dumps(parser)
            return "spawn"
        except Exception:
            if "fork" in methods:
                return "fork"
        return "spawn"
    return "fork" if "fork" in methods else methods[0]
