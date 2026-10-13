"""Theory generation, versioning and change comparison.

A *theory* is a decision-relevant causal explanation derived from the reviewed
graph. Theories are never overwritten: each generation run creates a new
:class:`TheoryRevision` and a new row per theory, keyed by a stable
``theory_key`` so successive versions can be compared.

Matching new output to previous theories uses the model's own
``previous_theory_key`` when it supplies a valid one, and otherwise falls back
to causal-path overlap — two theories built on mostly the same edges are two
versions of the same theory, whatever the model chose to call them.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from decision_studio.config import settings
from decision_studio.db.models import (
    Experiment,
    Project,
    Theory,
    TheoryClaim,
    TheoryEdge,
    TheoryEvidence,
    TheoryRevision,
    TheoryTripwire,
)
from decision_studio.llm.client import LLMClient, get_llm_client
from decision_studio.llm.prompts import language_instruction
from decision_studio.llm.prompts.theory_generation import (
    THEORY_GENERATION_SCHEMA,
    THEORY_GENERATION_SYSTEM,
)
from decision_studio.reasoning.context_builder import build_generation_context
from decision_studio.reasoning.decision_anchor import normalise_anchor
from decision_studio.reasoning.effective_graph import load_effective_snapshot
from decision_studio.reasoning.decision_context import (
    decision_objective,
    render_objective,
)
from decision_studio.reasoning.outside_view import list_reference_cases, render_reference_cases
from decision_studio.reasoning.validation import ValidatedTheory, validate_theories

logger = logging.getLogger(__name__)

#: Causal-path overlap above which a new theory is treated as a new version of
#: an existing one rather than a genuinely new theory.
MATCH_EDGE_OVERLAP = 0.6

#: Confidence movement below this is not worth calling a change.
MATERIAL_CONFIDENCE_DELTA = 0.05


class TheoryGenerationError(RuntimeError):
    """Raised when no storable theory could be produced."""


@dataclass
class TheoryGenerationResult:
    """Outcome of one generation or regeneration run."""

    theories: list[Theory]
    revision: TheoryRevision
    change_summary: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    #: True when no decision was stated. The theories describe the situation
    #: rather than bearing on a choice, and the user should be told which they
    #: are looking at.
    objective_missing: bool = False


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def _theory_loader_options() -> list[Any]:
    """Eager-load provenance links; loading them lazily would be an N+1."""
    return [
        selectinload(Theory.claim_links),
        selectinload(Theory.edge_links),
        selectinload(Theory.evidence_links),
    ]


async def list_current_theories(
    session: AsyncSession, project_id: UUID
) -> list[Theory]:
    """Current version of every theory, strongest decision signal first."""
    result = await session.execute(
        select(Theory)
        .where(Theory.project_id == project_id, Theory.is_current.is_(True))
        .options(*_theory_loader_options())
    )
    theories = list(result.scalars().all())
    theories.sort(key=lambda t: rank_key(t, None))
    return theories


def rank_key(theory: Theory, conviction: float | None) -> tuple:
    """Order theories by what the analysis measured, strongest first.

    1. Whether the causal chain verifiably reaches a success criterion
       (computed from the graph): a theory that never reaches the decision is
       context, however well argued.
    2. Up to date before out of date.
    3. Support: the decider's conviction once stated (the only number moved by
       observations), otherwise the objection-discounted score.

    The model's own ``business_impact`` label is deliberately not a key: it was
    the model grading its own theory, and it used to outrank everything.
    """
    support = conviction
    if support is None:
        support = theory.adjusted_score if theory.adjusted_score is not None else (theory.confidence or 0.0)
    return (not bool(getattr(theory, "reaches_outcome", False)), bool(theory.is_stale), -support)


async def get_theory(
    session: AsyncSession, project_id: UUID, theory_id: UUID
) -> Theory | None:
    """Fetch one theory, verifying it belongs to the project in the route."""
    result = await session.execute(
        select(Theory)
        .where(Theory.id == theory_id, Theory.project_id == project_id)
        .options(*_theory_loader_options())
    )
    return result.scalars().first()


async def list_theory_versions(
    session: AsyncSession, project_id: UUID, theory_key: UUID
) -> list[Theory]:
    """Every stored version of one theory, oldest first."""
    result = await session.execute(
        select(Theory)
        .where(Theory.project_id == project_id, Theory.theory_key == theory_key)
        .order_by(Theory.version)
        .options(*_theory_loader_options())
    )
    return list(result.scalars().all())


async def list_revisions(
    session: AsyncSession, project_id: UUID
) -> list[TheoryRevision]:
    """Generation history, newest first."""
    result = await session.execute(
        select(TheoryRevision)
        .where(TheoryRevision.project_id == project_id)
        .order_by(TheoryRevision.revision.desc())
    )
    return list(result.scalars().all())


async def _next_revision_number(session: AsyncSession, project_id: UUID) -> int:
    """The next revision number for a project's theory history."""
    result = await session.execute(
        select(TheoryRevision.revision)
        .where(TheoryRevision.project_id == project_id)
        .order_by(TheoryRevision.revision.desc())
        .limit(1)
    )
    latest = result.scalars().first()
    return (latest or 0) + 1


