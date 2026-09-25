"""Remove the question machinery.

Three question systems were built and all three are gone:

* **intake** — asked about ambiguity in the extracted claims. It paused the
  pipeline, then it did not, and either way it inserted an LLM call and a
  waiting user between claim extraction and the causal graph.
* **framing** — fifteen questions, five of them a reusable profile. It gated
  theory generation, then it reported gaps instead, and in both forms it stood
  between someone who had uploaded documents and the analysis they wanted.
* **clarification** — asked after theories about what would change a conclusion.

What survives is the one field they were all circling: ``project.decision_objective``,
which predates them and is a single sentence in the project header. Reasoning
still needs to know what is being decided; it does not need a questionnaire to
find out.

Irreversible by nature — the answers are dropped with the tables. The downgrade
recreates the tables empty so the chain stays walkable.

Revision ID: 016
Revises: 015
Create Date: 2026-07-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Child tables first: they reference clarification_question.
_TABLES = (
    "question_edge",
    "question_claim",
    "question_theory",
    "clarification_question",
    "decision_profile",
    "decision_frame",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")


def downgrade() -> None:
    # Empty shells. The answers are gone; this only keeps the chain walkable.
    op.create_table(
        "decision_frame",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True),
                  sa.ForeignKey("project.id", ondelete="CASCADE"), unique=True),
        sa.Column("answers", JSON, nullable=True),
        sa.Column("domain", sa.String(40), nullable=False, server_default="generic"),
        sa.Column("custom_questions", JSON, nullable=True),
        sa.Column("is_complete", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "decision_profile",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("answers", JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "clarification_question",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True),
                  sa.ForeignKey("project.id", ondelete="CASCADE")),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("stage", sa.String(20), nullable=False, server_default="theory"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
