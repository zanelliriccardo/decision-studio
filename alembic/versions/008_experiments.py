"""Synthetic and field experiments.

A synthetic experiment simulates the stakeholders who must be convinced, and
answers "will this survive the room, and what will they object to". A field
experiment is a real test the user runs.

The distinction is load-bearing: only the second is evidence about the world, so
only the second may move a theory's confidence. See the epistemic note in
models.py.

Revision ID: 008
Revises: 007
Create Date: 2026-07-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "experiment",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True),
                  sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("theory_id", UUID(as_uuid=True),
                  sa.ForeignKey("theory.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False, server_default="synthetic"),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("design", sa.Text(), nullable=False, server_default=""),
        sa.Column("measure", sa.Text(), nullable=True),
        sa.Column("cost_estimate", sa.String(200), nullable=True),
        sa.Column("duration_days", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="designed"),
        sa.Column("support_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("oppose_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("neutral_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_experiment_project_id", "experiment", ["project_id"])
    op.create_index("ix_experiment_theory_id", "experiment", ["theory_id"])

    op.create_table(
        "experiment_persona",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("experiment_id", UUID(as_uuid=True),
                  sa.ForeignKey("experiment.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("stake", sa.Text(), nullable=False),
        sa.Column("prior_position", sa.Text(), nullable=True),
        sa.Column("grounded_in_frame", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index("ix_experiment_persona_experiment_id", "experiment_persona",
                    ["experiment_id"])

    op.create_table(
        "experiment_response",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("experiment_id", UUID(as_uuid=True),
                  sa.ForeignKey("experiment.id", ondelete="CASCADE"), nullable=False),
        sa.Column("persona_id", UUID(as_uuid=True),
                  sa.ForeignKey("experiment_persona.id", ondelete="CASCADE"), nullable=False),
        sa.Column("verdict", sa.String(20), nullable=False),
        sa.Column("reaction", sa.Text(), nullable=False),
        sa.Column("key_objection", sa.Text(), nullable=True),
        sa.Column("would_need", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_experiment_response_experiment_id", "experiment_response",
                    ["experiment_id"])


def downgrade() -> None:
    op.drop_table("experiment_response")
    op.drop_table("experiment_persona")
    op.drop_table("experiment")