def _same_claim(candidate: ValidatedTheory, previous: Theory) -> bool:
    """Whether two versions make the same claim about the decision.

    A theory key carries the decider's conviction and every test result. If a
    theory about O1 "achieving" the outcome were matched to a regenerated one
    about O1 "threatening" it — the same links read the other way — the
    conviction stated for the first would silently transfer to its opposite.
    Unknown values on either side (theories from before options existed) do
    not block a match.
    """
    for field in ("option_key", "predicted_effect"):
        before = getattr(previous, field, None)
        after = getattr(candidate, field, None)
        if field == "predicted_effect" and "unclear" in (before, after):
            continue
        if before is not None and after is not None and before != after:
            return False
    return True


def match_previous(
    candidate: ValidatedTheory,
    previous: list[Theory],
    used_keys: set[str],
) -> Theory | None:
    """Find the previous theory a candidate continues, if any."""
    if candidate.previous_theory_key:
        for theory in previous:
            if (
                str(theory.theory_key) == candidate.previous_theory_key
                and str(theory.theory_key) not in used_keys
                and _same_claim(candidate, theory)
            ):
                return theory

    candidate_edges = set(candidate.supporting_edge_ids)
    if not candidate_edges:
        return None

    best: Theory | None = None
    best_overlap = 0.0
    for theory in previous:
        if str(theory.theory_key) in used_keys or not _same_claim(candidate, theory):
            continue
        prior_edges = {str(link.edge_id) for link in theory.edge_links}
        if not prior_edges:
            continue
        union = candidate_edges | prior_edges
        overlap = len(candidate_edges & prior_edges) / len(union)
        if overlap > best_overlap:
            best_overlap = overlap
            best = theory
    return best if best_overlap >= MATCH_EDGE_OVERLAP else None


