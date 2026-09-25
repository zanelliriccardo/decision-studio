"""Manual graph authoring.

Adds ``origin`` to claim and causal_edge so a human-authored element is
distinguishable from an inferred one.

This closes an asymmetry that was incoherent with the rest of the design: human
review was authoritative for *removing* elements and silent for *adding* them.
In strategic decisions the factors that matter are frequently not written down
anywhere, so a model that can only be pruned cannot be corrected.

Revision ID: 009
Revises: 008
Create Date: 2026-07-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "claim", sa.Column("origin", sa.String(10), nullable=False, server_default="ai")
    )
    op.add_column(
        "causal_edge",
        sa.Column("origin", sa.String(10), nullable=False, server_default="ai"),
    )


def downgrade() -> None:
    op.drop_column("causal_edge", "origin")
    op.drop_column("claim", "origin")
