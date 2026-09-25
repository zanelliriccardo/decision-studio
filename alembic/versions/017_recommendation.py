"""The synthesised recommendation.

The theories are separate explanations; weighing them against each other is the
part the reader came for and was being left to do alone.

Revision ID: 017
Revises: 016
Create Date: 2026-07-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID

revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "decision_recommendation",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True),
                  sa.ForeignKey("project.id", ondelete="CASCADE"),
                  nullable=False, unique=True),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False, server_default=""),
        sa.Column("depends_on", JSON, nullable=True),
        sa.Column("against_it", sa.Text(), nullable=True),
        sa.Column("next_step", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(20), nullable=False, server_default="moderate"),
        sa.Column("theory_ids", JSON, nullable=True),
        sa.Column("graph_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_decision_recommendation_project_id",
                    "decision_recommendation", ["project_id"])


def downgrade() -> None:
    op.drop_table("decision_recommendation")
