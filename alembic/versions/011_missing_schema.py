"""Schema drift: objects that existed in the models but in no migration.

Found by diffing a database built purely from migrations against
``Base.metadata``. All three predate the decision-reasoning work:

  - ``project.last_completed_stage`` — the pipeline resume checkpoint. Its
    absence made ``GET /api/v1/projects`` fail outright on a fresh deployment,
    because SQLAlchemy selects every mapped column.
  - ``advisor_session`` / ``advisor_message`` — the Strategic Advisor's
    conversation history.

They went unnoticed because a long-lived development database accumulates
columns through `create_all` and other out-of-band changes, so the drift only
appears when someone deploys from scratch. Which is exactly what deploying to
Azure does.

Guarded with IF NOT EXISTS / checkfirst so it is a no-op on a database that
already has them.

Revision ID: 011
Revises: 010
Create Date: 2026-07-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing databases may already carry these, so every step is conditional.
    op.execute(
        "ALTER TABLE project ADD COLUMN IF NOT EXISTS last_completed_stage VARCHAR(50)"
    )

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "advisor_session" not in existing:
        op.create_table(
            "advisor_session",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "project_id",
                UUID(as_uuid=True),
                sa.ForeignKey("project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "title", sa.String(500), nullable=False, server_default="New conversation"
            ),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_advisor_session_project_id", "advisor_session", ["project_id"]
        )

    if "advisor_message" not in existing:
        op.create_table(
            "advisor_message",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "session_id",
                UUID(as_uuid=True),
                sa.ForeignKey("advisor_session.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("role", sa.String(20), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("tags", JSON, nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
            ),
        )
        op.create_index(
            "ix_advisor_message_session_id", "advisor_message", ["session_id"]
        )


def downgrade() -> None:
    op.drop_table("advisor_message")
    op.drop_table("advisor_session")
    op.drop_column("project", "last_completed_stage")
