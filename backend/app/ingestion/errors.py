"""Application errors raised by the ingestion pipeline."""

from __future__ import annotations


class IngestionError(Exception):
    """Base class for expected, user-safe ingestion failures."""


class InvalidArxivIdentifierError(IngestionError):
    """The supplied input is not a supported arXiv identifier or URL."""


class ArxivMetadataError(IngestionError):
    """Metadata could not be retrieved or interpreted."""


class ArxivNotFoundError(ArxivMetadataError):
    """arXiv returned no matching paper."""


class PdfDownloadError(IngestionError):
    """The paper PDF could not be safely downloaded."""


class PdfValidationError(PdfDownloadError):
    """The response was not a usable PDF."""

    code = "PDF_MALFORMED"


class PaperParseError(IngestionError):
    """The downloaded paper could not be parsed reliably."""

    code = "PDF_PARSE_FAILED"


class PdfTooLargeError(PdfValidationError):
    """The PDF exceeded the streamed byte budget."""

    code = "PDF_TOO_LARGE"


class PdfMalformedError(PdfValidationError):
    """The bytes do not represent a usable PDF."""

    code = "PDF_MALFORMED"


class PdfTooManyPagesError(PaperParseError):
    """The PDF exceeded the page budget before traversal."""

    code = "PDF_TOO_MANY_PAGES"


class PdfTextLimitError(PaperParseError):
    """Incremental page extraction exceeded the text budget."""

    code = "PDF_TEXT_LIMIT_EXCEEDED"


class PdfImageLimitError(PaperParseError):
    """Embedded image work exceeded the configured budget."""

    code = "PDF_IMAGE_LIMIT_EXCEEDED"


class PdfParseTimeoutError(PaperParseError):
    """The isolated parser exceeded its wall-clock budget."""

    code = "PDF_PARSE_TIMEOUT"


class PdfMemoryLimitError(PaperParseError):
    """The parser child hit its memory budget."""

    code = "PDF_MEMORY_LIMIT"


class PdfUnsupportedError(PaperParseError):
    """The parser cannot safely process this PDF variant."""

    code = "PDF_UNSUPPORTED"


class PdfParseFailedError(PaperParseError):
    """The isolated parser failed without exposing native details."""

    code = "PDF_PARSE_FAILED"


class PaperPersistenceError(IngestionError):
    """The normalized paper could not be persisted."""
