"""Widen columns the models declare as Text but the schema created as varchar.

Five columns disagreed. The one that bit: ``causal_edge.time_delay``, declared
Text and created ``varchar(100)``. A model asked for "estimated time between
cause and effect" answers in prose, and on a large graph one of several hundred
answers eventually runs long — at which point the INSERT fails, the transaction
is poisoned, and a pipeline that had already done twenty minutes of work dies
with a message about string truncation.

Every one of these holds text a language model wrote. A length limit on
generated prose is a bomb with a timer set by input size: it survives every
small run and fails on the first large one.

``role`` is the exception and stays as it is: it holds one of a fixed set of
labels, so the constraint is doing real work there.

Revision ID: 018
Revises: 017
Create Date: 2026-08-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: (table, column, the varchar length it was created with)
_WIDENED = (
    ("causal_edge", "time_delay", 100),
    ("causal_edge", "temporal_window", 100),
    ("evidence", "source_title", 500),
    ("evidence", "source_url", 2048),
)


def upgrade() -> None:
    for table, column, _ in _WIDENED:
        op.alter_column(table, column, type_=sa.Text(), existing_nullable=True)


def downgrade() -> None:
    # Truncate first: narrowing a column holding longer values fails outright,
    # and a downgrade that cannot run is not a downgrade.
    for table, column, length in _WIDENED:
        op.execute(
            f"UPDATE {table} SET {column} = LEFT({column}, {length}) "
            f"WHERE LENGTH({column}) > {length}"
        )
        op.alter_column(
            table, column, type_=sa.String(length), existing_nullable=True
        )
