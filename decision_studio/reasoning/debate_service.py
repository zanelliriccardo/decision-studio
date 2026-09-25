"""Running debates between theories, and turning the result into work.

A debate is not a verdict. It is a routing decision: each of the three relations
sends the user somewhere different, and all three destinations already exist.

    same_story   → one theory should be superseded; nothing to compare
    orthogonal   → both may hold; the combined case is a scenario worth running
    competing    → the discriminator becomes a tripwire, or, if none is
                   feasible in time, the choice moves to whichever option
                   survives both explanations

What a debate never does is move a theory's confidence. Discovering that two
theories diverge is not evidence that either is wrong — no observation of the
world has occurred. It changes what work is worth doing, not what is believed.

Promotion to a tripwire is a separate, explicit call. The discriminator arrives
already in tripwire shape, so creating it automatically would be easy; the
reason not to is consistency. Everywhere else in this system — clarification
answers, proposed graph changes — the model proposes and the user commits. A
discriminator that silently became a commitment would be the one exception, and
exceptions to that rule are how a tool stops being trustworthy.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from decision_studio.db.models import Project, Theory, TheoryDebate, TheoryTripwire
from decision_studio.llm.client import LLMClient, get_llm_client
from decision_studio.llm.prompts import language_instruction
from decision_studio.llm.prompts.debate import DEBATE_SCHEMA, DEBATE_SYSTEM
from decision_studio.reasoning.debate import (
    StructuralComparison,
    compare_structure,
    relation_explanation,
    select_pairs,
)
from decision_studio.reasoning.decision_context import decision_objective
from decision_studio.reasoning.theories import list_current_theories

logger = logging.getLogger(__name__)

#: Finding a crux is analytical, not creative.
DEBATE_TEMPERATURE = 0.3

#: Default horizon when a discriminator is feasible but unscoped.
DEFAULT_HORIZON_DAYS = 30


class DebateError(ValueError):
    """Raised when a debate cannot be run or promoted."""


async def run_debates(
    session: AsyncSession,
    project_id: UUID,
    *,
    llm: LLMClient | None = None,
    max_theories: int = 4,
    concurrency: int = 3,
) -> dict[str, Any]:
    """Compare the leading theories pairwise.

    Structure is computed for every pair; the model is called only for the pairs
    that turn out to be genuinely in competition. On a set where most pairs are
    restatements, that is most of the cost avoided.

    Raises:
        LookupError: unknown project.
        DebateError: fewer than two current theories.
    """
    project = await session.get(Project, project_id)
    if project is None:
        raise LookupError(f"Project {project_id} not found")

    theories = await list_current_theories(session, project_id)
    if len(theories) < 2:
        raise DebateError(
            "At least two current theories are needed before they can be compared."
        )

    decision = await decision_objective(session, project_id) or ""
    deadline = None

    # Previous debates describe a graph that may have moved on.
    await session.execute(
        update(TheoryDebate)
        .where(TheoryDebate.project_id == project_id, TheoryDebate.is_stale.is_(False))
        .values(is_stale=True)
    )

    pairs = select_pairs(theories, max_theories=max_theories)
    comparisons = [(a, b, compare_structure(a, b)) for a, b in pairs]

    to_ask = [(a, b, c) for a, b, c in comparisons if c.needs_model]
    client = llm or get_llm_client(enable_cache=False)
    semaphore = asyncio.Semaphore(concurrency)

    async def ask(a: Theory, b: Theory, comparison: StructuralComparison):
        """Ask the model where two theories part company, and what would tell them apart."""
        parts = [f"THE DECISION: {decision}" if decision else ""]
        if deadline:
            parts.append(f"THE DECISION IS DUE: {deadline}")
        parts.append(f"EXPLANATION A: {a.title}\n{a.summary}")
        parts.append(f"EXPLANATION B: {b.title}\n{b.summary}")
        parts.append(
            "ESTABLISHED FROM THE GRAPH (do not re-assess):\n"
            f"- {relation_explanation(comparison)}\n"
            f"- shared links: {len(comparison.shared_edge_ids)}\n"
            f"- links unique to one or the other: {len(comparison.divergent_edge_ids)}"
        )
        parts.append("Find the crux, and what observation would separate them.")

        async with semaphore:
            try:
                return await client.complete_json(
                    system=DEBATE_SYSTEM,
                    user="\n\n".join(p for p in parts if p)
                    + language_instruction(a.summary),
                    schema=DEBATE_SCHEMA,
                    max_tokens=1536,
                    temperature=DEBATE_TEMPERATURE,
                )
            except Exception as exc:  # pragma: no cover - provider dependent
                logger.warning("Debate failed for %s vs %s: %s", a.id, b.id, exc)
                return None

    payloads = await asyncio.gather(*(ask(a, b, c) for a, b, c in to_ask))
    generated = {id(c): p for (_, _, c), p in zip(to_ask, payloads)}

    counts = {"same_story": 0, "competing": 0, "orthogonal": 0}
    with_discriminator = 0
    created: list[TheoryDebate] = []

    for theory_a, theory_b, comparison in comparisons:
        counts[comparison.relation] += 1
        payload = generated.get(id(comparison))

        debate = TheoryDebate(
            project_id=project_id,
            theory_a_id=theory_a.id,
            theory_b_id=theory_b.id,
            graph_revision=project.graph_revision or 1,
            both_possible=comparison.both_possible,
            **comparison.persisted_fields(),
        )

        if payload is not None:
            discriminator = (payload.get("discriminator") or "").strip()
            debate.crux = (payload.get("crux") or "").strip() or None
            debate.discriminator = discriminator or None
            debate.discriminator_feasible = bool(discriminator)
            debate.discriminator_horizon_days = (
                _safe_horizon(payload.get("discriminator_horizon_days"))
                if discriminator
                else None
            )
            favours = payload.get("evidence_favours")
            debate.evidence_favours = favours if favours in ("a", "b", "neither") else None
            # The model may see a shared outcome the structure alone missed.
            debate.both_possible = comparison.both_possible or bool(
                payload.get("both_possible")
            )
            if not discriminator:
                debate.crux = debate.crux or (
                    payload.get("not_feasible_reason") or ""
                ).strip() or None
            if discriminator:
                with_discriminator += 1
        else:
            # same_story, or the call failed. The structural verdict stands on
            # its own and is the useful part here anyway.
            debate.crux = relation_explanation(comparison)

        session.add(debate)
        created.append(debate)

    await session.commit()

    logger.info(
        "Debates for project %s: %d pairs (%d same story, %d competing, "
        "%d orthogonal), %d model calls, %d with a discriminator",
        project_id, len(comparisons), counts["same_story"], counts["competing"],
        counts["orthogonal"], len(to_ask), with_discriminator,
    )

    return {
        "pairs": len(comparisons),
        "same_story": counts["same_story"],
        "competing": counts["competing"],
        "orthogonal": counts["orthogonal"],
        "model_calls": len(to_ask),
        "with_discriminator": with_discriminator,
        "debate_ids": [str(d.id) for d in created],
    }


async def list_debates(
    session: AsyncSession, project_id: UUID, *, include_stale: bool = False
) -> list[TheoryDebate]:
    """Debates for a project, most decision-relevant first.

    Competing pairs with a usable discriminator lead, because they are the ones
    that generate work.
    """
    stmt = select(TheoryDebate).where(TheoryDebate.project_id == project_id)
    if not include_stale:
        stmt = stmt.where(TheoryDebate.is_stale.is_(False))
    result = await session.execute(stmt.order_by(TheoryDebate.created_at.desc()))
    debates = list(result.scalars().all())

    relation_rank = {"competing": 0, "orthogonal": 1, "same_story": 2}
    debates.sort(
        key=lambda d: (
            relation_rank.get(d.relation, 3),
            0 if d.discriminator_feasible else 1,
        )
    )
    return debates


async def promote_to_tripwire(
    session: AsyncSession, project_id: UUID, debate_id: UUID
) -> list[TheoryTripwire]:
    """Turn a discriminator into a tripwire on both theories.

    On *both*, because the observation does not test one explanation — it
    resolves a fork from which opposite actions follow. Recording it against
    only one side would lose that.

    The direction is ``falsifies``: whichever way the observation falls, one of
    the two is weakened, so both theories should be revisited when it fires.

    Raises:
        LookupError: unknown debate.
        DebateError: no usable discriminator, or already promoted.
    """
    debate = (
        await session.execute(
            select(TheoryDebate).where(
                TheoryDebate.id == debate_id, TheoryDebate.project_id == project_id
            )
        )
    ).scalars().first()
    if debate is None:
        raise LookupError(f"Debate {debate_id} not found in project")
    if not debate.discriminator or not debate.discriminator_feasible:
        raise DebateError(
            "This comparison produced no observation that could separate the two "
            "theories in time."
        )
    if debate.promoted_tripwire_at is not None:
        raise DebateError("This discriminator has already been turned into a tripwire.")

    horizon = debate.discriminator_horizon_days or DEFAULT_HORIZON_DAYS
    check_by = datetime.now(timezone.utc) + timedelta(days=horizon)

    created: list[TheoryTripwire] = []
    for theory_id in (debate.theory_a_id, debate.theory_b_id):
        tripwire = TheoryTripwire(
            theory_id=theory_id,
            observable=debate.discriminator,
            direction="falsifies",
            horizon_days=horizon,
            check_by=check_by,
            status="pending",
        )
        session.add(tripwire)
        created.append(tripwire)

    debate.promoted_tripwire_at = datetime.now(timezone.utc)
    await session.commit()
    for tripwire in created:
        await session.refresh(tripwire)

    logger.info(
        "Debate %s promoted to tripwires on both theories, due %s",
        debate_id, check_by.date(),
    )
    return created


async def mark_debates_stale(session: AsyncSession, project_id: UUID) -> int:
    """Invalidate debates after the graph or the theory set changes."""
    result = await session.execute(
        update(TheoryDebate)
        .where(TheoryDebate.project_id == project_id, TheoryDebate.is_stale.is_(False))
        .values(is_stale=True)
        .returning(TheoryDebate.id)
    )
    return len(list(result.scalars().all()))


def _safe_horizon(value: Any) -> int:
    """Days as an int within sensible bounds, or the default."""
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return DEFAULT_HORIZON_DAYS
    return max(1, min(365, numeric)) or DEFAULT_HORIZON_DAYS
