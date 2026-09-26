"""Synthetic and field experiments.

**Synthetic**: cast the room the decision has to survive, put the proposal in
front of each stakeholder, and collect what they would say. This answers *"will
this survive contact with the people who must agree, and what will they object
to"* — a real question for any decision that has to be sold, and one you can
answer today rather than in ninety days.

**Field**: design a real test that could actually be run. This is the only one
that produces evidence about the world.

The distinction is enforced in code, not merely documented. ``execute_synthetic``
never touches ``Theory.confidence``. What it does is promote substantive
stakeholder objections into :class:`TheoryObjection`, where the existing
adversarial machinery already discounts rank and lets the user overrule — so a
simulated CFO's cost objection is treated exactly like any other criticism:
visible, costed, and dismissible. What it must never do is look like proof.

If that seems over-cautious, consider the alternative: a system that runs five
simulated stakeholders, reports "4 of 5 support this", and raises the theory's
confidence accordingly. Nothing about the world was observed. The number would be
a measurement of the model's own agreeableness, presented to an executive as
evidence.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from decision_studio.db.models import (
    Experiment,
    ExperimentPersona,
    ExperimentResponse,
    Theory,
    TheoryObjection,
)
from decision_studio.llm.client import LLMClient, get_llm_client
from decision_studio.llm.prompts import language_instruction
from decision_studio.llm.prompts.experiments import (
    FIELD_EXPERIMENT_SCHEMA,
    FIELD_EXPERIMENT_SYSTEM,
    PERSONA_SCHEMA,
    PERSONA_SYSTEM,
    REACTION_SCHEMA,
    REACTION_SYSTEM,
)
from decision_studio.reasoning.adversary import (
    CONTESTED_THRESHOLD,
    adjusted_score,
    objection_load,
)
from decision_studio.reasoning.decision_context import (
    decision_objective,
    render_objective,
)
from decision_studio.reasoning.decision_anchor import project_anchor
from decision_studio.reasoning.theory_value import record_evidence

logger = logging.getLogger(__name__)

#: Personas need range to disagree with each other.
PERSONA_TEMPERATURE = 0.8

#: Each stakeholder argues from their own position, so range again.
REACTION_TEMPERATURE = 0.7

#: A design must be concrete and runnable, so much less range.
DESIGN_TEMPERATURE = 0.3

#: Severity assigned to an objection promoted from a simulated stakeholder.
#: Deliberately below CONTESTED_THRESHOLD: one simulated person disliking a
#: proposal must not, on its own, mark a theory contested. Several of them can.
SIMULATED_OBJECTION_SEVERITY = 0.35


class ExperimentError(ValueError):
    """Raised when an experiment cannot be designed or run."""


async def _reload(session: AsyncSession, experiment_id: UUID) -> Experiment:
    """Re-read an experiment with its collections refreshed.

    ``populate_existing`` is required: the session keeps ``expire_on_commit``
    off, so an already-loaded (and now stale) collection would survive a plain
    re-query and the caller would see the state from before the write.
    """
    result = await session.execute(
        select(Experiment)
        .where(Experiment.id == experiment_id)
        .options(selectinload(Experiment.personas), selectinload(Experiment.responses))
        .execution_options(populate_existing=True)
    )
    return result.scalars().one()


async def _theory_and_objective(
    session: AsyncSession, project_id: UUID, theory_id: UUID
) -> tuple[Theory, str | None]:
    """One theory with the project's stated decision."""
    result = await session.execute(
        select(Theory)
        .where(Theory.id == theory_id, Theory.project_id == project_id)
        .options(selectinload(Theory.claim_links))
    )
    theory = result.scalars().first()
    if theory is None:
        raise LookupError(f"Theory {theory_id} not found in project")
    return theory, await decision_objective(session, project_id)