def describe_change(
    candidate: ValidatedTheory, previous: Theory
) -> tuple[str, str | None]:
    """Classify a theory against its previous version.

    Returns ``(change_kind, explanation)`` where kind is ``changed`` or
    ``unchanged``. The explanation is written for a human reading the panel,
    and falls back to the model's own account when it supplied one.
    """
    reasons: list[str] = []

    delta = (candidate.confidence or 0.0) - (previous.confidence or 0.0)
    if abs(delta) >= MATERIAL_CONFIDENCE_DELTA:
        direction = "rose" if delta > 0 else "fell"
        reasons.append(
            f"confidence {direction} from {previous.confidence:.2f} to "
            f"{candidate.confidence:.2f}"
        )
    if candidate.status != previous.status:
        reasons.append(f"status changed from {previous.status} to {candidate.status}")
    if candidate.business_impact != previous.business_impact:
        reasons.append(
            f"business impact changed from {previous.business_impact} to "
            f"{candidate.business_impact}"
        )
    if candidate.recommendation.strip() != (previous.recommendation or "").strip():
        reasons.append("the recommended action changed")
    if (candidate.option_key, candidate.predicted_effect) != (
        getattr(previous, "option_key", None), getattr(previous, "predicted_effect", None)
    ) and (candidate.option_key or getattr(previous, "option_key", None)):
        reasons.append(
            f"it now argues that {candidate.option_key or 'no specific option'} "
            f"{candidate.predicted_effect} the outcome"
        )

    prior_edges = {str(link.edge_id) for link in previous.edge_links}
    new_edges = set(candidate.supporting_edge_ids)
    if prior_edges != new_edges:
        added = len(new_edges - prior_edges)
        removed = len(prior_edges - new_edges)
        parts = []
        if added:
            parts.append(f"{added} edge(s) added")
        if removed:
            parts.append(f"{removed} edge(s) no longer available")
        if parts:
            reasons.append("the causal chain moved: " + ", ".join(parts))

    if not reasons:
        return "unchanged", candidate.change_explanation

    explanation = "; ".join(reasons)
    if candidate.change_explanation:
        explanation = f"{explanation}. Model note: {candidate.change_explanation}"
    return "changed", explanation


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _persist_theory(
    session: AsyncSession,
    *,
    project_id: UUID,
    candidate: ValidatedTheory,
    theory_key: UUID,
    version: int,
    change_kind: str,
    change_explanation: str | None,
    graph_revision: int,
    theory_revision: int,
    generation_id: UUID,
) -> Theory:
    """Write one validated theory and its links to the database."""
    theory = Theory(
        project_id=project_id,
        theory_key=theory_key,
        title=candidate.title,
        summary=candidate.summary,
        status=candidate.status,
        confidence=candidate.confidence,
        business_impact=candidate.business_impact,
        recommendation=candidate.recommendation,
        weak_assumptions=candidate.weak_assumptions,
        causal_chain=candidate.causal_chain,
        connected_links=candidate.connected_links,
        cited_links=candidate.cited_links,
        graph_revision=graph_revision,
        theory_revision=theory_revision,
        version=version,
        is_current=True,
        is_stale=False,
        change_kind=change_kind,
        change_explanation=change_explanation,
        generation_id=generation_id,
        # Until the adversary runs, nothing has been objected to.
        adjusted_score=candidate.confidence,
        option_key=candidate.option_key,
        predicted_effect=candidate.predicted_effect,
        outcome_keys=candidate.outcome_keys or None,
        reaches_outcome=candidate.reaches_outcome,
    )
    session.add(theory)
    theory.claim_links = [
        TheoryClaim(claim_id=uuid.UUID(cid), role="supporting", position=i)
        for i, cid in enumerate(candidate.supporting_claim_ids)
    ]
    theory.edge_links = [
        TheoryEdge(edge_id=uuid.UUID(eid), role="supporting", position=i)
        for i, eid in enumerate(candidate.supporting_edge_ids)
    ]
    theory.evidence_links = [
        TheoryEvidence(evidence_id=uuid.UUID(vid), role="supporting")
        for vid in candidate.supporting_evidence_ids
    ] + [
        TheoryEvidence(evidence_id=uuid.UUID(vid), role="contradicting")
        for vid in candidate.contradicting_evidence_ids
    ]
    return theory


