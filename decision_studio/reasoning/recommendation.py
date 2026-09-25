"""Synthesising a recommendation from the whole set of theories.

A theory explains part of the situation. A decision needs one answer, and
arriving at it means weighing the explanations against each other — noticing
where two of them point the same way, where they point in opposite directions,
and where one has been so heavily objected to that leaning on it would be
unwise.

That weighing is the hardest part of reading an analysis and the part the reader
came for. Presenting the theories in a list and stopping leaves it undone.

Two properties are load-bearing:

* **It runs over the finished set**, not per theory. A per-theory
  recommendation is what ``Theory.recommendation`` already is, and stacking
  those produces contradictory advice with nothing to resolve it.
* **Objections travel with their theory.** A recommendation resting on a
  contested explanation is weaker than one resting on an unattacked one, and the
  model cannot account for that if it never sees the attacks.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_studio.db.models import (
    DecisionRecommendation,
    Project,
    Theory,
    TheoryObjection,
    TheoryTripwire,
)
from decision_studio.llm.client import LLMClient, get_llm_client
from decision_studio.llm.prompts import language_instruction
from decision_studio.llm.prompts.recommendation import (
    RECOMMENDATION_SCHEMA,
    RECOMMENDATION_SYSTEM,
)
from decision_studio.reasoning.calibration import band
from decision_studio.reasoning.decision_context import decision_objective
from decision_studio.reasoning.theories import list_current_theories

logger = logging.getLogger(__name__)

#: Synthesis is judgement, not invention. Some range, well short of the
#: adversary's.
TEMPERATURE = 0.4

VALID_CONFIDENCE = ("low", "moderate", "high")


class RecommendationError(RuntimeError):
    """Raised when no recommendation could be produced."""


def _render_theory(theory: Theory, index: int, objections, tripwires) -> str:
    """One theory as the synthesiser sees it: claim, caveats, and what would
    disprove it — all three, because a recommendation that ignores the caveats
    is worse than no recommendation."""
    parts = [
        f"[T{index}] {theory.title}",
        f"  {theory.summary}",
        f"  confidence: {band(theory.confidence)}; impact: {theory.business_impact}",
    ]
    if theory.recommendation:
        parts.append(f"  its own recommendation: {theory.recommendation}")

    live = [o for o in objections if not o.dismissed]
    if live:
        parts.append("  objections raised against it:")
        parts.extend(f"    - [{o.kind}] {o.objection}" for o in live)
    else:
        parts.append("  no objections were raised against it")

    if theory.weak_assumptions:
        parts.append("  weak assumptions:")
        parts.extend(f"    - {a}" for a in theory.weak_assumptions)

    pending = [t for t in tripwires if t.status == "pending"]
    if pending:
        parts.append("  what would prove it wrong:")
        parts.extend(f"    - {t.observable}" for t in pending)

    if theory.outside_view_note:
        parts.append(f"  against comparable cases: {theory.outside_view_note}")

    return "\n".join(parts)


async def generate_recommendation(
    session: AsyncSession,
    project_id: UUID,
    *,
    llm: LLMClient | None = None,
) -> DecisionRecommendation:
    """Weigh every current theory and say what to do.

    Raises:
        LookupError: unknown project.
        RecommendationError: no theories to reason from.
    """
    project = await session.get(Project, project_id)
    if project is None:
        raise LookupError(f"Project {project_id} not found")

    theories = await list_current_theories(session, project_id)
    if not theories:
        raise RecommendationError(
            "There are no theories to base a recommendation on."
        )

    theory_ids = [t.id for t in theories]
    objections: dict[UUID, list[TheoryObjection]] = {}
    tripwires: dict[UUID, list[TheoryTripwire]] = {}

    for row in (
        await session.execute(
            select(TheoryObjection).where(TheoryObjection.theory_id.in_(theory_ids))
        )
    ).scalars().all():
        objections.setdefault(row.theory_id, []).append(row)
    for row in (
        await session.execute(
            select(TheoryTripwire).where(TheoryTripwire.theory_id.in_(theory_ids))
        )
    ).scalars().all():
        tripwires.setdefault(row.theory_id, []).append(row)

    objective = await decision_objective(session, project_id)
    rendered = "\n\n".join(
        _render_theory(
            theory, index, objections.get(theory.id, []), tripwires.get(theory.id, [])
        )
        for index, theory in enumerate(theories)
    )

    user = "\n\n".join(
        part
        for part in (
            f"THE DECISION: {objective}" if objective else
            # Said rather than omitted: without it the model would pick an
            # implicit decision of its own and answer that instead.
            "THE DECISION: not stated. Say what the analysis supports, and note "
            "that no decision was specified.",
            f"THE EXPLANATIONS FOUND:\n\n{rendered}",
            "Weigh these together and say what should be done.",
        )
        if part
    ) + language_instruction(theories[0].summary)

    client = llm or get_llm_client(enable_cache=False)
    payload = await client.complete_json(
        system=RECOMMENDATION_SYSTEM,
        user=user,
        schema=RECOMMENDATION_SCHEMA,
        max_tokens=2048,
        temperature=TEMPERATURE,
    )

    text = (payload.get("recommendation") or "").strip()
    if not text:
        raise RecommendationError("The model returned no recommendation.")

    confidence = payload.get("confidence")
    if confidence not in VALID_CONFIDENCE:
        confidence = "moderate"

    # Replace rather than append: a recommendation is about the current set of
    # theories, and keeping older ones invites reading advice derived from
    # explanations that no longer exist.
    await session.execute(
        delete(DecisionRecommendation).where(
            DecisionRecommendation.project_id == project_id
        )
    )

    recommendation = DecisionRecommendation(
        project_id=project_id,
        recommendation=text,
        reasoning=(payload.get("reasoning") or "").strip(),
        depends_on=[
            str(d).strip() for d in (payload.get("depends_on") or []) if str(d).strip()
        ] or None,
        against_it=(payload.get("against_it") or "").strip() or None,
        next_step=(payload.get("next_step") or "").strip() or None,
        confidence=confidence,
        theory_ids=[str(t) for t in theory_ids],
        graph_revision=project.graph_revision or 1,
    )
    session.add(recommendation)
    await session.commit()
    await session.refresh(recommendation)

    logger.info(
        "Recommendation for project %s from %d theories (confidence: %s)",
        project_id, len(theories), confidence,
    )
    return recommendation


async def get_recommendation(
    session: AsyncSession, project_id: UUID
) -> DecisionRecommendation | None:
    """The current recommendation, if one has been generated."""
    result = await session.execute(
        select(DecisionRecommendation).where(
            DecisionRecommendation.project_id == project_id
        )
    )
    return result.scalars().first()


async def is_stale(
    session: AsyncSession, recommendation: DecisionRecommendation
) -> bool:
    """Whether the theories have moved on since this was written.

    Compared by theory id rather than by revision number: theories can be
    regenerated without the graph changing, and a recommendation derived from a
    superseded set is describing explanations the reader can no longer find.
    """
    current = await list_current_theories(session, recommendation.project_id)
    return {str(t.id) for t in current} != set(recommendation.theory_ids or [])
