"""Add durable accounts, sessions, audit events, and tenant ownership.

The first release was local-first and had no principal boundary.  Existing
records are assigned to a deterministic local owner so the upgrade is safe and
repeatable; production deployments must then use real registered accounts.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import Column, DateTime, ForeignKey, JSON, String, inspect, text

revision = "0002_phase13a_auth_ownership"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None

LEGACY_OWNER_ID = "user_legacy_local"
LEGACY_OWNER_EMAIL = "local@paperlens.invalid"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "users" not in tables:
        op.create_table(
            "users",
            Column("id", String(64), primary_key=True),
            Column("email", String(320), nullable=False, unique=True),
            Column("password_hash", String(512), nullable=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
            Column("disabled_at", DateTime(timezone=True), nullable=True),
        )
    else:
        tables.add("users")

    op.execute(
        text(
            "INSERT INTO users (id, email, password_hash, created_at, updated_at) "
            "SELECT :id, :email, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
            "WHERE NOT EXISTS (SELECT 1 FROM users WHERE id = :id OR email = :email)"
        ).bindparams(id=LEGACY_OWNER_ID, email=LEGACY_OWNER_EMAIL)
    )

    inspector = inspect(bind)
    for table in ("papers", "workspaces", "research_runs", "chat_sessions"):
        if table not in inspector.get_table_names():
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "owner_id" not in columns:
            op.add_column(table, Column("owner_id", String(64), nullable=True))
        op.execute(text(f"UPDATE {table} SET owner_id = :owner WHERE owner_id IS NULL").bindparams(owner=LEGACY_OWNER_ID))
        table_inspector = inspect(bind)
        foreign_keys = table_inspector.get_foreign_keys(table)
        has_owner_fk = any(
            fk.get("referred_table") == "users" and fk.get("constrained_columns") == ["owner_id"]
            for fk in foreign_keys
        )
        owner_nullable = next(
            (column.get("nullable", True) for column in inspect(bind).get_columns(table) if column["name"] == "owner_id"),
            True,
        )
        if owner_nullable or not has_owner_fk:
            # Batch mode keeps this compatible with SQLite while producing a
            # real non-null foreign key on PostgreSQL and fresh deployments.
            with op.batch_alter_table(table) as batch:
                if owner_nullable:
                    batch.alter_column("owner_id", existing_type=String(64), nullable=False)
                if not has_owner_fk:
                    batch.create_foreign_key(
                        f"fk_{table}_owner_users",
                        "users",
                        ["owner_id"],
                        ["id"],
                        ondelete="RESTRICT",
                    )
        indexes = {index["name"] for index in inspect(bind).get_indexes(table)}
        owner_index = f"ix_{table}_owner_id"
        if owner_index not in indexes:
            op.create_index(owner_index, table, ["owner_id"])

    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "auth_sessions" not in tables:
        op.create_table(
            "auth_sessions",
            Column("id", String(64), primary_key=True),
            Column("user_id", String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            Column("token_hash", String(64), nullable=False, unique=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("expires_at", DateTime(timezone=True), nullable=False),
            Column("last_seen_at", DateTime(timezone=True), nullable=False),
            Column("revoked_at", DateTime(timezone=True), nullable=True),
        )
    if "audit_log" not in tables:
        op.create_table(
            "audit_log",
            Column("id", String(64), primary_key=True),
            Column("event", String(64), nullable=False),
            Column("user_id", String(64), nullable=True),
            Column("metadata", JSON, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "audit_log" in tables:
        op.drop_table("audit_log")
    if "auth_sessions" in tables:
        op.drop_table("auth_sessions")
    for table in ("chat_sessions", "research_runs", "workspaces", "papers"):
        if table not in tables:
            continue
        if "owner_id" in {column["name"] for column in inspect(bind).get_columns(table)}:
            with op.batch_alter_table(table) as batch:
                batch.drop_column("owner_id")
    if "users" in tables:
        op.drop_table("users")
