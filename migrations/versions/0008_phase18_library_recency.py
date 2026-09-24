"""Store the last time an owner opened a paper."""

from __future__ import annotations

from alembic import op
from sqlalchemy import Column, DateTime, inspect


revision = "0008_phase18_library_recency"
down_revision = "0007_phase18_secret_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("papers")}
    if "last_opened_at" not in columns:
        op.add_column("papers", Column("last_opened_at", DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("papers")}
    if "last_opened_at" in columns:
        op.drop_column("papers", "last_opened_at")
