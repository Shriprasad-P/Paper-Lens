"""Add interactive_papers persistence for the unified reconstructed paper."""

from __future__ import annotations

from alembic import op
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, inspect

revision = "0004_phase17_interactive_paper"
down_revision = "0003_phase13b_durable_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "interactive_papers" in tables:
        return
    op.create_table(
        "interactive_papers",
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("paper_id", String(64), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, unique=True),
        Column("document_id", String(64), nullable=False),
        Column("document_hash", String(64), nullable=True),
        Column("source_hash", String(64), nullable=True),
        Column("provider", String(64), nullable=True),
        Column("model", String(128), nullable=True),
        Column("prompt_version", String(32), nullable=False),
        Column("schema_version", String(32), nullable=False),
        Column("cache_key", String(128), nullable=False, unique=True),
        Column("payload", JSON, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=True),
        Column("updated_at", DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_interactive_papers_paper_id", "interactive_papers", ["paper_id"], unique=True)
    op.create_index("ix_interactive_papers_cache_key", "interactive_papers", ["cache_key"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    if "interactive_papers" in set(inspect(bind).get_table_names()):
        op.drop_index("ix_interactive_papers_cache_key", table_name="interactive_papers")
        op.drop_index("ix_interactive_papers_paper_id", table_name="interactive_papers")
        op.drop_table("interactive_papers")
