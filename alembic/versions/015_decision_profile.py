"""Answers that hold across analyses, kept once.

Role, authority, audience, hard constraints and risk appetite describe the
decider rather than the decision. Re-asking them for every analysis produced
identical answers and made a second analysis feel like starting over.

A single row: this deployment has no user model. Accounts later mean adding a
nullable user_id with a unique constraint.

Revision ID: 015
Revises: 014
Create Date: 2026-07-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "decision_profile",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("answers", JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("decision_profile")
