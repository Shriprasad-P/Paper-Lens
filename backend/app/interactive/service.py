"""Staged InteractivePaper generation through the existing AIProvider."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from ..ai.provider import AIProvider, AIProviderError
from ..core.config import Settings
from ..db.database import SQLDatabase
from ..models.document import Evidence
from ..models.interactive_paper import (
    BlockSimplification,
    BlockStatus,
    GenerationMode,
    INTERACTIVE_PROMPT_VERSION,
    INTERACTIVE_SCHEMA_VERSION,
    InteractivePaper,
    InteractivePaperBlock,
    ValidatorStatus,
)
from .assembler import analysis_fingerprint, assemble_interactive_paper, interactive_cache_key
from .validator import validate_paper
from ..extraction.vlm import analyze_figures_from_pdf


class InteractivePaperError(Exception):
    """Expected interactive-paper orchestration failure."""


class InteractivePaperService:
    PROMPT_VERSION = INTERACTIVE_PROMPT_VERSION
    SCHEMA_VERSION = INTERACTIVE_SCHEMA_VERSION

    def __init__(
        self,
        database: SQLDatabase,
        provider: AIProvider,
        *,
        settings: Settings | None = None,
        prompt_dir: Path | None = None,
    ) -> None:
        self.database = database
        self.provider = provider
        self.settings = settings or Settings.from_env()
        self.prompt_dir = prompt_dir or Path(__file__).parents[1] / "prompts"

    def current(self, paper_id: str, owner_id: str = "user_legacy_local") -> InteractivePaper | None:
        document = self.database.get_document(paper_id, owner_id)
        if document is None:
            return None
        analysis_record = self.database.get_analysis_record(paper_id, owner_id)
        analysis = analysis_record[0] if analysis_record else None
        fingerprint = analysis_fingerprint(analysis)
        cached = self.database.get_interactive_paper_record(paper_id, owner_id)
        if cached is None:
            return None
        paper, _cache_key = cached
        if (
            paper.document_hash != document.document_hash
            or paper.source_hash != document.source_hash
            or paper.analysis_fingerprint != fingerprint
            or paper.schema_version != self.SCHEMA_VERSION
        ):
            return None
        return paper

    async def get_or_assemble(self, paper_id: str, owner_id: str = "user_legacy_local") -> InteractivePaper:
        current = self.current(paper_id, owner_id)
        if current is not None:
            return current
        return await self.generate(paper_id, owner_id, simplify=False)

    async def generate(self, paper_id: str, owner_id: str = "user_legacy_local", *, simplify: bool = True) -> InteractivePaper:
        document = self.database.get_document(paper_id, owner_id)
        if document is None:
            raise InteractivePaperError("Structured document not found.")
        analysis_record = self.database.get_analysis_record(paper_id, owner_id)
        analysis = analysis_record[0] if analysis_record else None
        evidence = self.database.get_evidence_for_document(paper_id, document.id, owner_id)
        available_ids = {item.id for item in evidence}
        fingerprint = analysis_fingerprint(analysis)
        provider_name = self.settings.ai_provider
        model_name = getattr(self.provider, "model", self.settings.ai_model)
        mode = GenerationMode.SIMPLIFIED if simplify else GenerationMode.ASSEMBLER
        cache_key = interactive_cache_key(
            owner_id=owner_id,
            paper_id=paper_id,
            document_hash=document.document_hash,
            source_hash=document.source_hash,
            analysis_fingerprint_value=fingerprint,
            schema_version=self.SCHEMA_VERSION,
            prompt_version=self.PROMPT_VERSION,
            provider=provider_name,
            model=model_name,
            generation_mode=mode,
            embedding_model=self.settings.embedding_model,
            vlm_model=self.settings.vlm_model if self.settings.vlm_enabled else None,
        )
        cached = self.database.get_interactive_paper_record(paper_id, owner_id)
        if cached is not None and cached[1] == cache_key:
            return cached[0]
        visual_analyses = {}
        if self.settings.vlm_enabled:
            source = self.database.get_source_pdf_path(paper_id, owner_id)
            root = Path(self.settings.paper_storage_path).expanduser().resolve()
            if source is not None:
                source = source.expanduser().resolve()
                if source.is_file() and source.is_relative_to(root):
                    try:
                        visual_analyses = await analyze_figures_from_pdf(
                            document,
                            source,
                            model=self.settings.vlm_model,
                            python=self.settings.vlm_python,
                            max_figures=self.settings.vlm_max_visuals,
                        )
                    except Exception:
                        visual_analyses = {}
        paper = assemble_interactive_paper(
            document,
            analysis,
            available_ids=available_ids,
            cache_key=cache_key,
            provider=provider_name,
            model=model_name,
            generation_mode=mode,
            visual_analyses=visual_analyses,
        )
        self.database.save_interactive_paper(paper, owner_id=owner_id)
        if not simplify:
            return paper
        paper = await self._simplify_blocks(paper, evidence, available_ids, owner_id)
        paper = validate_paper(
            paper,
            available_ids=available_ids,
            figure_ids={figure.id for figure in document.figures},
            table_ids={table.id for table in document.tables},
        )
        self.database.save_interactive_paper(paper, owner_id=owner_id)
        return paper

    async def _simplify_blocks(
        self,
        paper: InteractivePaper,
        evidence: list[Evidence],
        available_ids: set[str],
        owner_id: str,
    ) -> InteractivePaper:
        prompt_path = self.prompt_dir / "block_simplifier.md"
        system_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
        by_id = {item.id: item for item in evidence}
        blocks: list[InteractivePaperBlock] = []
        for block in paper.blocks:
            if block.status != BlockStatus.READY or not block.simplified_explanation:
                blocks.append(block)
                continue
            generating = paper.model_copy(update={"blocks": [*blocks, block.model_copy(update={"status": BlockStatus.GENERATING}), *paper.blocks[len(blocks) + 1 :]]})
            self.database.save_interactive_paper(generating, owner_id=owner_id)
            try:
                payload = await self.provider.generate_structured(
                    (
                        f"{system_prompt}\n\nBLOCK TYPE: {block.type.value}\nTITLE: {block.title}\n"
                        f"CURRENT TEXT:\n{block.simplified_explanation}\n\n"
                        f"SUPPLIED EVIDENCE IDS: {', '.join(block.evidence_ids)}\n"
                        f"EVIDENCE:\n{_evidence_snippet(block.evidence_ids, by_id)}\n"
                    ),
                    BlockSimplification,
                )
                valid_ids = [item for item in payload.evidence_ids if item in available_ids] or block.evidence_ids
                updated = block.model_copy(
                    update={
                        "simplified_explanation": payload.simplified_explanation,
                        "key_points": payload.key_points or block.key_points,
                        "evidence_ids": valid_ids,
                        "inferred": payload.inferred or block.inferred,
                        "status": BlockStatus.READY,
                        "validator_status": ValidatorStatus.PASSED,
                        "error": None,
                    }
                )
            except (AIProviderError, ValidationError, ValueError, TypeError):
                updated = block
            blocks.append(updated)
            paper = paper.model_copy(update={"blocks": [*blocks, *paper.blocks[len(blocks) :]], "status": BlockStatus.READY})
            self.database.save_interactive_paper(paper, owner_id=owner_id)
        return paper.model_copy(update={"blocks": blocks, "status": BlockStatus.READY})


def _evidence_snippet(evidence_ids: list[str], by_id: dict[str, Evidence], *, limit: int = 6, chars: int = 1800) -> str:
    parts: list[str] = []
    used = 0
    for evidence_id in evidence_ids[:limit]:
        record = by_id.get(evidence_id)
        if record is None:
            continue
        chunk = f"[{record.id} p.{record.page or '?'}] {record.source_text[:400]}"
        if used + len(chunk) > chars:
            break
        parts.append(chunk)
        used += len(chunk)
    return "\n".join(parts)
