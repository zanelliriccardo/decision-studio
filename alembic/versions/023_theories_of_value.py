"""Theories of value: option-bound theories, conviction, link hypotheses.

The theory-based view (and Bocconi's Aristotle, which implements it) treats a
theory as a causal map from the attributes of a choice to the outcome that
defines success, held with a stated *conviction* that is updated by tests. Until
now a theory here was a causal explanation of the situation: bound to no option,
held with a confidence the model assigned, and moved by nothing the user
observed.

Three additions:

* ``theory`` gains the option it is a theory *of*, whether its chain predicts
  that option achieves or threatens an outcome, and whether the chain verifiably
  reaches an outcome node.
* ``theory_belief`` records the user's conviction in a theory: a stated prior,
  and evidence as likelihood ratios. Keyed by ``theory_key`` rather than theory
  id, because regeneration creates a new row per version and a conviction is
  about the theory, not about one wording of it.
* ``link_hypothesis`` holds falsifiable hypotheses about individual causal
  links, ranked by how much testing each would tell.

Revision ID: 023
Revises: 022
Create Date: 2026-09-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "023"
down_revision: Union[str, None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("theory", sa.Column("option_key", sa.String(10), nullable=True))
    op.add_column("theory", sa.Column("predicted_effect", sa.String(20), nullable=True))
    op.add_column("theory", sa.Column("outcome_keys", sa.JSON(), nullable=True))
    op.add_column("theory", sa.Column(
        "reaches_outcome", sa.Boolean(), nullable=False, server_default="false"))

    op.create_table(
        "theory_belief",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True),
                  sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("theory_key", UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("likelihood_ratio", sa.Float(), nullable=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("source_id", UUID(as_uuid=True), nullable=True),
        sa.Column("method", sa.String(20), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_theory_belief_key", "theory_belief", ["project_id", "theory_key"])

    op.create_table(
        "link_hypothesis",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True),
                  sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("theory_key", UUID(as_uuid=True), nullable=False),
        sa.Column("theory_id", UUID(as_uuid=True),
                  sa.ForeignKey("theory.id", ondelete="SET NULL"), nullable=True),
        sa.Column("edge_id", UUID(as_uuid=True),
                  sa.ForeignKey("causal_edge.id", ondelete="CASCADE"), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("refuted_if", sa.Text(), nullable=False),
        sa.Column("cheapest_test", sa.Text(), nullable=False, server_default=""),
        sa.Column("priority", sa.Float(), nullable=False, server_default="0"),
        sa.Column("leverage", sa.Float(), nullable=False, server_default="0"),
        sa.Column("uncertainty", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("observed_note", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_link_hypothesis_key", "link_hypothesis", ["project_id", "theory_key"])


def downgrade() -> None:
    op.drop_index("ix_link_hypothesis_key", table_name="link_hypothesis")
    op.drop_table("link_hypothesis")
    op.drop_index("ix_theory_belief_key", table_name="theory_belief")
    op.drop_table("theory_belief")
    op.drop_column("theory", "reaches_outcome")
    op.drop_column("theory", "outcome_keys")
    op.drop_column("theory", "predicted_effect")
    op.drop_column("theory", "option_key")
