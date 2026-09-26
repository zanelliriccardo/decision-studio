"""Theories of value: coverage of options, and the decider's conviction.

## Conviction is not confidence

``Theory.confidence`` is the model's estimate, and everything in this codebase
treats it with suspicion: it is shown as a band, discounted by objections, and
never raised by a simulated experiment. *Conviction* is the decider's own degree
of belief that the theory holds — the quantity the theory-based view says a
decision actually turns on, and the one Bocconi's Aristotle asks for alongside
each causal map.

It is stated once, as a **prior**, and then moves only through things observed
in the world: a tripwire firing or not, a field experiment's result, a tested
link. Each observation is entered as a **likelihood ratio** — how much more
likely the observation is if the theory is true than if it is false — and the
update is Bayes' rule in odds form::

    posterior odds = prior odds x LR1 x LR2 x ...

Odds form makes the history replayable and order-independent, so the stored
rows are the record and the current conviction is always recomputed from them.

## Which evidence counts

Evidence recorded *after* the latest prior is applied to it. Evidence recorded
before it is shown and not applied: someone restating their conviction after
seeing a test has already taken the test into account, and applying it again
would count it twice. Evidence recorded before any prior waits, visibly, for
one.

## Likelihood ratios are elicited, with defaults

Asking for a likelihood ratio directly produces bad numbers, as asking for a
probability does. The UI offers five verbal steps (``LIKELIHOOD_SCALE``); a
tripwire supplies a default from its direction (``tripwire_likelihood``). Every
one is a hand-chosen, uncalibrated convention, like the thresholds in HANDOVER
§10 — exposed so it can be argued with.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_studio.db.models import Theory, TheoryBelief

#: Bounds on any stated or computed conviction. Certainty cannot be updated —
#: odds of 0 or infinity absorb every likelihood ratio — so nobody may state it.
MIN_CONVICTION = 0.01
MAX_CONVICTION = 0.99

#: The verbal scale offered for a likelihood ratio. Symmetric in log-odds, so
#: "strongly for" and "strongly against" cancel exactly.
LIKELIHOOD_SCALE: dict[str, float] = {
    "strongly_for": 4.0,
    "for": 2.0,
    "neutral": 1.0,
    "against": 0.5,
    "strongly_against": 0.25,
}

#: Bounds on any likelihood ratio accepted from a client.
MIN_LR = 1 / 20
MAX_LR = 20.0

SOURCES = ("elicited", "tripwire", "field_experiment", "link_hypothesis")


def clamp_probability(value: float) -> float:
    return max(MIN_CONVICTION, min(MAX_CONVICTION, float(value)))


def clamp_lr(value: float) -> float:
    return max(MIN_LR, min(MAX_LR, float(value)))


def bayes_update(prior: float, likelihood_ratios: Iterable[float]) -> float:
    """Posterior probability from a prior and likelihood ratios, in odds form."""
    p = clamp_probability(prior)
    log_odds = math.log(p / (1 - p)) + sum(math.log(clamp_lr(lr)) for lr in likelihood_ratios)
    posterior = 1 / (1 + math.exp(-log_odds))
    return clamp_probability(posterior)


def tripwire_likelihood(direction: str, observed: bool) -> float:
    """The default likelihood ratio of a tripwire outcome.

    A falsifier that fires is strong evidence against (the user committed in
    advance that it would change their mind). One that does not fire is mild
    evidence for: the theory survived a test it could have failed, but absence
    of an observation is weaker than presence. A confirmer is the mirror image.
    """
    if direction == "confirms":
        return LIKELIHOOD_SCALE["strongly_for"] if observed else 1 / 1.5
    return LIKELIHOOD_SCALE["strongly_against"] if observed else 1.5


@dataclass
class ConvictionStep:
    """One piece of evidence and where it left the conviction."""

    id: str
    likelihood_ratio: float
    source: str
    source_id: str | None
    note: str | None
    created_at: Any
    applied: bool
    after: float | None


@dataclass
class Conviction:
    """A theory's conviction, replayed from its history."""

    theory_key: str
    prior: float | None = None
    prior_method: str | None = None
    prior_at: Any = None
    current: float | None = None
    steps: list[ConvictionStep] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "theory_key": self.theory_key,
            "prior": self.prior,
            "prior_method": self.prior_method,
            "prior_at": self.prior_at,
            "current": self.current,
            "steps": [step.__dict__ for step in self.steps],
        }


