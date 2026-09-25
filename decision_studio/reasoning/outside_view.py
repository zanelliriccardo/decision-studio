"""The outside view: comparing a theory against how comparable cases went.

Kahneman's finding is that people asked to forecast a project reliably take the
*inside* view — they reason from this project's specifics, which always feel
exceptional — and ignore the *outside* view, the base rate of how similar things
turned out. The outside view is usually the better predictor, and it is the only
empirical anchor a one-off strategic decision has.

Decision Studio already asked the user for it: *"Have you seen similar decisions before,
and how did they turn out?"* Until now that answer was rendered into a prompt and
nothing more, which is the weakest possible use of it — the model reads it, may
or may not weigh it, and nobody can tell which.

This module makes it operative. The free-text recollection is parsed into
explicit base rates, and generated theories are then *checked against* them. A
theory that puts 30% on a slip, in a project whose owner remembers two out of two
comparable integrations slipping, is flagged — not overruled. The user may have a
good reason this case differs. They should have to give it.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from decision_studio.db.models import ReferenceCase, Theory
from decision_studio.llm.client import LLMClient, get_llm_client
from decision_studio.llm.prompts.outside_view import (
    OUTSIDE_VIEW_MATCH_SCHEMA,
    OUTSIDE_VIEW_MATCH_SYSTEM,
    REFERENCE_CLASS_SCHEMA,
    REFERENCE_CLASS_SYSTEM,
)
from decision_studio.reasoning.decision_context import decision_objective

logger = logging.getLogger(__name__)

#: Extraction should be literal, not creative: we are reading numbers out of a
#: sentence, not estimating anything.
EXTRACTION_TEMPERATURE = 0.1

#: Divergence beyond this counts as the inside-view error worth flagging.
#: Below it, the difference is within the noise of both estimates.
MATERIAL_DIVERGENCE = 0.20


def base_rate(cases_with_outcome: int, cases_total: int) -> float:
    """Frequency, guarding the degenerate cases."""
    if cases_total <= 0:
        return 0.0
    return max(0.0, min(1.0, cases_with_outcome / cases_total))


def is_material(delta: float | None) -> bool:
    """True when a theory departs from its reference class enough to matter."""
    return delta is not None and abs(delta) >= MATERIAL_DIVERGENCE


def divergence_note(
    case: ReferenceCase, confidence: float, delta: float
) -> str:
    """A sentence the user can act on, in their own terms."""
    direction = "more optimistic than" if delta > 0 else "more pessimistic than"
    return (
        f"This theory is {direction} your own experience: you recalled "
        f"{case.cases_with_outcome} of {case.cases_total} comparable cases where "
        f"{case.outcome} ({case.base_rate:.0%}), but this theory implies "
        f"{confidence:.0%}. If this case genuinely differs, say why."
    )


async def extract_reference_cases(
    session: AsyncSession,
    project_id: UUID,
    recollection: str | None,
    *,
    llm: LLMClient | None = None,
) -> list[ReferenceCase]:
    """Turn the user's recollection of similar decisions into base rates.

    Replaces any previously extracted cases: the answer is the source of truth,
    and stale numbers from an earlier version of it would silently compete.

    Args:
        recollection: how comparable cases turned out, in the user's own words.

    Returns an empty list when nothing was supplied, or what was supplied
    carries no countable cases. Inventing a denominator would be
    worse than having none.
    """
    # The recollection used to come from a framing answer. With the
    # questionnaire gone it is supplied explicitly by whoever wants the outside
    # view — the caller has it, and inferring it from the documents would defeat
    # the purpose: the point is what *you* have seen happen before, not what the
    # uploaded material says.
    if not recollection or not str(recollection).strip():
        return []

    decision = await decision_objective(session, project_id) or ""

    client = llm or get_llm_client(enable_cache=False)
    payload = await client.complete_json(
        system=REFERENCE_CLASS_SYSTEM,
        user=f"THE DECISION: {decision}\n\nWHAT THE USER RECALLS:\n{recollection}",
        schema=REFERENCE_CLASS_SCHEMA,
        max_tokens=1024,
        temperature=EXTRACTION_TEMPERATURE,
    )

    await session.execute(
        delete(ReferenceCase).where(ReferenceCase.project_id == project_id)
    )

    created: list[ReferenceCase] = []
    for raw in (payload.get("cases") or [])[:6]:
        if not isinstance(raw, dict):
            continue
        outcome = (raw.get("outcome") or "").strip()
        if not outcome:
            continue
        try:
            total = int(raw.get("cases_total", 0))
            with_outcome = int(raw.get("cases_with_outcome", 0))
        except (TypeError, ValueError):
            continue
        if total <= 0 or with_outcome < 0 or with_outcome > total:
            # A malformed count is worse than no count: it would anchor the user
            # on a number nobody actually stated.
            logger.info("Discarding malformed reference case: %s", raw)
            continue

        case = ReferenceCase(
            project_id=project_id,
            outcome=outcome,
            cases_total=total,
            cases_with_outcome=with_outcome,
            base_rate=base_rate(with_outcome, total),
            basis=(raw.get("basis") or "").strip() or None,
            source="user_recall",
        )
        session.add(case)
        created.append(case)

    await session.commit()
    for case in created:
        await session.refresh(case)

    logger.info(
        "Outside view: %d reference case(s) extracted for project %s",
        len(created), project_id,
    )
    return created


async def list_reference_cases(
    session: AsyncSession, project_id: UUID
) -> list[ReferenceCase]:
    """Reference cases recorded for a project."""
    result = await session.execute(
        select(ReferenceCase)
        .where(ReferenceCase.project_id == project_id)
        .order_by(ReferenceCase.created_at)
    )
    return list(result.scalars().all())


def render_reference_cases(cases: list[ReferenceCase]) -> str:
    """Render base rates for a generation prompt."""
    if not cases:
        return ""
    lines = [
        "# Outside view (the user's own experience of comparable cases)",
        "Treat these as the starting point. A theory that departs from them needs "
        "a stated reason why this case is different.",
    ]
    for case in cases:
        lines.append(
            f"- {case.outcome}: {case.cases_with_outcome} of {case.cases_total} "
            f"comparable cases ({case.base_rate:.0%})"
        )
    return "\n".join(lines) + "\n"


async def check_theories_against_base_rates(
    session: AsyncSession,
    project_id: UUID,
    *,
    llm: LLMClient | None = None,
) -> dict[str, Any]:
    """Flag theories that depart from the user's own comparable cases.

    Matching a theory to a reference class is a judgement, so a model does it —
    but only the *matching*. The arithmetic and the threshold stay in code, and
    a theory the model cannot match is left alone rather than forced onto the
    nearest class.
    """
    cases = await list_reference_cases(session, project_id)
    if not cases:
        return {"cases": 0, "checked": 0, "diverging": 0}

    result = await session.execute(
        select(Theory)
        .where(Theory.project_id == project_id, Theory.is_current.is_(True))
        .options(selectinload(Theory.claim_links))
    )
    theories = list(result.scalars().all())
    if not theories:
        return {"cases": len(cases), "checked": 0, "diverging": 0}

    case_lines = "\n".join(
        f"[R{i}] {c.outcome} -- {c.cases_with_outcome}/{c.cases_total} "
        f"({c.base_rate:.0%})"
        for i, c in enumerate(cases)
    )
    theory_lines = "\n".join(
        f"[T{i}] {t.title}: {t.summary}" for i, t in enumerate(theories)
    )

    client = llm or get_llm_client(enable_cache=False)
    payload = await client.complete_json(
        system=OUTSIDE_VIEW_MATCH_SYSTEM,
        user=f"REFERENCE CLASSES:\n{case_lines}\n\nTHEORIES:\n{theory_lines}",
        schema=OUTSIDE_VIEW_MATCH_SCHEMA,
        max_tokens=1024,
        temperature=EXTRACTION_TEMPERATURE,
    )

    diverging = 0
    checked = 0
    for raw in payload.get("matches") or []:
        if not isinstance(raw, dict):
            continue
        try:
            theory_index = int(str(raw.get("theory_ref", "")).lstrip("Tt"))
            case_index = int(str(raw.get("reference_ref", "")).lstrip("Rr"))
        except (TypeError, ValueError):
            continue
        if not (0 <= theory_index < len(theories)) or not (0 <= case_index < len(cases)):
            continue

        theory = theories[theory_index]
        case = cases[case_index]

        # The theory's confidence is in "this explanation holds" terms; the base
        # rate is in "the outcome occurred" terms. They are comparable only when
        # the model says the theory is *about* that outcome, which is exactly
        # what it was asked.
        delta = (theory.confidence or 0.0) - case.base_rate
        theory.outside_view_delta = delta
        checked += 1

        if is_material(delta):
            theory.outside_view_note = divergence_note(case, theory.confidence, delta)
            diverging += 1
        else:
            theory.outside_view_note = (
                f"Consistent with your experience: {case.cases_with_outcome} of "
                f"{case.cases_total} comparable cases where {case.outcome}."
            )

    await session.commit()

    logger.info(
        "Outside view check: %d theories checked, %d diverging materially",
        checked, diverging,
    )
    return {"cases": len(cases), "checked": checked, "diverging": diverging}
