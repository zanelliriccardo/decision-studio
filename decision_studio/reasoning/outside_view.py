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

from decision_studio.db.models import Project, ReferenceCase, Theory
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


def implied_rate(belief: float, polarity: str | None) -> float:
    """How often the reference outcome should happen, if the theory is believed.

    A theory can predict the recalled outcome ("the schedule slips") or its
    opposite ("we ship on time"). Believing the second at 85% implies the
    recalled outcome at 15%, and that is the number to set against the base
    rate. Comparing 85% with it directly would flag a theory that agrees with
    the decider's experience as contradicting it.
    """
    return 1.0 - belief if polarity == "opposite" else belief


def compare(
    case: ReferenceCase,
    polarity: str | None,
    *,
    conviction: float | None,
    model_confidence: float | None,
) -> tuple[float, str]:
    """The theory against its reference case: ``(delta, note)``.

    Measured against the decider's conviction when they have stated one: the
    outside view exists to catch *human* optimism about this case, and the
    model's confidence is only a stand-in until there is a human number.
    ``delta`` is in terms of the recalled outcome: positive means this theory
    expects it more often than it happened before.
    """
    use_conviction = conviction is not None
    belief = conviction if use_conviction else (model_confidence or 0.0)
    implied = implied_rate(belief, polarity)
    delta = implied - case.base_rate
    whose = "your conviction" if use_conviction else "the model's confidence"
    stance = (
        f"expects {case.outcome!r} not to happen" if polarity == "opposite"
        else f"expects {case.outcome!r}"
    )
    history = (
        f"you recalled {case.cases_with_outcome} of {case.cases_total} comparable "
        f"cases where {case.outcome} ({case.base_rate:.0%})"
    )
    if not is_material(delta):
        return delta, (
            f"Consistent with your experience: {history}. This theory {stance}, and "
            f"at {whose} of {belief:.0%} it implies {implied:.0%}."
        )
    more_or_less = "more often" if delta > 0 else "less often"
    return delta, (
        f"Differs from your experience: {history}. This theory {stance}; at {whose} "
        f"of {belief:.0%} it implies {implied:.0%}, {more_or_less} than before. "
        "If this case genuinely differs, say why; if not, revisit the conviction."
    )


def current_comparison(theory: Theory, conviction: float | None) -> tuple[float | None, str | None]:
    """The theory's outside-view comparison, recomputed with today's conviction.

    Falls back to what was stored at matching time when the matched case is
    gone (the recollection was re-read) or was never loaded.
    """
    case = getattr(theory, "outside_view_case", None)
    if case is None:
        return theory.outside_view_delta, theory.outside_view_note
    return compare(
        case, theory.outside_view_polarity,
        conviction=conviction, model_confidence=theory.confidence,
    )


async def extract_reference_cases(
    session: AsyncSession,
    project_id: UUID,
    recollection: str | None = None,
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

    ``None`` re-reads the recollection saved on the project; a string replaces
    it, so the summary page can show the user their own words next time.
    """
    project = await session.get(Project, project_id)
    if recollection is None:
        recollection = project.outside_view_recollection if project else None
    elif project is not None:
        project.outside_view_recollection = recollection.strip()[:4000] or None
    # The recollection used to come from a framing answer. With the
    # questionnaire gone it is supplied explicitly by whoever wants the outside
    # view — the caller has it, and inferring it from the documents would defeat
    # the purpose: the point is what *you* have seen happen before, not what the
    # uploaded material says.
    if not recollection or not str(recollection).strip():
        # Cleared: the old base rates no longer stand for anything the user said.
        await session.execute(
            delete(ReferenceCase).where(ReferenceCase.project_id == project_id)
        )
        await session.commit()
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
        f"[T{i}] {t.title}: {t.summary}"
        + (f" (predicts option {t.option_key} {t.predicted_effect} the outcome)"
           if t.option_key and t.predicted_effect else "")
        for i, t in enumerate(theories)
    )

    client = llm or get_llm_client(enable_cache=False)
    payload = await client.complete_json(
        system=OUTSIDE_VIEW_MATCH_SYSTEM,
        user=f"REFERENCE CLASSES:\n{case_lines}\n\nTHEORIES:\n{theory_lines}",
        schema=OUTSIDE_VIEW_MATCH_SCHEMA,
        max_tokens=1024,
        temperature=EXTRACTION_TEMPERATURE,
    )

    from decision_studio.reasoning.theory_value import convictions as load_convictions

    held = await load_convictions(session, project_id, {t.theory_key for t in theories})
    for theory in theories:
        # Re-matched from scratch: a match against a case that no longer exists
        # would keep flagging a number the user has since corrected.
        theory.outside_view_case = None
        theory.outside_view_polarity = None
        theory.outside_view_delta = None
        theory.outside_view_note = None

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
        polarity = "opposite" if raw.get("polarity") == "opposite" else "same"

        # The theory's belief is in "this explanation holds" terms; the base
        # rate is in "the outcome occurred" terms. They are comparable only when
        # the model says the theory is *about* that outcome, which is exactly
        # what it was asked, and only once turned the same way round.
        conviction = held.get(str(theory.theory_key))
        delta, note = compare(
            case, polarity,
            conviction=conviction.current if conviction else None,
            model_confidence=theory.confidence,
        )
        theory.outside_view_case = case
        theory.outside_view_polarity = polarity
        theory.outside_view_delta = delta
        theory.outside_view_note = note
        checked += 1
        if is_material(delta):
            diverging += 1

    await session.commit()

    logger.info(
        "Outside view check: %d theories checked, %d diverging materially",
        checked, diverging,
    )
    return {"cases": len(cases), "checked": checked, "diverging": diverging}
