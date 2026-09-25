"""Decision reasoning: graph review state, theories and clarification questions.

Adds:
  - review columns on claim / causal_edge (reversible soft delete, review
    status, user note, human strength override)
  - graph_revision + decision_objective on project
  - graph_operation: immutable audit/undo log for review operations
  - theory, theory_revision + normalized provenance links
    (theory_claim, theory_edge, theory_evidence)
  - clarification_question + normalized links
    (question_theory, question_claim, question_edge)

Fully reversible: downgrade() drops every object created here and nothing else.

Revision ID: 004
Revises: 003
Create Date: 2026-07-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Project: revision counter + decision objective ──
    op.add_column(
        "project",
        sa.Column("graph_revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("project", sa.Column("decision_objective", sa.Text(), nullable=True))

    # ── Claim review state ──
    op.add_column(
        "claim",
        sa.Column("review_status", sa.String(30), nullable=False, server_default="accepted"),
    )
    op.add_column(
        "claim",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column("claim", sa.Column("user_note", sa.Text(), nullable=True))
    op.add_column(
        "claim", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)
    )

    # ── Causal edge review state ──
    op.add_column(
        "causal_edge",
        sa.Column("review_status", sa.String(30), nullable=False, server_default="accepted"),
    )
    op.add_column(
        "causal_edge",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column("causal_edge", sa.Column("user_note", sa.Text(), nullable=True))
    op.add_column("causal_edge", sa.Column("strength_override", sa.Float(), nullable=True))
    op.add_column(
        "causal_edge", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)
    )

    # ── Graph operation audit log ──
    op.create_table(
        "graph_operation",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("project.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("operation_type", sa.String(40), nullable=False),
        sa.Column("target_type", sa.String(10), nullable=False),
        sa.Column(
            "claim_id",
            UUID(as_uuid=True),
            sa.ForeignKey("claim.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "edge_id",
            UUID(as_uuid=True),
            sa.ForeignKey("causal_edge.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("before_state", JSON, nullable=True),
        sa.Column("after_state", JSON, nullable=True),
        sa.Column("revision_before", sa.Integer(), nullable=False),
        sa.Column("revision_after", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="user"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "undone_by_operation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("graph_operation.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_graph_operation_project_id", "graph_operation", ["project_id"])

    # ── Theory revisions ──
    op.create_table(
        "theory_revision",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("project.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("graph_revision", sa.Integer(), nullable=False),
        sa.Column("generation_id", UUID(as_uuid=True), nullable=False),
        sa.Column("trigger", sa.String(20), nullable=False, server_default="generate"),
        sa.Column("change_summary", JSON, nullable=True),
        sa.Column("generation_metadata", JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_theory_revision_project_id", "theory_revision", ["project_id"])

    # ── Theories ──
    op.create_table(
        "theory",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("project.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("theory_key", UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="hypothesis"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("business_impact", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("recommendation", sa.Text(), nullable=False, server_default=""),
        sa.Column("weak_assumptions", JSON, nullable=True),
        sa.Column("causal_chain", JSON, nullable=True),
        sa.Column("graph_revision", sa.Integer(), nullable=False),
        sa.Column("theory_revision", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_stale", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("stale_reason", sa.Text(), nullable=True),
        sa.Column("change_kind", sa.String(20), nullable=True),
        sa.Column("change_explanation", sa.Text(), nullable=True),
        sa.Column(
            "superseded_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("theory.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("generation_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_theory_project_id", "theory", ["project_id"])
    op.create_index("ix_theory_theory_key", "theory", ["theory_key"])

    # ── Theory provenance links ──
    op.create_table(
        "theory_claim",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "theory_id",
            UUID(as_uuid=True),
            sa.ForeignKey("theory.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "claim_id",
            UUID(as_uuid=True),
            sa.ForeignKey("claim.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False, server_default="supporting"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_theory_claim_theory_id", "theory_claim", ["theory_id"])
    op.create_index("ix_theory_claim_claim_id", "theory_claim", ["claim_id"])

    op.create_table(
        "theory_edge",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "theory_id",
            UUID(as_uuid=True),
            sa.ForeignKey("theory.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "edge_id",
            UUID(as_uuid=True),
            sa.ForeignKey("causal_edge.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False, server_default="supporting"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_theory_edge_theory_id", "theory_edge", ["theory_id"])
    op.create_index("ix_theory_edge_edge_id", "theory_edge", ["edge_id"])

    op.create_table(
        "theory_evidence",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "theory_id",
            UUID(as_uuid=True),
            sa.ForeignKey("theory.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "evidence_id",
            UUID(as_uuid=True),
            sa.ForeignKey("evidence.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False, server_default="supporting"),
    )
    op.create_index("ix_theory_evidence_theory_id", "theory_evidence", ["theory_id"])
    op.create_index("ix_theory_evidence_evidence_id", "theory_evidence", ["evidence_id"])

    # ── Clarification questions ──
    op.create_table(
        "clarification_question",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("project.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "expected_information_gain", sa.String(10), nullable=False, server_default="medium"
        ),
        sa.Column("priority", sa.String(10), nullable=False, server_default="medium"),
        sa.Column("answer_type", sa.String(20), nullable=False, server_default="free_text"),
        sa.Column("options", JSON, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("answer", JSON, nullable=True),
        sa.Column("answer_note", sa.Text(), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("graph_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("generation_id", UUID(as_uuid=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_clarification_question_project_id", "clarification_question", ["project_id"]
    )
    op.create_index(
        "ix_clarification_question_fingerprint", "clarification_question", ["fingerprint"]
    )

    op.create_table(
        "question_theory",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "question_id",
            UUID(as_uuid=True),
            sa.ForeignKey("clarification_question.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "theory_id",
            UUID(as_uuid=True),
            sa.ForeignKey("theory.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("theory_key", UUID(as_uuid=True), nullable=False),
    )
    op.create_index("ix_question_theory_question_id", "question_theory", ["question_id"])
    op.create_index("ix_question_theory_theory_id", "question_theory", ["theory_id"])
    op.create_index("ix_question_theory_theory_key", "question_theory", ["theory_key"])

    op.create_table(
        "question_claim",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "question_id",
            UUID(as_uuid=True),
            sa.ForeignKey("clarification_question.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "claim_id",
            UUID(as_uuid=True),
            sa.ForeignKey("claim.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    op.create_index("ix_question_claim_question_id", "question_claim", ["question_id"])
    op.create_index("ix_question_claim_claim_id", "question_claim", ["claim_id"])

    op.create_table(
        "question_edge",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "question_id",
            UUID(as_uuid=True),
            sa.ForeignKey("clarification_question.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "edge_id",
            UUID(as_uuid=True),
            sa.ForeignKey("causal_edge.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    op.create_index("ix_question_edge_question_id", "question_edge", ["question_id"])
    op.create_index("ix_question_edge_edge_id", "question_edge", ["edge_id"])


def downgrade() -> None:
    # Conditional: revision 016 removed the question machinery, so walking the
    # chain back past it finds these already gone.
    for table in ("question_edge", "question_claim", "question_theory"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("DROP TABLE IF EXISTS clarification_question CASCADE")
    op.drop_table("theory_evidence")
    op.drop_table("theory_edge")
    op.drop_table("theory_claim")
    op.drop_table("theory")
    op.drop_table("theory_revision")
    op.drop_table("graph_operation")

    op.drop_column("causal_edge", "reviewed_at")
    op.drop_column("causal_edge", "strength_override")
    op.drop_column("causal_edge", "user_note")
    op.drop_column("causal_edge", "is_active")
    op.drop_column("causal_edge", "review_status")

    op.drop_column("claim", "reviewed_at")
    op.drop_column("claim", "user_note")
    op.drop_column("claim", "is_active")
    op.drop_column("claim", "review_status")

    op.drop_column("project", "decision_objective")
    op.drop_column("project", "graph_revision")
