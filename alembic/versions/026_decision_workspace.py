"""Scenarios for the decision, and sub-decisions.

* ``scenario.decision_case``: "upside" or "downside" when the row holds the
  decider's own assumptions for that case of the option comparison. Null for
  the scenario forks that already live in this table. Reuses the table's
  ``edge_overrides`` (edge id -> strength) rather than adding a second store.
* ``scenario.claim_overrides``: claim id -> prior, for the same rows. Only root
  claims' priors enter propagation.
* ``project.sub_decisions``: sub-decisions under an option (staffing, vendor,
  scope), each with choices defined by existing claims. See
  reasoning/sub_decisions.py.

All nullable: existing rows and projects read as "nothing defined".

Revision ID: 026
Revises: 025
Create Date: 2026-09-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "026"
down_revision: Union[str, None] = "025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("scenario", sa.Column("decision_case", sa.String(20), nullable=True))
    op.add_column("scenario", sa.Column("claim_overrides", sa.JSON(), nullable=True))
    op.add_column("project", sa.Column("sub_decisions", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("project", "sub_decisions")
    op.drop_column("scenario", "claim_overrides")
    op.drop_column("scenario", "decision_case")
