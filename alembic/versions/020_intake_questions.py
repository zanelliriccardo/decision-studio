"""Questions asked before the pipeline starts.

The fourth question system in this repository, and the first that does not stand
between the user and the analysis. The three before it were removed by migration
016: the framing form blocked theory generation, the first intake paused a
twenty-minute run halfway through, and clarification went with them.

What makes this one different is only *where* it runs — before the orchestrator
is called, so there is nothing to pause. One table where the three of them held
six.

``project.intake_context`` holds the rendered answers verbatim, exactly as they
were prepended to the prompts. Stored rather than rebuilt on demand: six months
on the question is what the model actually read, and re-rendering under changed
code would answer a different one.

Revision ID: 020
Revises: 019
Create Date: 2026-08-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID

revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("project", sa.Column("intake_context", sa.Text(), nullable=True))

    op.create_table(
        "intake_question",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True),
                  sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("quoted_source", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("options", JSON, nullable=True),
        sa.Column("options_rejected", sa.Boolean(), nullable=False,
                  server_default="false"),
        sa.Column("answer_choice", sa.Integer(), nullable=True),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )
    op.create_index("ix_intake_question_project_id", "intake_question", ["project_id"])


def downgrade() -> None:
    op.drop_table("intake_question")
    op.drop_column("project", "intake_context")