async def design_synthetic(
    session: AsyncSession,
    project_id: UUID,
    theory_id: UUID,
    *,
    llm: LLMClient | None = None,
) -> Experiment:
    """Cast the room for a theory, without running it yet.

    Personas are grounded in the decision frame: the user has already said who
    must be convinced and what they believe. Inventing a cast from nothing would
    simulate a room that does not exist.

    Raises:
        LookupError: unknown theory.
    """
    theory, objective = await _theory_and_objective(session, project_id, theory_id)

    decision = objective or "(decision not stated)"
    audience = None
    authority = None

    parts = [render_objective(objective)] if objective else []
    parts.append(f"THE DECISION: {decision}")
    parts.append(f"THE PROPOSAL: {theory.title}\n{theory.summary}")
    parts.append(f"THE RECOMMENDED ACTION: {theory.recommendation}")
    if audience:
        parts.append(f"WHO THE USER SAYS MUST BE CONVINCED: {audience}")
    if authority:
        parts.append(f"THE USER'S AUTHORITY: {authority}")
    parts.append("Cast the stakeholders whose reaction to this actually matters.")

    client = llm or get_llm_client(enable_cache=False)
    payload = await client.complete_json(
        system=PERSONA_SYSTEM,
        user="\n\n".join(p for p in parts if p) + language_instruction(theory.summary),
        schema=PERSONA_SCHEMA,
        max_tokens=2048,
        temperature=PERSONA_TEMPERATURE,
    )

    experiment = Experiment(
        project_id=project_id,
        theory_id=theory_id,
        kind="synthetic",
        hypothesis=f"The stakeholders who must agree will accept: {theory.title}",
        design=(
            "Each stakeholder is shown the proposal and the recommended action, "
            "and reacts from their own role and stake. This tests whether the "
            "proposal survives the room -- not whether it is true."
        ),
        status="designed",
    )
    session.add(experiment)

    for raw in (payload.get("personas") or [])[:5]:
        if not isinstance(raw, dict):
            continue
        name = (raw.get("name") or "").strip()
        if not name:
            continue
        experiment.personas.append(
            ExperimentPersona(
                name=name[:200],
                role=(raw.get("role") or "").strip(),
                stake=(raw.get("stake") or "").strip(),
                prior_position=(raw.get("prior_position") or "").strip() or None,
                grounded_in_frame=bool(raw.get("from_user_frame")),
            )
        )

    if not experiment.personas:
        raise ExperimentError("No stakeholders could be identified for this theory.")

    await session.commit()

    return await _reload(session, experiment.id)


