"""How much of a theory's causal chain is actually connected.

Chain steps were validated for *resolution* — every token pointed at a live
graph element — but never for *connectivity*: whether an edge joins the claim
before it to the claim after it. On a fragmented graph the model produced chains
where every token resolved and no edge fitted, and they rendered with the same
authority as real ones.

The check is now enforced (see HANDOVER §5). These two columns carry the result
to the reader, because a theory keeping one junction of three is worth showing
and worth distinguishing from one keeping three of three — and the ranking is
what the brief recommends from.

Deliberately not folded into ``adjusted_score``: weighting integrity there would
be another hand-picked constant. It is exposed instead, which is what this system
does everywhere else it cannot calibrate.

Revision ID: 021
Revises: 020
Create Date: 2026-08-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "021"
down_revision: Union[str, None] = "020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("theory", sa.Column(
        "connected_links", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("theory", sa.Column(
        "cited_links", sa.Integer(), nullable=False, server_default="0"))

    # Objections generated before the connectivity check saw chains whose
    # mechanisms did not describe the graph — the adversary was criticising a
    # text that was not the theory. They feed objection_load, which feeds
    # adjusted_score, so every already-analysed project has a ranking computed
    # partly from criticism of fiction.
    #
    # Marked rather than deleted or regenerated: the objections may still be
    # sound, deleting them destroys work, and regenerating costs a model call
    # per theory across every project. Marking is cheap, loses nothing, and
    # makes the provenance visible to anyone reading them.
    op.add_column("theory_objection", sa.Column(
        "pre_connectivity_check", sa.Boolean(), nullable=False,
        server_default="false"))
    op.execute("UPDATE theory_objection SET pre_connectivity_check = true")
    # New rows are clean, so the default flips after the back-fill.
    op.alter_column("theory_objection", "pre_connectivity_check",
                    server_default="false")


def downgrade() -> None:
    op.drop_column("theory_objection", "pre_connectivity_check")
    op.drop_column("theory", "cited_links")
    op.drop_column("theory", "connected_links")
