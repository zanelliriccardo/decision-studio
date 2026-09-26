"""What would change my mind: the evidence already set up, consolidated per option.

Tripwires, link tests and field tests each hang off one theory, and each theory
argues that one option achieves or threatens a success criterion. Read that way
round, every one of them is a signal for or against an *option*:

=====================  ==========================  ====================
Signal                 Outcome that counts         Effect on the theory
=====================  ==========================  ====================
tripwire (falsifies)   it happens                  weakens
tripwire (confirms)    it happens                  strengthens
link test              the link is refuted         weakens
link test              the link holds              strengthens
field test             the test refutes            weakens
field test             the test supports           strengthens
=====================  ==========================  ====================

A theory that says the option *achieves* the outcome passes its effect on to
the option unchanged; one that says it *threatens* it inverts it (weakening
"Q3 threatens the date" strengthens the case for Q3). Theories bound to no
option are left out: they bear on every option alike.

Nothing is invented. Every signal is an existing tripwire, link test or field
test, referenced by id, with the status it has now.

## Ranking

Unresolved signals first, then by

    strength × open question × on-target

* **strength** — ``|ln LR|`` of the outcome that counts, from the decisiveness
  stated for it (theory_value.tripwire_likelihood, link_tests.result_likelihood,
  experiments.DEFAULT_FIELD_LR): how far it would move conviction;
* **open question** — ``4·p·(1−p)`` of the decider's conviction in the theory
  (the model's objection-discounted score until one is stated), floored at 0.25:
  a signal about a theory already near certain changes little;
* **on-target** — 1 when the theory's chain reaches a success criterion,
  0.5 when it does not.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_studio.db.models import Experiment, TheoryTripwire
from decision_studio.reasoning.decision_anchor import project_anchor
from decision_studio.reasoning.experiments import DEFAULT_FIELD_LR
from decision_studio.reasoning.link_tests import list_hypotheses, result_likelihood
from decision_studio.reasoning.theories import list_current_theories, rank_key
from decision_studio.reasoning.theory_value import convictions, decisiveness_of, tripwire_likelihood

WEAKEN = "weaken"
STRENGTHEN = "strengthen"
MAX_PER_DIRECTION = 5
MIN_OPEN_QUESTION = 0.25


def open_question(belief: float | None) -> float:
    p = 0.5 if belief is None else max(0.0, min(1.0, belief))
    return max(MIN_OPEN_QUESTION, 4 * p * (1 - p))


def _signal(
    *, kind: str, source_id: Any, theory: Any, text: str, condition: str, lr: float,
    theory_effect: str, decisiveness: str, status: str, resolved: bool,
    fired: bool | None, belief: float | None, detail: str | None = None,
) -> dict[str, Any]:
    strength = abs(math.log(lr)) if lr > 0 else 0.0
    on_target = 1.0 if getattr(theory, "reaches_outcome", False) else 0.5
    return {
        "kind": kind,
        "id": str(source_id),
        "theory_id": str(theory.id),
        "theory_title": theory.title,
        "text": text,
        "condition": condition,
        "theory_effect": theory_effect,
        "decisiveness": decisiveness,
        "likelihood_ratio": round(lr, 4),
        "status": status,
        "resolved": resolved,
        #: True when what this signal waits for has been observed; False when
        #: the opposite was observed; None while unresolved.
        "fired": fired,
        "detail": detail,
        "score": round(strength * open_question(belief) * on_target, 4),
    }


def theory_signals(
    theory: Any,
    tripwires: list[Any],
    hypotheses: list[Any],
    field_tests: list[Any],
    belief: float | None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Every signal that bears on one theory, with its effect on the theory."""
    now = now or datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []
    for tw in tripwires:
        level = decisiveness_of(getattr(tw, "decisiveness", None))
        lr = tripwire_likelihood(tw.direction, True, level)
        if tw.status == "pending":
            overdue = tw.check_by is not None and tw.check_by < now
            status, resolved, fired = ("overdue" if overdue else "pending"), False, None
        else:
            # Tripwire statuses read as what happened, so "not observed yet"
            # (pending) and "did not happen" cannot be confused.
            status = {"observed": "happened", "not_observed": "did_not_happen"}.get(tw.status, tw.status)
            resolved = True
            fired = tw.status == "observed" if tw.status in ("observed", "not_observed") else None
        out.append(_signal(
            kind="tripwire", source_id=tw.id, theory=theory, text=tw.observable,
            condition="if it happens",
            lr=lr, theory_effect=WEAKEN if tw.direction == "falsifies" else STRENGTHEN,
            decisiveness=level, status=status, resolved=resolved, fired=fired, belief=belief,
            detail=tw.check_by.date().isoformat() if tw.check_by else None,
        ))
    for h in hypotheses:
        level = decisiveness_of(getattr(h, "decisiveness", None))
        resolved = h.status != "open"
        for result, effect, text, condition in (
            ("refuted", WEAKEN, h.refuted_if or h.statement, "if the link is refuted"),
            ("held", STRENGTHEN, h.statement, "if the link holds"),
        ):
            out.append(_signal(
                kind="link_test", source_id=h.id, theory=theory, text=text, condition=condition,
                lr=result_likelihood(result, level), theory_effect=effect, decisiveness=level,
                status="not_tested" if not resolved else h.status, resolved=resolved,
                fired=(h.status == result) if resolved and h.status != "inconclusive" else None,
                belief=belief, detail=h.cheapest_test or None,
            ))
    for f in field_tests:
        if not f.design:
            continue  # judged infeasible: nothing to run
        resolved = f.status == "executed"
        outcome = None
        if resolved:
            outcome = ("supports" if f.support_count else "refutes" if f.oppose_count
                       else "inconclusive")
        for result, effect, condition in (
            ("refutes", WEAKEN, "if the field test refutes it"),
            ("supports", STRENGTHEN, "if the field test supports it"),
        ):
            out.append(_signal(
                kind="field_test", source_id=f.id, theory=theory, text=f.hypothesis,
                condition=condition, lr=DEFAULT_FIELD_LR[result], theory_effect=effect,
                decisiveness="moderate",
                status=("not_run" if not resolved else outcome) if f.status != "abandoned" else "abandoned",
                resolved=resolved or f.status == "abandoned",
                fired=(outcome == result) if resolved and outcome != "inconclusive" else None,
                belief=belief, detail=f.measure,
            ))
    return out