async def generate_theories(
    session: AsyncSession,
    project_id: UUID,
    *,
    llm: LLMClient | None = None,
    trigger: str = "generate",
    max_claims: int | None = None,
) -> TheoryGenerationResult:
    """Generate theories from the effective reviewed graph.

    The same code path serves the first generation and every regeneration; the
    only difference is that regeneration has previous theories to compare
    against.

    Raises:
        LookupError: unknown project.
        TheoryGenerationError: the graph is empty, or nothing survived validation.
    """
    # Existence first: an unknown project is a 404, not an invitation to fill
    # in a questionnaire for something that does not exist.
    project = await session.get(Project, project_id)
    if project is None:
        raise LookupError(f"Project {project_id} not found")
    anchor = normalise_anchor(getattr(project, "decision_anchor", None))

    objective = await decision_objective(session, project_id)

    snapshot = await load_effective_snapshot(project_id, session)
    if snapshot.is_empty:
        raise TheoryGenerationError(
            "The reviewed graph has no active claims. Restore or accept at least "
            "one claim before generating theories."
        )

    previous = await list_current_theories(session, project_id)

    context_kwargs: dict[str, Any] = {
        "previous_theories": previous,
        "purpose": "theories",
    }
    if max_claims is not None:
        context_kwargs["max_claims"] = max_claims

    context = build_generation_context(snapshot, **context_kwargs)
    # The frame leads: everything after it is evidence about a decision the user
    # has already defined, not raw material to find a story in.
    objective_text = render_objective(objective)
    # Base rates from comparable cases the user has actually seen. The inside
    # view is what the documents describe; this is the only outside view there is.
    outside_view = render_reference_cases(
        await list_reference_cases(session, project_id)
    )
    user_prompt = (
        objective_text + "\n" + outside_view + "\n" + context.user_prompt
        + language_instruction(context.language_sample)
    )

    generation_id = uuid.uuid4()
    logger.info(
        "Theory generation %s: project=%s graph_revision=%s claims=%s edges=%s "
        "provider=%s model=%s",
        generation_id,
        project_id,
        snapshot.graph_revision,
        context.metadata["claim_refs"],
        context.metadata["edge_refs"],
        settings.llm_provider,
        settings.llm_model,
    )

    # Cache deliberately disabled: the semantic cache matches on prompt
    # similarity, and a one-edge review edit barely moves the prompt. A cache
    # hit would silently return theories built on the pre-edit graph.
    client = llm or get_llm_client(enable_cache=False)
    payload = await client.complete_json(
        system=THEORY_GENERATION_SYSTEM,
        user=user_prompt,
        schema=THEORY_GENERATION_SCHEMA,
        max_tokens=8192,
        temperature=0.3,
    )

    known_keys = {str(t.theory_key) for t in previous}
    candidates, report = validate_theories(
        payload, context.refs, snapshot, known_theory_keys=known_keys, anchor=anchor
    )
    logger.info(
        "Theory generation %s validation: accepted=%d dropped=%d repaired=%d "
        "unknown_refs=%d",
        generation_id,
        report.accepted,
        len(report.dropped),
        len(report.repaired),
        len(set(report.unknown_refs)),
    )

    if not candidates:
        raise TheoryGenerationError(
            payload.get("insufficient_reason")
            or "No theory could be grounded in the reviewed graph."
        )

    theory_revision_number = await _next_revision_number(session, project_id)

    change_summary: dict[str, list[str]] = {
        "new_theory_ids": [],
        "changed_theory_ids": [],
        "unchanged_theory_ids": [],
        "superseded_theory_ids": [],
    }

    matched_keys: set[str] = set()
    matches: list[tuple[ValidatedTheory, Theory | None]] = []
    for candidate in candidates:
        previous_theory = match_previous(candidate, previous, matched_keys)
        if previous_theory is not None:
            matched_keys.add(str(previous_theory.theory_key))
        matches.append((candidate, previous_theory))

    created: list[Theory] = []
    key_to_theory: dict[str, Theory] = {}
    for candidate, previous_theory in matches:
        if previous_theory is None:
            theory_key = uuid.uuid4()
            version = 1
            change_kind = "new"
            explanation = candidate.change_explanation
        else:
            theory_key = previous_theory.theory_key
            version = (previous_theory.version or 1) + 1
            change_kind, explanation = describe_change(candidate, previous_theory)

        theory = _persist_theory(
            session,
            project_id=project_id,
            candidate=candidate,
            theory_key=theory_key,
            version=version,
            change_kind=change_kind,
            change_explanation=explanation,
            graph_revision=snapshot.graph_revision,
            theory_revision=theory_revision_number,
            generation_id=generation_id,
        )
        created.append(theory)
        key_to_theory[str(theory_key)] = theory

    await session.flush()

    # Commitments follow the theory, not the row. A pending tripwire is what the
    # decider said would change their mind, and a field test may be running;
    # leaving them on the retired version made both vanish from view on every
    # regeneration. Observed tripwires stay with the version they judged.
    for candidate, previous_theory in matches:
        if previous_theory is None:
            continue
        successor = key_to_theory[str(previous_theory.theory_key)]
        await session.execute(
            update(TheoryTripwire)
            .where(
                TheoryTripwire.theory_id == previous_theory.id,
                TheoryTripwire.status == "pending",
            )
            .values(theory_id=successor.id)
        )
        await session.execute(
            update(Experiment)
            .where(Experiment.theory_id == previous_theory.id, Experiment.kind == "field")
            .values(theory_id=successor.id)
        )
        # Same option, same predicted effect (see _same_claim), so the match
        # against the decider's comparable cases still holds, polarity included.
        successor.outside_view_case = previous_theory.outside_view_case
        successor.outside_view_polarity = previous_theory.outside_view_polarity
        successor.outside_view_delta = previous_theory.outside_view_delta
        successor.outside_view_note = previous_theory.outside_view_note

    # Retire previous versions, and mark genuinely dropped theories superseded.
    for previous_theory in previous:
        previous_theory.is_current = False
        successor = key_to_theory.get(str(previous_theory.theory_key))
        if successor is not None:
            previous_theory.superseded_by_id = successor.id
        else:
            previous_theory.status = "superseded"
            previous_theory.change_kind = "superseded"
            previous_theory.change_explanation = (
                previous_theory.change_explanation
                or "No longer supported by the reviewed graph."
            )
            change_summary["superseded_theory_ids"].append(str(previous_theory.id))

    for theory in created:
        bucket = {
            "new": "new_theory_ids",
            "changed": "changed_theory_ids",
            "unchanged": "unchanged_theory_ids",
        }[theory.change_kind or "new"]
        change_summary[bucket].append(str(theory.id))

    revision = TheoryRevision(
        project_id=project_id,
        revision=theory_revision_number,
        graph_revision=snapshot.graph_revision,
        generation_id=generation_id,
        trigger=trigger,
        change_summary=change_summary,
        generation_metadata={
            **context.metadata,
            "provider": settings.llm_provider,
            "model": settings.llm_model,
            "validation": report.as_dict(),
            "insufficient_reason": payload.get("insufficient_reason") or None,
        },
    )
    session.add(revision)

    await session.commit()

    # Re-load with provenance eagerly attached. A plain refresh() expires the
    # relationships, so the first caller to touch `theory.claim_links` would
    # trigger a lazy load — an N+1 at best, and a MissingGreenlet outside the
    # async context at worst.
    created_ids = [theory.id for theory in created]
    reloaded = await session.execute(
        select(Theory)
        .where(Theory.id.in_(created_ids))
        .options(*_theory_loader_options())
    )
    by_id = {theory.id: theory for theory in reloaded.scalars().all()}
    created = [by_id[theory_id] for theory_id in created_ids if theory_id in by_id]
    await session.refresh(revision)

    return TheoryGenerationResult(
        theories=created,
        objective_missing=objective is None,
        revision=revision,
        change_summary=change_summary,
        validation=report.as_dict(),
    )


async def mark_stale_if_answers_changed(
    session: AsyncSession, project_id: UUID, reason: str
) -> int:
    """Mark current theories stale after a clarification answer changed."""
    result = await session.execute(
        update(Theory)
        .where(
            Theory.project_id == project_id,
            Theory.is_current.is_(True),
            Theory.is_stale.is_(False),
        )
        .values(is_stale=True, stale_reason=reason)
        .returning(Theory.id)
    )
    return len(list(result.scalars().all()))
