"""Create the PaperLens schema from the canonical SQLAlchemy metadata."""

from __future__ import annotations

from alembic import op

from backend.app.db.database import Base

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The metadata is the single schema source. This runs only through an explicit
    # Alembic migration, never from production application startup.
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
