"""Verify at startup that the database matches the code.

Without this, a missing migration surfaces as ``relation "document" does not
exist`` in the middle of an unrelated request — a stack trace forty frames deep
that names a table but not the reason it is absent. Worse, once one statement
fails the transaction is poisoned, so every later error in that request reads
``current transaction is aborted``, which points at the wrong place entirely.

The check runs once, costs one query, and turns all of that into a line saying
which tables are missing and which command creates them.

It warns rather than refusing to start. A deployment that is briefly ahead of
its database should still serve the endpoints that work, and a hard failure here
would take down a running service over a table that half the application never
touches.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from decision_studio.db.models import Base

logger = logging.getLogger(__name__)


async def check_schema(engine: AsyncEngine) -> list[str]:
    """Compare the live schema with the models.

    Returns a list of human-readable problems; empty means the schema is current.
    A database that cannot be reached is reported as a problem rather than
    raising, since the caller is starting up and has nothing better to do with
    an exception.
    """
    def compare(sync_conn) -> list[str]:
        """Diff the live schema against the models, on a sync connection."""
        inspector = inspect(sync_conn)
        present = set(inspector.get_table_names())
        problems: list[str] = []

        for table in Base.metadata.sorted_tables:
            if table.name not in present:
                problems.append(f"missing table: {table.name}")
                continue
            live = {c["name"]: c for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name not in live:
                    problems.append(f"missing column: {table.name}.{column.name}")
                    continue

                # Two width checks. Both catch the same shape of bug: a column
                # narrow enough for every small run and too narrow for the first
                # large one, failing mid-transaction with a message that names
                # neither the table nor the declaration that disagrees.
                #
                # Nothing else about types is compared. SQLAlchemy and the
                # driver disagree about spelling often enough that a general
                # comparison produces noise, and noise in a startup check is
                # how a real warning gets ignored.
                declared_dim = getattr(column.type, "dim", None)
                actual_dim = getattr(live[column.name]["type"], "dim", None)
                if (
                    declared_dim is not None
                    and actual_dim is not None
                    and declared_dim != actual_dim
                ):
                    problems.append(
                        f"wrong vector width: {table.name}.{column.name} is "
                        f"{actual_dim} in the database, {declared_dim} in the model"
                    )

                # A model that says Text against a column that says varchar(n):
                # the value fits until it does not, and the failure lands in the
                # middle of a long pipeline rather than at startup.
                declared_len = getattr(column.type, "length", "absent")
                actual_len = getattr(live[column.name]["type"], "length", "absent")
                if declared_len is None and isinstance(actual_len, int):
                    problems.append(
                        f"too narrow: {table.name}.{column.name} is "
                        f"varchar({actual_len}) in the database but unbounded "
                        f"text in the model"
                    )
        return problems

    try:
        async with engine.connect() as conn:
            return await conn.run_sync(compare)
    except Exception as exc:
        return [f"could not read the schema: {exc}"]


def report(problems: list[str]) -> None:
    """Log the outcome once, in terms that name the fix."""
    if not problems:
        logger.info("Database schema is up to date")
        return

    # Truncated: twenty missing columns from one absent migration is a wall of
    # text that hides the one line that matters.
    shown = problems[:8]
    remainder = len(problems) - len(shown)

    logger.error(
        "The database is behind the code — %d item(s) the application expects "
        "do not exist:\n  %s%s\n\n"
        "  Run:  alembic upgrade head\n\n"
        "Until then, requests touching these will fail with "
        "'relation ... does not exist', and anything sharing their transaction "
        "will fail afterwards with 'current transaction is aborted'.",
        len(problems),
        "\n  ".join(shown),
        f"\n  ... and {remainder} more" if remainder else "",
    )