async def execute_synthetic(
    session: AsyncSession,
    project_id: UUID,
    experiment_id: UUID,
    *,
    llm: LLMClient | None = None,
    concurrency: int = 3,
) -> Experiment:
    """Run the room, and promote substantive objections into the adversarial log.

    Deliberately does NOT change the theory's confidence. Simulated agreement is
    not evidence; simulated objections are worth surfacing precisely because they
    are cheap to obtain and expensive to meet unprepared.

    Raises:
        LookupError: unknown experiment.
        ExperimentError: the experiment has no cast, or is a field experiment.
    """
    result = await session.execute(
        select(Experiment)
        .where(Experiment.id == experiment_id, Experiment.project_id == project_id)
        .options(selectinload(Experiment.personas), selectinload(Experiment.responses))
    )
    experiment = result.scalars().first()
    if experiment is None:
        raise LookupError(f"Experiment {experiment_id} not found in project")
    if experiment.kind != "synthetic":
        raise ExperimentError("Only synthetic experiments can be simulated.")
    if not experiment.personas:
        raise ExperimentError("This experiment has no stakeholders to simulate.")

    theory, objective = await _theory_and_objective(session, project_id, experiment.theory_id)
    decision = objective or "(decision not stated)"

    client = llm or get_llm_client(enable_cache=False)
    semaphore = asyncio.Semaphore(concurrency)

    async def react(persona: ExperimentPersona) -> tuple[ExperimentPersona, dict | None]:
        """Ask one simulated stakeholder how they would respond to a theory."""
        prior = f"\nWHAT YOU ALREADY THINK: {persona.prior_position}" if persona.prior_position else ""
        user = (
            f"YOU ARE: {persona.name} -- {persona.role}\n"
            f"YOUR STAKE: {persona.stake}{prior}\n\n"
            f"THE DECISION ON THE TABLE: {decision}\n\n"
            f"THE PROPOSAL: {theory.title}\n{theory.summary}\n\n"
            f"THE RECOMMENDED ACTION: {theory.recommendation}\n\n"
            "React as this person would in the room."
        ) + language_instruction(theory.summary)

        async with semaphore:
            try:
                return persona, await client.complete_json(
                    system=REACTION_SYSTEM,
                    user=user,
                    schema=REACTION_SCHEMA,
                    max_tokens=1024,
                    temperature=REACTION_TEMPERATURE,
                )
            except Exception as exc:  # pragma: no cover - provider dependent
                logger.warning("Persona %s failed to react: %s", persona.name, exc)
                return persona, None

    outcomes = await asyncio.gather(*(react(p) for p in experiment.personas))

    # Clear any previous run: a re-execution replaces its results.
    for old in list(experiment.responses):
        await session.delete(old)

    counts = {"supports": 0, "opposes": 0, "neutral": 0}
    promoted = 0

    for persona, payload in outcomes:
        if payload is None:
            continue
        verdict = payload.get("verdict")
        if verdict not in counts:
            verdict = "neutral"
        counts[verdict] += 1

        objection_text = (payload.get("key_objection") or "").strip()
        session.add(
            ExperimentResponse(
                experiment_id=experiment.id,
                persona_id=persona.id,
                verdict=verdict,
                reaction=(payload.get("reaction") or "").strip(),
                key_objection=objection_text or None,
                would_need=(payload.get("would_need") or "").strip() or None,
            )
        )

        # A stakeholder's objection is a criticism like any other: it goes where
        # criticisms go, costs rank there, and can be dismissed by the user.
        if objection_text and verdict != "supports":
            session.add(
                TheoryObjection(
                    theory_id=theory.id,
                    objection=f"[{persona.name}] {objection_text}",
                    kind="incentive" if persona.stake else "other",
                    severity=SIMULATED_OBJECTION_SEVERITY,
                )
            )
            promoted += 1

    experiment.support_count = counts["supports"]
    experiment.oppose_count = counts["opposes"]
    experiment.neutral_count = counts["neutral"]
    experiment.status = "executed"
    experiment.executed_at = datetime.now(timezone.utc)
    experiment.summary = (
        f"{counts['supports']} would support, {counts['opposes']} would oppose, "
        f"{counts['neutral']} undecided. This measures how the argument lands, "
        f"not whether it is right."
    )

    await session.flush()

    # Recompute the theory's objection load, since we may have added to it.
    # Confidence itself is untouched -- see the module docstring.
    if promoted:
        live = (
            await session.execute(
                select(TheoryObjection).where(TheoryObjection.theory_id == theory.id)
            )
        ).scalars().all()
        load = objection_load(live)
        theory.objection_load = load
        theory.contested = load >= CONTESTED_THRESHOLD
        theory.adjusted_score = adjusted_score(theory.confidence, load)

    await session.commit()

    logger.info(
        "Synthetic experiment %s: %d support, %d oppose, %d neutral, "
        "%d objections promoted",
        experiment.id, counts["supports"], counts["opposes"], counts["neutral"], promoted,
    )

    return await _reload(session, experiment.id)


