"""Separate the quantities that were sharing one number.

Three conflations are unpicked here:

1. ``causal_edge.strength`` meant both "how much effect flows" and "how sure are
   we the link is real". Split into ``effect`` and ``link_confidence``;
   ``strength`` remains as the stored product so existing consumers are unaffected.
2. ``claim.confidence`` was elicited as assertion firmness but consumed as a
   truth probability. ``prior`` now carries the probability; ``confidence``
   keeps its original meaning.
3. Claims repeated across documents each shifted the prior separately.
   ``corroborated_by`` / ``duplicate_count`` record merges.

Also adds ``author_effect`` / ``author_confidence`` / ``blind_scored`` so an
edge's original self-assigned score survives blind re-scoring and inflation can
be measured.

Back-fill preserves every existing number exactly:
  effect = strength, link_confidence = 1.0  ->  product == old strength
  prior  = confidence                       ->  propagation unchanged

Revision ID: 005
Revises: 004
Create Date: 2026-07-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Item 1: effect x link_confidence ──
    op.add_column(
        "causal_edge",
        sa.Column("effect", sa.Float(), nullable=False, server_default="0.5"),
    )
    op.add_column(
        "causal_edge",
        sa.Column("link_confidence", sa.Float(), nullable=False, server_default="0.5"),
    )
    op.add_column("causal_edge", sa.Column("author_effect", sa.Float(), nullable=True))
    op.add_column(
        "causal_edge", sa.Column("author_confidence", sa.Float(), nullable=True)
    )
    op.add_column(
        "causal_edge",
        sa.Column("blind_scored", sa.Boolean(), nullable=False, server_default="false"),
    )

    # Attribute the whole of the legacy strength to effect, with full confidence.
    # effect * 1.0 == old strength, so no propagated belief changes.
    op.execute("UPDATE causal_edge SET effect = strength, link_confidence = 1.0")

    # ── Item 2: truth prior, distinct from assertion firmness ──
    op.add_column(
        "claim", sa.Column("prior", sa.Float(), nullable=False, server_default="0.5")
    )
    op.execute("UPDATE claim SET prior = confidence")

    # ── Item 5: corroboration bookkeeping ──
    op.add_column("claim", sa.Column("corroborated_by", JSON, nullable=True))
    op.add_column(
        "claim",
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    # strength was maintained as the product throughout, so dropping the
    # components loses the distinction but not the operative weight.
    op.drop_column("claim", "duplicate_count")
    op.drop_column("claim", "corroborated_by")
    op.drop_column("claim", "prior")

    op.drop_column("causal_edge", "blind_scored")
    op.drop_column("causal_edge", "author_confidence")
    op.drop_column("causal_edge", "author_effect")
    op.drop_column("causal_edge", "link_confidence")
    op.drop_column("causal_edge", "effect")