def for_option(effect_on_theory: str, predicted_effect: str | None) -> str:
    """A theory-level effect, carried to the option the theory is about."""
    if predicted_effect == "threatens":
        return STRENGTHEN if effect_on_theory == WEAKEN else WEAKEN
    return effect_on_theory


def _order(signal: dict[str, Any]) -> tuple:
    return (signal["resolved"], -signal["score"], signal["kind"], signal["id"])


def consolidate(
    anchor: dict[str, Any] | None,
    theories: list[Any],
    beliefs: dict[str, float | None],
    signals_by_theory: dict[str, list[dict[str, Any]]],
    *,
    limit: int = MAX_PER_DIRECTION,
) -> list[dict[str, Any]]:
    """Per option: the theories about it, and the signals that would weaken or strengthen it."""
    result = []
    for option in (anchor or {}).get("options", []):
        bound = [t for t in theories if getattr(t, "option_key", None) == option["key"]
                 and getattr(t, "predicted_effect", None) in ("achieves", "threatens")]
        weaken: list[dict[str, Any]] = []
        strengthen: list[dict[str, Any]] = []
        for theory in bound:
            for signal in signals_by_theory.get(str(theory.id), []):
                effect = for_option(signal["theory_effect"], theory.predicted_effect)
                (weaken if effect == WEAKEN else strengthen).append(
                    {**signal, "effect": effect, "theory_predicts": theory.predicted_effect})
        weaken.sort(key=_order)
        strengthen.sort(key=_order)
        result.append({
            "key": option["key"],
            "label": option["label"],
            "theories": [
                {
                    "id": str(t.id), "title": t.title, "predicted_effect": t.predicted_effect,
                    "conviction": beliefs.get(str(t.theory_key)),
                    "model_support": t.adjusted_score if t.adjusted_score is not None else t.confidence,
                    "reaches_outcome": bool(getattr(t, "reaches_outcome", False)),
                    "is_stale": bool(t.is_stale),
                }
                for t in sorted(bound, key=lambda t: rank_key(t, beliefs.get(str(t.theory_key))))
            ],
            "weaken": weaken[:limit],
            "strengthen": strengthen[:limit],
        })
    return result


async def what_would_change_my_mind(session: AsyncSession, project_id: UUID) -> list[dict[str, Any]]:
    """The consolidated view for every option of the project's decision."""
    anchor = await project_anchor(session, project_id)
    theories = await list_current_theories(session, project_id)
    if not anchor or not theories:
        return consolidate(anchor, [], {}, {})
    ids = [t.id for t in theories]
    held = await convictions(session, project_id, [t.theory_key for t in theories])
    beliefs = {k: c.current for k, c in held.items()}

    tripwires: dict[Any, list[Any]] = {}
    for row in (await session.execute(
        select(TheoryTripwire).where(TheoryTripwire.theory_id.in_(ids))
    )).scalars():
        tripwires.setdefault(row.theory_id, []).append(row)
    fields: dict[Any, list[Any]] = {}
    for row in (await session.execute(
        select(Experiment).where(Experiment.theory_id.in_(ids), Experiment.kind == "field")
    )).scalars():
        fields.setdefault(row.theory_id, []).append(row)
    hypotheses: dict[str, list[Any]] = {}
    for row in await list_hypotheses(session, project_id):
        hypotheses.setdefault(str(row.theory_key), []).append(row)

    signals = {}
    for theory in theories:
        belief = beliefs.get(str(theory.theory_key))
        if belief is None:
            belief = theory.adjusted_score if theory.adjusted_score is not None else theory.confidence
        signals[str(theory.id)] = theory_signals(
            theory, tripwires.get(theory.id, []), hypotheses.get(str(theory.theory_key), []),
            fields.get(theory.id, []), belief,
        )
    return consolidate(anchor, theories, beliefs, signals)
