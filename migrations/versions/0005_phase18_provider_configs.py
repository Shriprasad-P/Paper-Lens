"""Add owner-bound encrypted LLM provider configurations."""

from __future__ import annotations

from alembic import op
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text, UniqueConstraint, inspect


revision = "0005_phase18_provider_configs"
down_revision = "0004_phase17_interactive_paper"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "ai_provider_configs" in set(inspect(bind).get_table_names()):
        return
    op.create_table(
        "ai_provider_configs",
        Column("id", String(64), primary_key=True),
        Column("owner_id", String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        Column("provider_type", String(32), nullable=False),
        Column("display_name", String(120), nullable=False),
        Column("base_url", Text, nullable=False),
        Column("generation_model", String(200), nullable=False),
        Column("embedding_model", String(200), nullable=True),
        Column("encrypted_secret", Text, nullable=False, default=""),
        Column("secret_version", String(32), nullable=False, default="fernet-v1"),
        Column("secret_hint", String(32), nullable=True),
        Column("enabled", Boolean, nullable=False, default=True),
        Column("last_tested_at", DateTime(timezone=True), nullable=True),
        Column("last_test_status", String(32), nullable=True),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
        UniqueConstraint("owner_id", "display_name", name="uq_ai_provider_owner_name"),
    )
    op.create_index("ix_ai_provider_configs_owner_id", "ai_provider_configs", ["owner_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if "ai_provider_configs" in set(inspect(bind).get_table_names()):
        op.drop_index("ix_ai_provider_configs_owner_id", table_name="ai_provider_configs")
        op.drop_table("ai_provider_configs")
