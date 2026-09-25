"""Decision domain and custom framing questions.

A merger and a reorganisation share the questions that are true of every
decision and almost none of the ones that matter. ``domain`` selects an extra
pack; ``custom_questions`` holds a model-proposed pack for domains the six
built-in ones do not cover.

Neither affects which questions are *required*: the gate stays uniform so a
mis-picked domain cannot block a project.

Revision ID: 012
Revises: 011
Create Date: 2026-07-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "decision_frame",
        sa.Column("domain", sa.String(40), nullable=False, server_default="generic"),
    )
    op.add_column("decision_frame", sa.Column("custom_questions", JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("decision_frame", "custom_questions")
    op.drop_column("decision_frame", "domain")
