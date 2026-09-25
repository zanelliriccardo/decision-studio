"""Questions asked before the causal graph is built.

Adds ``clarification_question.stage``, separating questions about ambiguity in
the extracted claims (``intake``, which pause the pipeline) from questions about
what would change a theory (``theory``, which never block anything).

Existing rows default to ``theory``, which is what they are.

Revision ID: 013
Revises: 012
Create Date: 2026-07-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "clarification_question",
        sa.Column("stage", sa.String(20), nullable=False, server_default="theory"),
    )
    op.create_index(
        "ix_clarification_question_stage", "clarification_question", ["stage"]
    )


def downgrade() -> None:
    # Conditional: revision 016 drops clarification_question entirely, so
    # walking the chain back past it finds nothing here to undo. An
    # unconditional drop would break `downgrade base`.
    op.execute("DROP INDEX IF EXISTS ix_clarification_question_stage")
    op.execute(
        "ALTER TABLE IF EXISTS clarification_question DROP COLUMN IF EXISTS stage"
    )
