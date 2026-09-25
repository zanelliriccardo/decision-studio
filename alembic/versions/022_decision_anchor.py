"""The decision anchor, and each claim's relation to it.

Until now the graph was built without the decision. Extraction was told to
"extract ALL claims", causal inference started from root causes and asked what
each one caused, and ``decision_objective`` was first read by theory generation
— after the graph existed. On twelve documents that produced 476 claims in 58
components, most of them true and unrelated to the choice being made.

The anchor is the decision in a form the pipeline can steer by: the decision,
the options on the table, the outcomes that define success, a deadline and the
hard constraints. Outcomes become nodes, so causal inference has a destination.

Each claim gains four columns saying how it bears on that decision. They are
**scores, never filters**: in a strategic decision the deciding factor is often
the one nobody connected to the problem, and a hard relevance cut would discard
exactly the thing this tool exists to surface.

All nullable. A project without an anchor behaves exactly as before, and every
existing project is such a project.

Revision ID: 022
Revises: 021
Create Date: 2026-09-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "022"
down_revision: Union[str, None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("project", sa.Column("decision_anchor", sa.JSON(), nullable=True))

    op.add_column("claim", sa.Column("decision_role", sa.String(20), nullable=True))
    op.add_column("claim", sa.Column("relevance", sa.Float(), nullable=True))
    op.add_column("claim", sa.Column("relevance_reason", sa.Text(), nullable=True))
    op.add_column("claim", sa.Column("bears_on", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("claim", "bears_on")
    op.drop_column("claim", "relevance_reason")
    op.drop_column("claim", "relevance")
    op.drop_column("claim", "decision_role")
    op.drop_column("project", "decision_anchor")
