"""Ingest pinned local PDF snapshots through the Phase 14 production path.

The acquisition step is intentionally separate: PDFs are downloaded and
hashed into ``datasets/corpus/pdfs`` first, then this command feeds those exact
bytes through ``IngestionService`` (bounded fetch validation, isolated parser,
normalization, document persistence, and Evidence Registry construction).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

try:
    from app.core.config import Settings
    from app.db.database import SQLDatabase
    from app.ingestion.arxiv.client import ArxivClient
    from app.ingestion.parser import PyMuPDFPaperParser
    from app.ingestion.service import IngestionService
    from app.models.paper import PaperMetadata
except ModuleNotFoundError:  # pragma: no cover - repository-root imports
    from backend.app.core.config import Settings
    from backend.app.db.database import SQLDatabase
    from backend.app.ingestion.arxiv.client import ArxivClient
    from backend.app.ingestion.parser import PyMuPDFPaperParser
    from backend.app.ingestion.service import IngestionService
    from backend.app.models.paper import PaperMetadata


class LocalSnapshotClient(ArxivClient):
    """ArxivClient-compatible bounded fetcher for a previously hashed snapshot."""

    def __init__(self, rows: dict[str, dict[str, Any]], root: Path) -> None:
        super().__init__(timeout=1.0)
        self.rows = rows
        self.root = root

    async def fetch_metadata(self, identifier):
        row = self.rows[identifier.canonical_id]
        return PaperMetadata(
            arxiv_id=identifier.canonical_id,
            title=row["title"],
            authors=[],
            categories=row.get("arxiv_categories", []),
            source_url=row["source_url"],
            pdf_url=row["pdf_url"],
        )

    async def download_pdf(self, metadata: PaperMetadata, *, max_bytes: int) -> bytes:
        row = self.rows[metadata.arxiv_id]
        body = (self.root / row["pdf_path"]).read_bytes()
        if len(body) > max_bytes:
            raise ValueError("snapshot exceeds the configured byte limit")
        if not body.startswith(b"%PDF-"):
            raise ValueError("snapshot is not a PDF")
        return body


async def ingest_manifest(manifest_path: Path, database_url: str, storage_path: str, owner_id: str) -> dict[str, Any]:
    root = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = {row["versioned_identifier"]: row for row in manifest["papers"]}
    settings = replace(Settings.from_env(), database_url=database_url, paper_storage_path=storage_path)
    database = SQLDatabase(database_url, create_schema=True)
    parser = PyMuPDFPaperParser(
        max_page_count=settings.effective_pdf_max_pages,
        max_text_chars=settings.effective_pdf_max_text_chars,
        max_text_chars_per_page=settings.pdf_max_text_chars_per_page,
        max_images_per_page=settings.pdf_max_images_per_page,
        max_total_images=settings.pdf_max_total_images,
    )
    service = IngestionService(database, settings=settings, arxiv_client=LocalSnapshotClient(rows, root), parser=parser)
    results = []
    for row in manifest["papers"]:
        try:
            paper = await service.ingest(row["versioned_identifier"], owner_id=owner_id)
            document = database.get_document(paper.id, owner_id)
            evidence = database.get_evidence_for_document(paper.id, document.id, owner_id) if document else []
            results.append({"source_identifier": row["source_identifier"], "paper_id": paper.id, "document_id": document.id if document else None, "document_hash": document.document_hash if document else None, "source_hash": document.source_hash if document else None, "parser_version": document.parser_version if document else None, "evidence_count": len(evidence), "status": "COMPLETED"})
        except Exception as exc:  # noqa: BLE001 - preserve per-paper failure evidence
            results.append({"source_identifier": row["source_identifier"], "status": "FAILED", "error_type": type(exc).__name__, "error": str(exc)})
    return {"schema_version": "1.0", "corpus_hash": manifest.get("corpus_hash"), "owner_id": owner_id, "completed_count": sum(item["status"] == "COMPLETED" for item in results), "failed_count": sum(item["status"] != "COMPLETED" for item in results), "papers": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("backend/evaluation/datasets/corpus/manifest.json"))
    parser.add_argument("--database-url", default="sqlite:////tmp/paperlens-phase15-real.db")
    parser.add_argument("--storage-path", default="/tmp/paperlens-phase15-real-storage")
    parser.add_argument("--owner-id", default="user_legacy_local")
    parser.add_argument("--output", type=Path, default=Path("backend/evaluation/datasets/corpus/ingestion.json"))
    args = parser.parse_args()
    result = asyncio.run(ingest_manifest(args.manifest, args.database_url, args.storage_path, args.owner_id))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"completed_count": result["completed_count"], "failed_count": result["failed_count"]}, indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
