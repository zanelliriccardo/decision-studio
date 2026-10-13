"""Decision priorities: how much each success criterion matters to the decider.

``project.outcome_priorities`` maps an anchor outcome key (Y1..) to an
importance level (critical, high, medium, low, none); see
reasoning/decision_priorities.py for the weights. Kept apart from
``decision_anchor`` so changing a priority never touches the causal graph or
re-scores a claim. Nullable: existing projects read as "all at the default".

Revision ID: 025
Revises: 024
Create Date: 2026-09-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "025"
down_revision: Union[str, None] = "024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("project", sa.Column("outcome_priorities", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("project", "outcome_priorities")
