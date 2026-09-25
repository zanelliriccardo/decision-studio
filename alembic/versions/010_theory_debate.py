"""Structured comparison between competing theories.

Records where two theories overlap, where they part company, and what
observation would resolve the difference. The overlap fields are computed from
the normalized theory links rather than generated.

Revision ID: 010
Revises: 009
Create Date: 2026-07-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "theory_debate",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True),
                  sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("theory_a_id", UUID(as_uuid=True),
                  sa.ForeignKey("theory.id", ondelete="CASCADE"), nullable=False),
        sa.Column("theory_b_id", UUID(as_uuid=True),
                  sa.ForeignKey("theory.id", ondelete="CASCADE"), nullable=False),
        sa.Column("overlap_jaccard", sa.Float(), nullable=False),
        sa.Column("relation", sa.String(20), nullable=False),
        sa.Column("shared_claim_ids", JSON, nullable=True),
        sa.Column("shared_edge_ids", JSON, nullable=True),
        sa.Column("divergent_claim_ids", JSON, nullable=True),
        sa.Column("divergent_edge_ids", JSON, nullable=True),
        sa.Column("crux", sa.Text(), nullable=True),
        sa.Column("discriminator", sa.Text(), nullable=True),
        sa.Column("discriminator_feasible", sa.Boolean(), nullable=False,
                  server_default="false"),
        sa.Column("discriminator_horizon_days", sa.Integer(), nullable=True),
        sa.Column("evidence_favours", sa.String(10), nullable=True),
        sa.Column("both_possible", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("graph_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_stale", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("promoted_tripwire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_theory_debate_project_id", "theory_debate", ["project_id"])
    op.create_index("ix_theory_debate_theory_a_id", "theory_debate", ["theory_a_id"])
    op.create_index("ix_theory_debate_theory_b_id", "theory_debate", ["theory_b_id"])


def downgrade() -> None:
    op.drop_table("theory_debate")
