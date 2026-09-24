"""Track the provider secret envelope version for future key rotation."""

from __future__ import annotations

from alembic import op
from sqlalchemy import Column, String, inspect, text


revision = "0007_phase18_secret_version"
down_revision = "0006_phase18_resolver_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("ai_provider_configs")}
    if "secret_version" not in columns:
        op.add_column("ai_provider_configs", Column("secret_version", String(32), nullable=True))
        op.execute(text("UPDATE ai_provider_configs SET secret_version = 'fernet-v1' WHERE secret_version IS NULL"))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("ai_provider_configs")}
    if "secret_version" in columns:
        op.drop_column("ai_provider_configs", "secret_version")
