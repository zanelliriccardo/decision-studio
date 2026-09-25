"""Adversarial review and tripwires: the discipline that replaces experiments.

Two services, both applied *after* theories exist.

``challenge_theories`` runs a separate call briefed to demolish each theory,
without ever showing it the theory's own persuasive text. The resulting
objections are stored, aggregated into ``Theory.objection_load``, and — this is
the part that is usually skipped — **discount the theory's rank**. An objection
that costs nothing is decoration; ``adjusted_score`` is what the panel orders by.

``generate_tripwires`` converts each theory into something that can be proved
wrong: concrete observations, with dates, that the user commits to checking. A
theory with no tripwire is an assertion about an unknowable future. A theory
with one is a bet that can be lost, which is the only form of empirical
discipline available when experiments are impossible.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from decision_studio.db.models import (
    Claim,
    Theory,
    TheoryObjection,
    TheoryTripwire,
)
from decision_studio.llm.client import LLMClient, get_llm_client
from decision_studio.llm.prompts import language_instruction
from decision_studio.llm.prompts.adversary import (
    ADVERSARY_SCHEMA,
    ADVERSARY_SYSTEM,
    TRIPWIRE_SCHEMA,
    TRIPWIRE_SYSTEM,
)
from decision_studio.reasoning.decision_context import (
    decision_objective,
    render_objective,
)

logger = logging.getLogger(__name__)

#: Objections want range; a deterministic critic finds the same flaw every time.
ADVERSARY_TEMPERATURE = 0.7

#: Tripwires must be concrete, so less range than the adversary.
TRIPWIRE_TEMPERATURE = 0.4

#: How much a fully-objected theory is discounted. At 0.5, a theory with
#: objection_load 1.0 keeps half its score -- objections are meant to demote,
#: not annihilate, since the adversary is also just a language model.
OBJECTION_WEIGHT = 0.5

#: objection_load above which a theory is flagged contested in the UI.
CONTESTED_THRESHOLD = 0.45

VALID_KINDS = (
    "common_cause",
    "single_source",
    "reversal",
    "scope",
    "timing",
    "incentive",
    "other",
)


def objection_load(objections: list[Any]) -> float:
    """Mean severity of live objections, 0-1.

    Mean rather than sum: three mild objections should not outweigh one fatal
    one, and summing would make the number depend on how verbose the adversary
    happened to be.
    """
    live = [o for o in objections if not getattr(o, "dismissed", False)]
    if not live:
        return 0.0
    return min(1.0, sum(float(o.severity or 0.0) for o in live) / len(live))


def adjusted_score(confidence: float, load: float) -> float:
    """Confidence discounted by the weight of surviving objections."""
    return max(0.0, min(1.0, float(confidence) * (1.0 - OBJECTION_WEIGHT * float(load))))


def _chain_text(theory: Theory, claims_by_id: dict[str, Claim]) -> str:
    """The causal chain in plain text -- no theory prose, by design.

    Gaps are stated. This text is the entire basis for the adversary's
    objections, and before connectivity was checked it was routinely a chain
    whose mechanisms described something else entirely — so the objections
    generated from it were criticism of a text that was not the theory. An
    unmarked gap here would reproduce that in a smaller way: the adversary would
    attack a leap it could not see was a leap.
    """
    steps: list[str] = []
    previous_claim: str | None = None

    for step in theory.causal_chain or []:
        if not isinstance(step, dict):
            continue
        if step.get("claim_id"):
            claim = claims_by_id.get(str(step["claim_id"]))
            if previous_claim is not None:
                steps.append(
                    "  -> (NO VERIFIED LINK: the mechanism cited here does not "
                    "join these two claims and was dropped)"
                )
            steps.append(f"- {claim.text if claim else step.get('label', '?')}")
            previous_claim = str(step["claim_id"])
        elif step.get("edge_id"):
            steps.append(f"  -> (because: {step.get('label', 'unspecified mechanism')})")
            previous_claim = None
    if steps:
        return "\n".join(steps)
    return "\n".join(
        f"- {claims_by_id[str(link.claim_id)].text}"
        for link in theory.claim_links
        if str(link.claim_id) in claims_by_id
    )


async def _load_context(
    session: AsyncSession, project_id: UUID
) -> tuple[dict[str, Claim], str | None]:
    """Claims by id, and the stated decision if there is one."""
    claims = (
        await session.execute(select(Claim).where(Claim.project_id == project_id))
    ).scalars().all()
    return {str(c.id): c for c in claims}, await decision_objective(session, project_id)


async def challenge_theories(
    session: AsyncSession,
    project_id: UUID,
    *,
    llm: LLMClient | None = None,
    concurrency: int = 3,
) -> dict[str, Any]:
    """Attack every current theory, and make the objections cost rank.

    Returns a report with per-theory objection counts and how many theories the
    critique demoted.
    """
    result = await session.execute(
        select(Theory)
        .where(Theory.project_id == project_id, Theory.is_current.is_(True))
        .options(selectinload(Theory.claim_links), selectinload(Theory.edge_links))
    )
    theories = list(result.scalars().all())
    if not theories:
        return {"theories": 0, "objections": 0, "contested": 0}

    claims_by_id, objective = await _load_context(session, project_id)
    decision = objective or "(decision not stated)"
    audience = None
    situation = render_objective(objective)

    client = llm or get_llm_client(enable_cache=False)
    semaphore = asyncio.Semaphore(concurrency)

    async def attack(theory: Theory) -> tuple[Theory, dict[str, Any] | None]:
        """Ask the model to demolish one theory, seeing its structure but not its prose."""
        chain = _chain_text(theory, claims_by_id)
        parts = [situation] if situation else []
        parts.append(f"THE DECISION: {decision}")
        if audience:
            parts.append(f"WHO MUST BE CONVINCED: {audience}")
        parts.append(f"THE CAUSAL CHAIN BEING RELIED ON:\n{chain}")
        parts.append("Argue that acting on this chain would be a mistake.")
        user = "\n\n".join(parts) + language_instruction(chain)

        async with semaphore:
            try:
                return theory, await client.complete_json(
                    system=ADVERSARY_SYSTEM,
                    user=user,
                    schema=ADVERSARY_SCHEMA,
                    max_tokens=2048,
                    temperature=ADVERSARY_TEMPERATURE,
                )
            except Exception as exc:  # pragma: no cover - provider dependent
                logger.warning("Adversary failed for theory %s: %s", theory.id, exc)
                return theory, None

    outcomes = await asyncio.gather(*(attack(t) for t in theories))

    total_objections = 0
    contested_count = 0

    for theory, payload in outcomes:
        if payload is None:
            continue

        # Replace previous objections: they belonged to an earlier version.
        existing = (
            await session.execute(
                select(TheoryObjection).where(TheoryObjection.theory_id == theory.id)
            )
        ).scalars().all()
        for row in existing:
            await session.delete(row)

        stored: list[TheoryObjection] = []
        for raw in (payload.get("objections") or [])[:4]:
            if not isinstance(raw, dict):
                continue
            text = (raw.get("objection") or "").strip()
            if not text:
                continue
            kind = raw.get("kind")
            if kind not in VALID_KINDS:
                kind = "other"
            try:
                severity = max(0.0, min(1.0, float(raw.get("severity", 0.5))))
            except (TypeError, ValueError):
                severity = 0.5
            objection = TheoryObjection(
                theory_id=theory.id, objection=text, kind=kind, severity=severity
            )
            session.add(objection)
            stored.append(objection)

        load = objection_load(stored)
        theory.objection_load = load
        theory.contested = load >= CONTESTED_THRESHOLD
        theory.adjusted_score = adjusted_score(theory.confidence, load)

        total_objections += len(stored)
        if theory.contested:
            contested_count += 1

    await session.commit()

    logger.info(
        "Adversarial review: %d theories, %d objections, %d contested",
        len(theories), total_objections, contested_count,
    )
    return {
        "theories": len(theories),
        "objections": total_objections,
        "contested": contested_count,
    }


async def generate_tripwires(
    session: AsyncSession,
    project_id: UUID,
    *,
    llm: LLMClient | None = None,
    concurrency: int = 3,
) -> dict[str, Any]:
    """Give every current theory something that could prove it wrong."""
    result = await session.execute(
        select(Theory)
        .where(Theory.project_id == project_id, Theory.is_current.is_(True))
        .options(selectinload(Theory.claim_links))
    )
    theories = list(result.scalars().all())
    if not theories:
        return {"theories": 0, "tripwires": 0}

    claims_by_id, objective = await _load_context(session, project_id)
    decision = objective or "(decision not stated)"
    change_mind = None
    success = None
    deadline = None

    client = llm or get_llm_client(enable_cache=False)
    semaphore = asyncio.Semaphore(concurrency)

    async def propose(theory: Theory) -> tuple[Theory, dict[str, Any] | None]:
        """Ask the model for observations that would falsify one theory."""
        chain = _chain_text(theory, claims_by_id)
        parts = [
            f"THE DECISION: {decision}",
            f"THEORY: {theory.title}\n{theory.summary}",
            f"CAUSAL CHAIN:\n{chain}",
        ]
        if success:
            parts.append(f"WHAT SUCCESS WOULD LOOK LIKE: {success}")
        if change_mind:
            # The user already said what would change their mind. Start there
            # rather than inventing something less relevant.
            parts.append(f"THE USER SAYS THIS WOULD CHANGE THEIR MIND: {change_mind}")
        if deadline:
            parts.append(f"THE DECISION MUST BE MADE BY: {deadline}")
        parts.append("Propose observations that would prove this theory wrong.")
        user = "\n\n".join(parts) + language_instruction(theory.summary)

        async with semaphore:
            try:
                return theory, await client.complete_json(
                    system=TRIPWIRE_SYSTEM,
                    user=user,
                    schema=TRIPWIRE_SCHEMA,
                    max_tokens=1536,
                    temperature=TRIPWIRE_TEMPERATURE,
                )
            except Exception as exc:  # pragma: no cover - provider dependent
                logger.warning("Tripwire generation failed for %s: %s", theory.id, exc)
                return theory, None

    outcomes = await asyncio.gather(*(propose(t) for t in theories))

    now = datetime.now(timezone.utc)
    created = 0

    for theory, payload in outcomes:
        if payload is None:
            continue

        existing = (
            await session.execute(
                select(TheoryTripwire).where(
                    TheoryTripwire.theory_id == theory.id,
                    TheoryTripwire.status == "pending",
                )
            )
        ).scalars().all()
        for row in existing:
            await session.delete(row)

        for raw in (payload.get("tripwires") or [])[:3]:
            if not isinstance(raw, dict):
                continue
            observable = (raw.get("observable") or "").strip()
            if not observable:
                continue
            direction = raw.get("direction")
            if direction not in ("falsifies", "confirms"):
                direction = "falsifies"
            try:
                horizon = max(1, min(730, int(raw.get("horizon_days", 90))))
            except (TypeError, ValueError):
                horizon = 90
            session.add(
                TheoryTripwire(
                    theory_id=theory.id,
                    observable=observable,
                    direction=direction,
                    horizon_days=horizon,
                    check_by=now + timedelta(days=horizon),
                )
            )
            created += 1

    await session.commit()
    logger.info(
        "Tripwires: %d created across %d theories", created, len(theories)
    )
    return {"theories": len(theories), "tripwires": created}


async def record_observation(
    session: AsyncSession,
    project_id: UUID,
    tripwire_id: UUID,
    *,
    observed: bool,
    note: str | None = None,
) -> TheoryTripwire:
    """Record whether a tripwire fired, and mark the theory accordingly.

    A falsifying tripwire that fires makes its theory stale: the thing the user
    said would change their mind has happened, so the conclusion should be
    revisited rather than left standing.

    Raises:
        LookupError: unknown tripwire, or it belongs to another project.
    """
    row = (
        await session.execute(
            select(TheoryTripwire)
            .join(Theory, Theory.id == TheoryTripwire.theory_id)
            .where(
                TheoryTripwire.id == tripwire_id,
                Theory.project_id == project_id,
            )
        )
    ).scalars().first()
    if row is None:
        raise LookupError(f"Tripwire {tripwire_id} not found in project")

    row.status = "observed" if observed else "not_observed"
    row.observed_at = datetime.now(timezone.utc)
    row.observed_note = (note or "").strip() or None

    theory = await session.get(Theory, row.theory_id)
    if theory is not None:
        falsified = observed and row.direction == "falsifies"
        confirmed_absent = not observed and row.direction == "confirms"
        if falsified or confirmed_absent:
            theory.is_stale = True
            theory.stale_reason = (
                f"A tripwire fired against this theory: {row.observable}"
            )

    await session.commit()
    await session.refresh(row)
    return row
