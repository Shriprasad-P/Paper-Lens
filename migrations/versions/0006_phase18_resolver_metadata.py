"""Persist canonical resolver metadata on paper rows."""

from __future__ import annotations

from alembic import op
from sqlalchemy import JSON, Column, inspect


revision = "0006_phase18_resolver_metadata"
down_revision = "0005_phase18_provider_configs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("papers")}
    if "metadata_payload" not in columns:
        op.add_column("papers", Column("metadata_payload", JSON, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("papers")}
    if "metadata_payload" in columns:
        op.drop_column("papers", "metadata_payload")
