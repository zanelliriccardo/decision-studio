"""Strategic decision support: framing, tripwires and adversarial objections.

Adds the process discipline that low-evidence decisions need in place of the
empirical validation they cannot have:

  - ``decision_frame``   the user's answers to the framing questionnaire.
    Theory generation is gated on the required ones being answered.
  - ``theory_tripwire``  falsifiable forward commitments per theory.
  - ``theory_objection`` adversarial critiques, plus ``objection_load`` /
    ``contested`` / ``adjusted_score`` on ``theory`` so they cost rank.

Reversible. Nothing existing changes value.

Revision ID: 006
Revises: 005
Create Date: 2026-07-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Decision frame ──
    op.create_table(
        "decision_frame",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("project.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("answers", JSON, nullable=True),
        sa.Column("is_complete", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_decision_frame_project_id", "decision_frame", ["project_id"])

    # ── Tripwires ──
    op.create_table(
        "theory_tripwire",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "theory_id",
            UUID(as_uuid=True),
            sa.ForeignKey("theory.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("observable", sa.Text(), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False, server_default="falsifies"),
        sa.Column("horizon_days", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("check_by", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_theory_tripwire_theory_id", "theory_tripwire", ["theory_id"])

    # ── Objections ──
    op.create_table(
        "theory_objection",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "theory_id",
            UUID(as_uuid=True),
            sa.ForeignKey("theory.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("objection", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False, server_default="other"),
        sa.Column("severity", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("dismissed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_theory_objection_theory_id", "theory_objection", ["theory_id"])

    # ── Theory carries the adversary's verdict ──
    op.add_column(
        "theory",
        sa.Column("objection_load", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "theory",
        sa.Column("contested", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("theory", sa.Column("adjusted_score", sa.Float(), nullable=True))
    # Until the adversary has run, the adjusted score is just the confidence.
    op.execute("UPDATE theory SET adjusted_score = confidence")

    # ── Internal sources become first-class ──
    # `source_url` was NOT NULL because every source came from the web. An
    # internal report has no URL, and requiring a placeholder would corrupt
    # provenance.
    op.alter_column("evidence", "source_url", existing_type=sa.Text(), nullable=True)
    op.add_column(
        "evidence",
        sa.Column("author_interest", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("evidence", "author_interest")
    op.execute("UPDATE evidence SET source_url = '' WHERE source_url IS NULL")
    op.alter_column("evidence", "source_url", existing_type=sa.Text(), nullable=False)

    op.drop_column("theory", "adjusted_score")
    op.drop_column("theory", "contested")
    op.drop_column("theory", "objection_load")

    op.drop_table("theory_objection")
    op.drop_table("theory_tripwire")
    op.drop_table("decision_frame")
