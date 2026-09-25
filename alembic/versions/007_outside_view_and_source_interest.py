"""Outside view and source interest.

Closes two gaps left by 006, where both concepts existed as questions but nothing
consumed the answers:

  - ``reference_case``: base rates extracted from the user's recollection of
    comparable decisions, so the outside view can be *compared against* a
    theory's confidence rather than merely appearing in a prompt.
  - ``claim.source_interest`` / ``claim.source_role``: whether the person
    asserting a claim gains from it being believed, decided per claim at
    extraction time and fed into the truth prior.
  - ``theory.outside_view_delta`` / ``outside_view_note``: how far a theory
    departs from the base rate of its matching reference class.

Reversible. Existing values are unaffected: ``source_interest`` defaults to
``unknown``, which the prior estimator treats as no adjustment.

Revision ID: 007
Revises: 006
Create Date: 2026-07-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Outside view ──
    op.create_table(
        "reference_case",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("project.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("cases_total", sa.Integer(), nullable=False),
        sa.Column("cases_with_outcome", sa.Integer(), nullable=False),
        sa.Column("base_rate", sa.Float(), nullable=False),
        sa.Column("basis", sa.Text(), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="user_recall"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_reference_case_project_id", "reference_case", ["project_id"])

    op.add_column("theory", sa.Column("outside_view_delta", sa.Float(), nullable=True))
    op.add_column("theory", sa.Column("outside_view_note", sa.Text(), nullable=True))

    # ── Source interest, per claim ──
    op.add_column(
        "claim",
        sa.Column(
            "source_interest", sa.String(20), nullable=False, server_default="unknown"
        ),
    )
    op.add_column("claim", sa.Column("source_role", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("claim", "source_role")
    op.drop_column("claim", "source_interest")
    op.drop_column("theory", "outside_view_note")
    op.drop_column("theory", "outside_view_delta")
    op.drop_table("reference_case")
