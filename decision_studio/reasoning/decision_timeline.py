"""The decision journal: what was believed, and what changed it.

Built from records that already carry their own timestamps — nothing is
back-dated or inferred:

=============================  ==============================================
Event                          Source
=============================  ==============================================
Analysis created               ``project.created_at``
Claim / link added, reviewed,  ``graph_operation`` (the review audit log)
excluded, strength overridden
Theories generated             ``theory_revision``
Conviction stated / restated   ``theory_belief`` priors
Tripwire happened / did not    ``theory_tripwire.observed_at``
Link test held / refuted       ``link_hypothesis.observed_at``
Field test result              ``experiment.executed_at``
Comparable cases recorded      ``reference_case.created_at``
Comparison changed, priorities ``event_timeline`` rows written by this module
changed                        (source ``decision_journal``)
=============================  ==============================================

The last row is the only thing recorded specifically for the journal: nothing
else keeps a history of the option comparison. A comparison is snapshotted when
it is viewed and differs materially from the last snapshot (an option-implied
outcome moved by ``MATERIAL_OUTCOME_SHIFT`` or more, or the weighted view's
verdict changed), so its date is when the change was first *seen*, and the
journal says so.

Observations are shown with the conviction they moved (before → after), so the
journal answers "what did we believe, and what evidence changed it?". A
conviction change of ``MATERIAL_CONVICTION_SHIFT`` or more, a fired falsifier,
a refuted link, a comparison change and a priority change are *material*; the
summary shows those by default.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_studio.db.models import (
    CausalEdge,
    Claim,
    EventTimeline,
    Experiment,
    GraphOperation,
    LinkHypothesis,
    Project,
    ReferenceCase,
    Theory,
    TheoryBelief,
    TheoryRevision,
    TheoryTripwire,
)
from decision_studio.reasoning import theory_value

JOURNAL_SOURCE = "decision_journal"
MATERIAL_CONVICTION_SHIFT = 0.10
MATERIAL_OUTCOME_SHIFT = 0.05
MAX_EVENTS = 200


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{round(value * 100)}%"


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _event(at, kind: str, title: str, *, detail: str | None = None,
           belief_change: str | None = None, material: bool = False,
           ref: dict[str, str] | None = None) -> dict[str, Any] | None:
    at = _aware(at)
    if at is None:
        return None  # no timestamp, no event: never invent one
    return {"at": at.isoformat(), "kind": kind, "title": title, "detail": detail,
            "belief_change": belief_change, "material": material, "ref": ref or {}}


# ── Comparison snapshots ────────────────────────────────────────────────────


def comparison_fingerprint(comparison: Any) -> dict[str, Any] | None:
    """The parts of a comparison whose change is worth a journal entry."""
    if comparison is None or comparison.unavailable:
        return None
    headline = None
    pair = set(comparison.headline_pair or [])
    for row in comparison.robustness:
        if {row["a"], row["b"]} == pair and row.get("weighted"):
            headline = {"higher": row["weighted"]["higher"], "verdict": row["weighted"]["verdict"]}
    return {
        "outcomes": {o.key: {k: v["point"] for k, v in o.outcomes.items()} for o in comparison.options},
        "labels": {o.key: o.label for o in comparison.options},
        "outcome_labels": dict(comparison.outcomes),
        "headline": headline,
    }


def describe_change(before: dict[str, Any] | None, after: dict[str, Any]) -> list[str]:
    """Material differences between two fingerprints, as sentences. Empty when none."""
    if before is None:
        return ["First comparison of the options on the causal map."]
    changes = []
    for option, values in after["outcomes"].items():
        for key, value in values.items():
            old = before.get("outcomes", {}).get(option, {}).get(key)
            if old is not None and abs(value - old) >= MATERIAL_OUTCOME_SHIFT:
                changes.append(
                    f"{key} under {option} {after['labels'].get(option, '')}: "
                    f"{_pct(old)} → {_pct(value)}".replace("  ", " "))
    old_head, new_head = before.get("headline"), after.get("headline")
    if old_head != new_head and (old_head or new_head):
        def say(head):
            if not head or not head.get("higher"):
                return "no material difference"
            return f"{head['higher']} {head['verdict']}"
        changes.append(f"Weighted view: {say(old_head)} → {say(new_head)}")
    return changes


async def record_comparison_if_changed(session: AsyncSession, project_id: UUID, comparison: Any) -> bool:
    """Snapshot the comparison when it differs materially from the last one seen."""
    fingerprint = comparison_fingerprint(comparison)
    if fingerprint is None:
        return False
    last = (await session.execute(
        select(EventTimeline)
        .where(EventTimeline.project_id == project_id, EventTimeline.source == JOURNAL_SOURCE,
               EventTimeline.event_type == "comparison")
        .order_by(EventTimeline.event_date.desc()).limit(1)
    )).scalars().first()
    changes = describe_change((last.metadata_ or {}).get("fingerprint") if last else None, fingerprint)
    if not changes:
        return False
    await record(session, project_id, "comparison",
                 "Option comparison changed" if last else "Options first compared",
                 "; ".join(changes), {"fingerprint": fingerprint})
    return True


async def record(session: AsyncSession, project_id: UUID, kind: str, title: str,
                 detail: str | None = None, payload: dict[str, Any] | None = None) -> None:
    """A journal entry for a change nothing else keeps a history of."""
    session.add(EventTimeline(
        project_id=project_id, title=title[:500], description=detail, event_type=kind,
        event_date=datetime.now(timezone.utc), source=JOURNAL_SOURCE, metadata_=payload or {},
    ))
    await session.commit()


# ── The timeline ────────────────────────────────────────────────────────────

OPERATION_TITLES = {
    "add_claim": "Claim added",
    "add_edge": "Link added",
    "disable": "Excluded from reasoning",
    "restore": "Restored to reasoning",
    "override_strength": "Link strength overridden",
    "clear_strength_override": "Link strength override cleared",
    "edit_mechanism": "Link mechanism edited",
    "reverse_edge": "Link reversed",
}


async def decision_timeline(session: AsyncSession, project_id: UUID) -> dict[str, Any]:
    """Every dated event, oldest first, with the belief each one moved."""
    project = await session.get(Project, project_id)
    if project is None:
        raise LookupError(f"Project {project_id} not found")
    events: list[dict[str, Any] | None] = []
    events.append(_event(project.created_at, "created", "Analysis created",
                         detail=getattr(project, "decision_objective", None) or project.title,
                         material=True))

    claims = {str(c.id): c.text for c in (await session.execute(
        select(Claim).where(Claim.project_id == project_id))).scalars()}
    edges = {str(e.id): e for e in (await session.execute(
        select(CausalEdge).where(CausalEdge.project_id == project_id))).scalars()}

    def element(op: GraphOperation) -> str:
        if op.claim_id:
            return claims.get(str(op.claim_id), "a claim")
        edge = edges.get(str(op.edge_id)) if op.edge_id else None
        if edge is None:
            return "a link"
        return f"{claims.get(str(edge.source_claim_id), '?')} → {claims.get(str(edge.target_claim_id), '?')}"

    for op in (await session.execute(
        select(GraphOperation).where(GraphOperation.project_id == project_id)
    )).scalars():
        kind = op.operation_type
        if kind == "set_note":
            continue  # a note moves no belief
        undo = kind.startswith("undo:")
        base = kind.removeprefix("undo:")
        if base == "set_review_status":
            status = (op.after_state or {}).get("review_status", "reviewed")
            title = f"Marked {str(status).replace('_', ' ')}"
        else:
            title = OPERATION_TITLES.get(base, base.replace("_", " ").capitalize())
        change = None
        if base == "override_strength":
            change = (f"strength {_pct((op.before_state or {}).get('strength_override') or (op.before_state or {}).get('strength'))}"
                      f" → {_pct((op.after_state or {}).get('strength_override'))}")
        events.append(_event(
            op.created_at, "graph", ("Undone: " if undo else "") + title,
            detail=element(op), belief_change=change,
            material=base in ("disable", "override_strength") and not op.undone_at,
            ref={"claim_id": str(op.claim_id) if op.claim_id else "",
                 "edge_id": str(op.edge_id) if op.edge_id else ""},
        ))

    for rev in (await session.execute(
        select(TheoryRevision).where(TheoryRevision.project_id == project_id)
    )).scalars():
        summary = rev.change_summary or {}
        counts = {k: len(summary.get(f"{k}_theory_ids", []) or []) for k in ("new", "changed", "superseded")}
        parts = [f"{n} {k}" for k, n in counts.items() if n]
        events.append(_event(
            rev.created_at, "theories",
            "Theories generated" if rev.revision == 1 else f"Theories regenerated (revision {rev.revision})",
            detail=", ".join(parts) or None,
            material=bool(counts["new"] or counts["superseded"]),
        ))

    theories = list((await session.execute(
        select(Theory).where(Theory.project_id == project_id))).scalars())
    title_by_id = {t.id: t.title for t in theories}
    title_by_key: dict[str, str] = {}
    for t in sorted(theories, key=lambda t: t.version):
        title_by_key[str(t.theory_key)] = t.title

    # Conviction: priors as events; observations attach their before → after
    # to the tripwire / link test / field test that produced them.
    rows = list((await session.execute(
        select(TheoryBelief).where(TheoryBelief.project_id == project_id))).scalars())
    by_key: dict[str, list[TheoryBelief]] = {}
    for row in rows:
        by_key.setdefault(str(row.theory_key), []).append(row)
    moved: dict[str, tuple[float | None, float | None]] = {}
    for key, group in by_key.items():
        title = title_by_key.get(key, "a theory")
        previous_prior = None
        for row in sorted((r for r in group if r.kind == "prior"), key=lambda r: _aware(r.created_at) or datetime.min.replace(tzinfo=timezone.utc)):
            change = (f"{_pct(previous_prior)} → {_pct(row.value)}" if previous_prior is not None
                      else f"stated at {_pct(row.value)}")
            material = previous_prior is None or abs((row.value or 0) - previous_prior) >= MATERIAL_CONVICTION_SHIFT
            events.append(_event(row.created_at, "conviction",
                                 "Conviction restated" if previous_prior is not None else "Conviction stated",
                                 detail=title, belief_change=f"conviction {change}", material=material))
            previous_prior = row.value
        conviction = theory_value.replay(key, group)
        current = conviction.prior
        for step in conviction.steps:
            if step.applied:
                moved[step.source_id or step.id] = (current, step.after)
                current = step.after

    def conviction_change(source_id: Any, title: str) -> tuple[str | None, bool]:
        before, after = moved.get(str(source_id), (None, None))
        if before is None or after is None:
            return None, False
        return (f"conviction in “{title}” {_pct(before)} → {_pct(after)}",
                abs(after - before) >= MATERIAL_CONVICTION_SHIFT)

    for tw in (await session.execute(
        select(TheoryTripwire).join(Theory, Theory.id == TheoryTripwire.theory_id)
        .where(Theory.project_id == project_id, TheoryTripwire.observed_at.is_not(None))
    )).scalars():
        title = title_by_id.get(tw.theory_id, "a theory")
        happened = tw.status == "observed"
        change, material = conviction_change(tw.id, title)
        falsified = happened and tw.direction == "falsifies"
        events.append(_event(
            tw.observed_at, "tripwire",
            f"Tripwire {'happened' if happened else 'did not happen'}: {tw.observable}",
            detail=f"“{title}” marked out of date" if falsified else (tw.observed_note or None),
            belief_change=change, material=material or falsified, ref={"tripwire_id": str(tw.id)},
        ))

    for h in (await session.execute(
        select(LinkHypothesis).where(LinkHypothesis.project_id == project_id,
                                     LinkHypothesis.observed_at.is_not(None))
    )).scalars():
        title = title_by_key.get(str(h.theory_key), "a theory")
        change, material = conviction_change(h.id, title)
        events.append(_event(
            h.observed_at, "link_test", f"Link test {h.status}: {h.statement}",
            detail=f"“{title}” marked out of date" if h.status == "refuted" else (h.observed_note or None),
            belief_change=change, material=material or h.status == "refuted",
            ref={"hypothesis_id": str(h.id)},
        ))

    for f in (await session.execute(
        select(Experiment).where(Experiment.project_id == project_id, Experiment.kind == "field",
                                 Experiment.executed_at.is_not(None))
    )).scalars():
        title = title_by_id.get(f.theory_id, "a theory")
        change, material = conviction_change(f.id, title)
        events.append(_event(f.executed_at, "field_test", f"Field test run: {f.hypothesis}",
                             detail=f.summary, belief_change=change, material=material,
                             ref={"experiment_id": str(f.id)}))

    cases = list((await session.execute(
        select(ReferenceCase).where(ReferenceCase.project_id == project_id))).scalars())
    if cases:
        first = min((c.created_at for c in cases if c.created_at), default=None)
        events.append(_event(first, "outside_view", f"Comparable cases recorded ({len(cases)})",
                             detail="; ".join(f"{c.outcome}: {c.cases_with_outcome}/{c.cases_total}" for c in cases)))

    for row in (await session.execute(
        select(EventTimeline).where(EventTimeline.project_id == project_id,
                                    EventTimeline.source == JOURNAL_SOURCE)
    )).scalars():
        seen = " (first seen when the comparison was viewed)" if row.event_type == "comparison" else ""
        events.append(_event(row.event_date, row.event_type, row.title,
                             detail=(row.description or "") + seen or None, material=True))

    dated = sorted((e for e in events if e is not None), key=lambda e: e["at"])
    return {
        "events": dated[-MAX_EVENTS:],
        "total": len(dated),
        "material": sum(1 for e in dated if e["material"]),
    }