async def design_field(
    session: AsyncSession,
    project_id: UUID,
    theory_id: UUID,
    *,
    llm: LLMClient | None = None,
) -> Experiment:
    """Propose a real test that could actually be run.

    Returns an experiment whose ``design`` is empty and whose ``summary`` gives
    the reason when no meaningful test fits inside the decision's horizon. That
    is a genuine finding, not a failure: it tells the user the decision must be
    made on judgement.

    Raises:
        LookupError: unknown theory.
    """
    theory, objective = await _theory_and_objective(session, project_id, theory_id)

    decision = objective or "(decision not stated)"
    anchor = await project_anchor(session, project_id)
    deadline = (anchor or {}).get("deadline") or None
    constraints = "; ".join((anchor or {}).get("constraints", [])) or None
    change_mind = None

    parts = [
        f"THE DECISION: {decision}",
        f"THE THEORY TO TEST: {theory.title}\n{theory.summary}",
    ]
    if deadline:
        parts.append(f"THE DECISION IS DUE: {deadline}")
    if constraints:
        parts.append(f"HARD CONSTRAINTS: {constraints}")
    if change_mind:
        parts.append(f"THE USER SAYS THIS WOULD CHANGE THEIR MIND: {change_mind}")
    parts.append("Design a real test that could be run before the decision is due.")

    client = llm or get_llm_client(enable_cache=False)
    payload = await client.complete_json(
        system=FIELD_EXPERIMENT_SYSTEM,
        user="\n\n".join(parts) + language_instruction(theory.summary),
        schema=FIELD_EXPERIMENT_SCHEMA,
        max_tokens=1536,
        temperature=DESIGN_TEMPERATURE,
    )

    not_feasible = (payload.get("not_feasible_reason") or "").strip()
    design = (payload.get("design") or "").strip()

    experiment = Experiment(
        project_id=project_id,
        theory_id=theory_id,
        kind="field",
        hypothesis=(payload.get("hypothesis") or theory.title).strip(),
        design=design,
        measure=(payload.get("measure") or "").strip() or None,
        cost_estimate=(payload.get("cost_estimate") or "").strip()[:200] or None,
        duration_days=_safe_int(payload.get("duration_days")),
        status="designed" if design else "abandoned",
        summary=not_feasible or (payload.get("main_confound") or "").strip() or None,
    )
    session.add(experiment)
    await session.commit()

    if not design:
        logger.info(
            "No feasible field test for theory %s: %s", theory_id, not_feasible
        )

    return await _reload(session, experiment.id)


#: A field result's default likelihood ratio. Real tests, so a refutation
#: counts strongly; support counts less, because a test can pass for reasons
#: unrelated to the theory.
FIELD_RESULTS = ("supports", "refutes", "inconclusive")
DEFAULT_FIELD_LR = {"supports": 2.0, "refutes": 0.25, "inconclusive": 1.0}


async def record_field_result(
    session: AsyncSession,
    project_id: UUID,
    experiment_id: UUID,
    result: str,
    *,
    likelihood_ratio: float | None = None,
    note: str | None = None,
    event: str | None = None,
) -> Experiment:
    """Record what a field experiment found, and let it move conviction.

    This is the path the module docstring promises and nothing implemented: a
    real test is the one kind of experiment allowed to change what the decider
    believes. It moves *conviction*, the user's belief (reasoning/theory_value.py),
    and leaves the model's confidence alone. A synthetic experiment has no such
    path, by design.

    Raises:
        LookupError: unknown experiment.
        ValueError: not a field experiment, or unknown result.
    """
    if result not in FIELD_RESULTS:
        raise ValueError(f"Result must be one of {', '.join(FIELD_RESULTS)}")
    experiment = (await session.execute(
        select(Experiment).where(
            Experiment.id == experiment_id, Experiment.project_id == project_id
        )
    )).scalars().first()
    if experiment is None:
        raise LookupError(f"Experiment {experiment_id} not found in project")
    if experiment.kind != "field":
        raise ValueError("Only a field experiment observes the world")

    theory = await session.get(Theory, experiment.theory_id)
    experiment.status = "executed"
    experiment.executed_at = datetime.now(timezone.utc)
    experiment.summary = (note or "").strip()[:2000] or f"Result: {result}"
    if result == "supports":
        experiment.support_count = 1
    elif result == "refutes":
        experiment.oppose_count = 1
    else:
        experiment.neutral_count = 1

    if theory is not None:
        await record_evidence(
            session, project_id, theory.theory_key,
            likelihood_ratio if likelihood_ratio is not None else DEFAULT_FIELD_LR[result],
            source="field_experiment", source_id=experiment.id,
            note=f"Field test {result}: {experiment.hypothesis}",
            event=event,
            commit=False,
        )
    await session.commit()
    return await _reload(session, experiment.id)


async def list_experiments(
    session: AsyncSession, project_id: UUID, theory_id: UUID | None = None
) -> list[Experiment]:
    """Experiments for a project, newest first."""
    stmt = (
        select(Experiment)
        .where(Experiment.project_id == project_id)
        .options(selectinload(Experiment.personas), selectinload(Experiment.responses))
        .order_by(Experiment.created_at.desc())
    )
    if theory_id is not None:
        stmt = stmt.where(Experiment.theory_id == theory_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _safe_int(value: Any) -> int | None:
    """An int within bounds, or the fallback."""
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, min(730, numeric)) or None
