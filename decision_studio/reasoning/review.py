"""Human review of graph nodes and edges.

Every mutation here goes through :func:`apply_review` so that four things
happen together, in one transaction:

1. the current-state review columns on ``claim`` / ``causal_edge`` are updated;
2. an immutable :class:`GraphOperation` row records before/after state;
3. ``project.graph_revision`` is bumped;
4. current theories are marked stale, because the graph they were derived from
   no longer matches the graph on screen.

Nothing is ever hard-deleted: "delete" means ``is_active = False``, which keeps
the element, its evidence and its provenance queryable and restorable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from decision_studio.db.models import CausalEdge, Claim, GraphOperation, Project, Theory
from decision_studio.reasoning.effective_graph import REVIEW_STATUSES

logger = logging.getLogger(__name__)

#: Fields of a claim that a review operation may change.
CLAIM_REVIEW_FIELDS = ("review_status", "is_active", "user_note")

#: Fields of an edge that a review operation may change.
EDGE_REVIEW_FIELDS = (
    "review_status",
    "is_active",
    "user_note",
    "strength_override",
    "mechanism",
)


class ReviewError(ValueError):
    """Raised when a review request is invalid or would corrupt the graph."""


@dataclass
class ReviewChange:
    """A validated set of field changes for one element."""

    review_status: str | None = None
    is_active: bool | None = None
    user_note: str | None = None
    strength_override: float | None = None
    clear_strength_override: bool = False
    mechanism: str | None = None

    def is_empty(self) -> bool:
        """Whether this element has been reviewed at all."""
        return (
            self.review_status is None
            and self.is_active is None
            and self.user_note is None
            and self.strength_override is None
            and not self.clear_strength_override
            and self.mechanism is None
        )


def validate_review_status(status: str | None) -> str | None:
    """Validate a review status against the supported vocabulary."""
    if status is None:
        return None
    if status not in REVIEW_STATUSES:
        raise ReviewError(
            f"Unknown review status '{status}'. Expected one of: "
            + ", ".join(REVIEW_STATUSES)
        )
    return status


def validate_strength_override(value: float | None) -> float | None:
    """Strength overrides must stay inside the causal-strength range."""
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ReviewError("Strength override must be a number") from exc
    if not (0.0 <= numeric <= 1.0):
        raise ReviewError("Strength override must be between 0.0 and 1.0")
    return numeric


def infer_operation_type(change: ReviewChange) -> str:
    """Name the operation for the audit log, most significant change first."""
    if change.is_active is False:
        return "disable"
    if change.is_active is True:
        return "restore"
    if change.review_status is not None:
        return "set_review_status"
    if change.clear_strength_override:
        return "clear_strength_override"
    if change.strength_override is not None:
        return "override_strength"
    if change.mechanism is not None:
        return "edit_mechanism"
    return "set_note"


def _snapshot(target: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    """Capture the reviewable fields of an element for the audit log."""
    return {name: getattr(target, name, None) for name in fields}


async def _bump_revision(project: Project) -> int:
    """Advance the graph revision, which is what makes reasoning stale."""
    project.graph_revision = (getattr(project, "graph_revision", 1) or 1) + 1
    return project.graph_revision


async def mark_theories_stale(
    session: AsyncSession,
    project_id: UUID,
    reason: str,
) -> int:
    """Flag every current theory of a project as stale.

    Returns the number of theories affected. Theories are not deleted — a stale
    theory is still readable and still explains what it was based on.
    """
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
    ids = list(result.scalars().all())
    if ids:
        logger.info(
            "Marked %d theories stale for project %s (%s)", len(ids), project_id, reason
        )
    return len(ids)


async def mark_reasoning_stale(
    session: AsyncSession,
    project_id: UUID,
    reason: str,
) -> dict[str, int]:
    """Invalidate everything derived from the graph, in one place.

    Theories rest on the graph; debates rest on two theories *and* on the graph
    that produced their overlap numbers. Anything that moves the graph moves
    both.

    This exists as a single function because the alternative -- each caller
    remembering to invalidate each derived thing -- already failed once: manual
    authoring marked theories stale and left debates claiming an overlap
    computed from claims that had since changed. The next derived artefact
    should be added here, not to every call site.
    """
    theories = await mark_theories_stale(session, project_id, reason)

    from decision_studio.reasoning.debate_service import mark_debates_stale

    debates = await mark_debates_stale(session, project_id)
    return {"theories": theories, "debates": debates}


async def apply_review(
    session: AsyncSession,
    project_id: UUID,
    *,
    target_type: str,
    target_id: UUID,
    change: ReviewChange,
    note: str | None = None,
    source: str = "user",
    commit: bool = True,
) -> tuple[Any, GraphOperation]:
    """Apply a review change to one claim or edge.

    Verifies that the target really belongs to ``project_id`` before touching
    anything — a review request must never reach across projects.

    Returns:
        ``(updated_element, operation)``.

    Raises:
        LookupError: unknown project or target, or target owned by another project.
        ReviewError: the requested change is invalid.
    """
    if target_type not in ("claim", "edge"):
        raise ReviewError(f"Unknown target type '{target_type}'")
    if change.is_empty():
        raise ReviewError("No review changes supplied")

    project = await session.get(Project, project_id)
    if project is None:
        raise LookupError(f"Project {project_id} not found")

    model = Claim if target_type == "claim" else CausalEdge
    target = await session.get(model, target_id)
    if target is None or target.project_id != project_id:
        raise LookupError(f"{target_type.capitalize()} {target_id} not found in project")

    validate_review_status(change.review_status)
    if target_type == "claim" and (
        change.strength_override is not None
        or change.clear_strength_override
        or change.mechanism is not None
    ):
        raise ReviewError("Strength override and mechanism only apply to edges")
    validate_strength_override(change.strength_override)

    fields = CLAIM_REVIEW_FIELDS if target_type == "claim" else EDGE_REVIEW_FIELDS
    before = _snapshot(target, fields)
    if target_type == "edge":
        before["strength_override"] = target.strength_override

    if change.review_status is not None:
        target.review_status = change.review_status
        # Rejecting or de-scoping an element also removes it from reasoning,
        # but keeps it in the graph so the user can see what they discarded.
        if change.review_status in ("rejected", "not_relevant") and change.is_active is None:
            target.is_active = False
    if change.is_active is not None:
        target.is_active = change.is_active
        # Restoring an element that was rejected returns it to review limbo
        # rather than silently promoting it to "accepted".
        if change.is_active and target.review_status in ("rejected", "not_relevant"):
            target.review_status = "uncertain"
    if change.user_note is not None:
        target.user_note = change.user_note or None
    if target_type == "edge":
        if change.clear_strength_override:
            target.strength_override = None
        elif change.strength_override is not None:
            target.strength_override = change.strength_override
        if change.mechanism is not None:
            if not change.mechanism.strip():
                raise ReviewError("Mechanism cannot be empty")
            target.mechanism = change.mechanism.strip()

    target.reviewed_at = datetime.now(timezone.utc)

    after = _snapshot(target, fields)
    revision_before = getattr(project, "graph_revision", 1) or 1
    revision_after = await _bump_revision(project)

    operation = GraphOperation(
        project_id=project_id,
        operation_type=infer_operation_type(change),
        target_type=target_type,
        claim_id=target_id if target_type == "claim" else None,
        edge_id=target_id if target_type == "edge" else None,
        before_state=before,
        after_state=after,
        revision_before=revision_before,
        revision_after=revision_after,
        source=source,
        note=note,
    )
    session.add(operation)

    await mark_reasoning_stale(
        session,
        project_id,
        reason=f"Graph edited at revision {revision_after} ({operation.operation_type})",
    )

    if commit:
        await session.commit()
        await session.refresh(target)
        await session.refresh(operation)

    return target, operation


async def undo_operation(
    session: AsyncSession,
    project_id: UUID,
    operation_id: UUID,
    *,
    commit: bool = True,
) -> tuple[Any, GraphOperation]:
    """Revert a previously recorded operation by replaying its before-state.

    The undo itself is recorded as a new operation, so history stays append-only
    and an undo can in turn be undone.

    Raises:
        LookupError: unknown operation, or it belongs to another project.
        ReviewError: the operation was already undone.
    """
    operation = await session.get(GraphOperation, operation_id)
    if operation is None or operation.project_id != project_id:
        raise LookupError(f"Operation {operation_id} not found in project")
    if operation.undone_at is not None:
        raise ReviewError("Operation has already been undone")

    project = await session.get(Project, project_id)
    if project is None:
        raise LookupError(f"Project {project_id} not found")

    model = Claim if operation.target_type == "claim" else CausalEdge
    target_id = operation.claim_id if operation.target_type == "claim" else operation.edge_id
    if target_id is None:
        raise ReviewError("Operation has no target to restore")

    target = await session.get(model, target_id)
    if target is None or target.project_id != project_id:
        raise LookupError("Operation target no longer exists")

    fields = (
        CLAIM_REVIEW_FIELDS if operation.target_type == "claim" else EDGE_REVIEW_FIELDS
    )
    before_undo = _snapshot(target, fields)
    for name, value in (operation.before_state or {}).items():
        if name in fields:
            setattr(target, name, value)
    target.reviewed_at = datetime.now(timezone.utc)

    revision_before = getattr(project, "graph_revision", 1) or 1
    revision_after = await _bump_revision(project)

    undo_op = GraphOperation(
        project_id=project_id,
        operation_type=f"undo:{operation.operation_type}",
        target_type=operation.target_type,
        claim_id=operation.claim_id,
        edge_id=operation.edge_id,
        before_state=before_undo,
        after_state=_snapshot(target, fields),
        revision_before=revision_before,
        revision_after=revision_after,
        source="user",
        note=f"Undo of operation {operation_id}",
    )
    session.add(undo_op)
    await session.flush()

    operation.undone_at = datetime.now(timezone.utc)
    operation.undone_by_operation_id = undo_op.id

    await mark_reasoning_stale(
        session,
        project_id,
        reason=f"Graph edit undone at revision {revision_after}",
    )

    if commit:
        await session.commit()
        await session.refresh(target)
        await session.refresh(undo_op)

    return target, undo_op


async def list_operations(
    session: AsyncSession,
    project_id: UUID,
    *,
    limit: int = 100,
) -> list[GraphOperation]:
    """Return the project's review history, newest first."""
    result = await session.execute(
        select(GraphOperation)
        .where(GraphOperation.project_id == project_id)
        .order_by(GraphOperation.created_at.desc(), GraphOperation.revision_after.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
