"""Token and cost accounting per analysis.

A run makes hundreds of model calls across a dozen stages. Until now the only
signal of what one cost was the provider's monthly bill — too late to know which
analysis was expensive, let alone which stage inside it.

One row per run rather than per project: re-running after a failure is a real
second cost, and folding it into the first would understate what a project
consumed.

Revision ID: 019
Revises: 018
Create Date: 2026-08-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID

revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analysis_usage",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True),
                  sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unpriced_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("price_table_date", sa.String(20), nullable=True),
        sa.Column("by_stage", JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_analysis_usage_project_id", "analysis_usage", ["project_id"])


def downgrade() -> None:
    op.drop_table("analysis_usage")
