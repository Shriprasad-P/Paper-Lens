"""Add database-authoritative research execution, attempts, leases, and fencing."""

from __future__ import annotations

from alembic import op
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, inspect, text

revision = "0003_phase13b_durable_execution"
down_revision = "0002_phase13a_auth_ownership"
branch_labels = None
depends_on = None


def _add_column(table: str, column: Column) -> None:
    if column.name not in {item["name"] for item in inspect(op.get_bind()).get_columns(table)}:
        op.add_column(table, column)


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "research_runs" in tables:
        _add_column("research_runs", Column("execution_state", String(32), nullable=True))
        _add_column("research_runs", Column("active_attempt_id", String(64), nullable=True))
        _add_column("research_runs", Column("attempt_count", Integer, nullable=True))
        _add_column("research_runs", Column("cancel_requested_at", DateTime(timezone=True), nullable=True))
        _add_column("research_runs", Column("next_attempt_at", DateTime(timezone=True), nullable=True))
        op.execute(text("UPDATE research_runs SET execution_state = CASE WHEN status IN ('COMPLETED','PARTIAL') THEN 'COMPLETED' WHEN status = 'CANCELLED' THEN 'CANCELLED' WHEN status IN ('FAILED','INTERRUPTED') THEN 'FAILED' WHEN status = 'CREATED' THEN 'IDLE' ELSE 'IDLE' END WHERE execution_state IS NULL"))
        op.execute(text("UPDATE research_runs SET attempt_count = 0 WHERE attempt_count IS NULL"))
        with op.batch_alter_table("research_runs") as batch:
            batch.alter_column("execution_state", existing_type=String(32), nullable=False, server_default="IDLE")
            batch.alter_column("attempt_count", existing_type=Integer, nullable=False, server_default="0")
        indexes = {item["name"] for item in inspect(bind).get_indexes("research_runs")}
        if "ix_research_runs_execution_state" not in indexes:
            op.create_index("ix_research_runs_execution_state", "research_runs", ["execution_state"])
        if "ix_research_runs_next_attempt_at" not in indexes:
            op.create_index("ix_research_runs_next_attempt_at", "research_runs", ["next_attempt_at"])

    if "research_execution_attempts" not in tables:
        op.create_table(
            "research_execution_attempts",
            Column("attempt_id", String(64), primary_key=True),
            Column("research_run_id", String(64), ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=False),
            Column("owner_id", String(64), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
            Column("worker_id", String(128), nullable=False),
            Column("claim_token_hash", String(64), nullable=False),
            Column("attempt_number", Integer, nullable=False),
            Column("status", String(32), nullable=False),
            Column("claimed_at", DateTime(timezone=True), nullable=False),
            Column("lease_expires_at", DateTime(timezone=True), nullable=False),
            Column("heartbeat_at", DateTime(timezone=True), nullable=True),
            Column("started_at", DateTime(timezone=True), nullable=True),
            Column("completed_at", DateTime(timezone=True), nullable=True),
            Column("next_retry_at", DateTime(timezone=True), nullable=True),
            Column("retryable", Boolean, nullable=True),
            Column("error_class", String(64), nullable=True),
            Column("error_message", Text, nullable=True),
            UniqueConstraint("research_run_id", "attempt_number", name="uq_research_attempt_number"),
        )
        op.create_index("ix_research_execution_attempts_research_run_id", "research_execution_attempts", ["research_run_id"])
        op.create_index("ix_research_execution_attempts_owner_id", "research_execution_attempts", ["owner_id"])
        op.create_index("ix_research_execution_attempts_worker_id", "research_execution_attempts", ["worker_id"])
        op.create_index("ix_research_execution_attempts_status", "research_execution_attempts", ["status"])
        op.create_index("ix_research_execution_attempts_lease_expires_at", "research_execution_attempts", ["lease_expires_at"])

    if "research_run_events" in tables:
        _add_column("research_run_events", Column("attempt_id", String(64), nullable=True))
        _add_column("research_run_events", Column("sequence", Integer, nullable=True))
        if "ix_research_run_events_attempt_id" not in {item["name"] for item in inspect(bind).get_indexes("research_run_events")}:
            op.create_index("ix_research_run_events_attempt_id", "research_run_events", ["attempt_id"])
        # Existing events are intentionally left as legacy (attempt_id NULL). New
        # events receive a strictly increasing per-run sequence in the DB adapter.


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "research_run_events" in tables:
        with op.batch_alter_table("research_run_events") as batch:
            batch.drop_index("ix_research_run_events_attempt_id")
            batch.drop_column("sequence")
            batch.drop_column("attempt_id")
    if "research_execution_attempts" in tables:
        op.drop_table("research_execution_attempts")
    if "research_runs" in tables:
        with op.batch_alter_table("research_runs") as batch:
            batch.drop_index("ix_research_runs_next_attempt_at")
            batch.drop_index("ix_research_runs_execution_state")
            batch.drop_column("next_attempt_at")
            batch.drop_column("cancel_requested_at")
            batch.drop_column("attempt_count")
            batch.drop_column("active_attempt_id")
            batch.drop_column("execution_state")
