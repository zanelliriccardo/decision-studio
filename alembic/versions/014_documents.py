"""Keep uploaded documents instead of consuming them.

An upload used to be extracted straight into the prompt box: the text replaced
whatever the user had typed, and the file was discarded. That lost the ability
to upload several files, any record of which document a claim came from, and
the original bytes — so re-extracting with a better parser meant asking the user
to find the file again.

``project_id`` is nullable because a document is uploaded before the project it
will belong to exists.

Revision ID: 014
Revises: 013
Create Date: 2026-07-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True),
                  sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=True),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("content_type", sa.String(120), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("extracted_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("extraction_error", sa.Text(), nullable=True),
        sa.Column("raw_content", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_document_project_id", "document", ["project_id"])


def downgrade() -> None:
    op.drop_table("document")
