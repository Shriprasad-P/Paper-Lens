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


class PaperParseError(IngestionError):
    """The downloaded paper could not be parsed reliably."""


class PaperPersistenceError(IngestionError):
    """The normalized paper could not be persisted."""
