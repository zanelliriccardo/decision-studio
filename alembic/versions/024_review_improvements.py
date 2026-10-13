"""Improvements from the logic review (docs/LOGIC_REVIEW.md, part 2).

* ``project.outside_view_recollection``: the decider's own words about
  comparable past decisions, kept so the summary page can show and edit them.
* ``theory.outside_view_case_id`` / ``outside_view_polarity``: which reference
  case a theory was matched to, and whether the theory predicts that case's
  outcome or its opposite. Stored so the comparison can be recomputed against
  the decider's conviction whenever it moves, without another model call.
* ``theory_belief.event``: the real-world event an observation came from. Two
  observations of one event are one piece of evidence, not two.
* ``theory_tripwire.decisiveness`` / ``link_hypothesis.decisiveness``: how much
  the decider said, in advance, that the result would count.

Revision ID: 024
Revises: 023
Create Date: 2026-09-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "024"
down_revision: Union[str, None] = "023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("project", sa.Column("outside_view_recollection", sa.Text(), nullable=True))
    op.add_column("theory", sa.Column(
        "outside_view_case_id", UUID(as_uuid=True),
        sa.ForeignKey("reference_case.id", ondelete="SET NULL"), nullable=True))
    op.add_column("theory", sa.Column("outside_view_polarity", sa.String(10), nullable=True))
    op.add_column("theory_belief", sa.Column("event", sa.String(200), nullable=True))
    op.add_column("theory_tripwire", sa.Column("decisiveness", sa.String(10), nullable=True))
    op.add_column("link_hypothesis", sa.Column("decisiveness", sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column("link_hypothesis", "decisiveness")
    op.drop_column("theory_tripwire", "decisiveness")
    op.drop_column("theory_belief", "event")
    op.drop_column("theory", "outside_view_polarity")
    op.drop_column("theory", "outside_view_case_id")
    op.drop_column("project", "outside_view_recollection")