def replay(theory_key: str, rows: list[TheoryBelief]) -> Conviction:
    """Recompute a conviction from its stored rows, oldest first."""
    ordered = sorted(rows, key=lambda r: (r.created_at is None, r.created_at))
    priors = [r for r in ordered if r.kind == "prior" and r.value is not None]
    latest = priors[-1] if priors else None

    conviction = Conviction(theory_key=theory_key)
    if latest is not None:
        conviction.prior = latest.value
        conviction.prior_method = latest.method
        conviction.prior_at = latest.created_at
        conviction.current = latest.value

    for row in ordered:
        if row.kind != "evidence" or row.likelihood_ratio is None:
            continue
        applied = latest is not None and _after(row, latest)
        if applied:
            conviction.current = bayes_update(conviction.current, [row.likelihood_ratio])
        conviction.steps.append(ConvictionStep(
            id=str(row.id),
            likelihood_ratio=row.likelihood_ratio,
            source=row.source,
            source_id=str(row.source_id) if row.source_id else None,
            note=row.note,
            created_at=row.created_at,
            applied=applied,
            after=conviction.current if applied else None,
        ))
    return conviction


def _after(row: TheoryBelief, prior: TheoryBelief) -> bool:
    if row.created_at is None or prior.created_at is None:
        return True
    return row.created_at >= prior.created_at


async def convictions(
    session: AsyncSession, project_id: UUID, theory_keys: Iterable[UUID | str]
) -> dict[str, Conviction]:
    """Convictions for several theories, keyed by theory key."""
    keys = {UUID(str(k)) for k in theory_keys}
    if not keys:
        return {}
    rows = (await session.execute(
        select(TheoryBelief).where(
            TheoryBelief.project_id == project_id,
            TheoryBelief.theory_key.in_(keys),
        )
    )).scalars().all()
    grouped: dict[str, list[TheoryBelief]] = {str(k): [] for k in keys}
    for row in rows:
        grouped[str(row.theory_key)].append(row)
    return {key: replay(key, group) for key, group in grouped.items()}


async def _require_theory_key(session: AsyncSession, project_id: UUID, theory_key: UUID) -> None:
    found = await session.scalar(
        select(Theory.id).where(Theory.project_id == project_id, Theory.theory_key == theory_key).limit(1)
    )
    if found is None:
        raise LookupError(f"Theory {theory_key} not found in project")


async def state_prior(
    session: AsyncSession,
    project_id: UUID,
    theory_key: UUID,
    value: float,
    *,
    method: str = "direct",
    note: str | None = None,
) -> Conviction:
    """Record the decider's conviction before (further) evidence.

    Raises:
        LookupError: the theory is not in the project.
    """
    await _require_theory_key(session, project_id, theory_key)
    session.add(TheoryBelief(
        project_id=project_id,
        theory_key=theory_key,
        kind="prior",
        value=clamp_probability(value),
        source="elicited",
        method=method if method in ("lottery", "direct") else "direct",
        note=(note or "").strip()[:2000] or None,
    ))
    await session.commit()
    return (await convictions(session, project_id, [theory_key]))[str(theory_key)]


async def record_evidence(
    session: AsyncSession,
    project_id: UUID,
    theory_key: UUID,
    likelihood_ratio: float,
    *,
    source: str,
    source_id: UUID | None = None,
    note: str | None = None,
    commit: bool = True,
) -> None:
    """Record an observation's likelihood ratio against a theory.

    Never called for a synthetic experiment: simulated stakeholders agreeing is
    a measurement of the model, not of the world (see reasoning/experiments.py).
    """
    if source not in SOURCES or source == "elicited":
        raise ValueError(f"Evidence cannot come from '{source}'")
    if source_id is not None:
        # One observation, one piece of evidence. Correcting a recorded result
        # (a tripwire marked "happened" by mistake, a link re-tested) replaces
        # the earlier row; adding a second would count the same observation
        # twice and compound it into the conviction.
        await session.execute(
            delete(TheoryBelief).where(
                TheoryBelief.project_id == project_id,
                TheoryBelief.theory_key == theory_key,
                TheoryBelief.source == source,
                TheoryBelief.source_id == source_id,
            )
        )
    session.add(TheoryBelief(
        project_id=project_id,
        theory_key=theory_key,
        kind="evidence",
        likelihood_ratio=clamp_lr(likelihood_ratio),
        source=source,
        source_id=source_id,
        note=(note or "").strip()[:2000] or None,
    ))
    if commit:
        await session.commit()


def option_coverage(
    anchor: dict[str, Any] | None, theories: list[Any]
) -> list[dict[str, Any]]:
    """For each option, how many current theories argue for and against it.

    An option no theory addresses is the most important row: the graph is silent
    about one of the choices, and a recommendation between options where one was
    never examined is not a comparison.
    """
    rows = []
    for option in (anchor or {}).get("options", []):
        bound = [t for t in theories if getattr(t, "option_key", None) == option["key"]]
        rows.append({
            "key": option["key"],
            "label": option["label"],
            "achieves": sum(1 for t in bound if t.predicted_effect == "achieves"),
            "threatens": sum(1 for t in bound if t.predicted_effect == "threatens"),
            "unclear": sum(1 for t in bound if t.predicted_effect not in ("achieves", "threatens")),
            "reaching_outcome": sum(1 for t in bound if getattr(t, "reaches_outcome", False)),
        })
    return rows
