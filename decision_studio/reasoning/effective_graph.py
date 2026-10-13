"""The *effective* graph: what human review left standing.

Decision Studio's visual graph keeps showing everything, including elements the user
rejected — provenance must never disappear. Reasoning, however, must run on the
reviewed graph only. This module is the single place that decides what "the
reviewed graph" means, so theory generation, clarification generation and the
API all agree.

Rules (see ``is_claim_effective`` / ``is_edge_effective``):

* an element must be active (not soft-deleted) and must not be rejected or
  marked not-relevant;
* an edge additionally requires both of its endpoint claims to be effective —
  a dangling edge is not a causal link;
* a human ``strength_override`` wins over the AI-inferred ``strength``.

The predicates take plain attribute holders rather than ORM instances so they
can be unit-tested without a database.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from decision_studio.db.models import CausalEdge, Claim, Evidence, Project

logger = logging.getLogger(__name__)

#: Review statuses that remove an element from the effective graph.
EXCLUDED_REVIEW_STATUSES: frozenset[str] = frozenset({"rejected", "not_relevant"})

#: All accepted review statuses.
REVIEW_STATUSES: tuple[str, ...] = (
    "accepted",
    "rejected",
    "uncertain",
    "business_critical",
    "not_relevant",
    "needs_evidence",
)

#: Statuses that flag an element as needing attention but keep it in the graph.
ATTENTION_REVIEW_STATUSES: frozenset[str] = frozenset({"uncertain", "needs_evidence"})


# DEAD-CODE-CANDIDATE DC-21: typing Protocol referenced nowhere. See docs/DEAD_CODE_REPORT.md
class _Reviewable(Protocol):
    """Minimal shape shared by reviewed claims and edges."""

    is_active: bool
    review_status: str


def is_claim_effective(claim: Any) -> bool:
    """Return True if *claim* participates in reasoning."""
    if not getattr(claim, "is_active", True):
        return False
    status = getattr(claim, "review_status", "accepted") or "accepted"
    return status not in EXCLUDED_REVIEW_STATUSES


def is_edge_effective(edge: Any, effective_claim_ids: set[str] | None = None) -> bool:
    """Return True if *edge* participates in reasoning.

    Args:
        edge: the edge to test.
        effective_claim_ids: string IDs of claims that survived review. When
            provided, an edge whose source or target was removed is itself
            removed — reasoning must never traverse a dangling link.
    """
    if not getattr(edge, "is_active", True):
        return False
    status = getattr(edge, "review_status", "accepted") or "accepted"
    if status in EXCLUDED_REVIEW_STATUSES:
        return False
    if effective_claim_ids is not None:
        if str(edge.source_claim_id) not in effective_claim_ids:
            return False
        if str(edge.target_claim_id) not in effective_claim_ids:
            return False
    return True


def effective_strength(edge: Any) -> float:
    """Human override wins over the AI-inferred strength."""
    override = getattr(edge, "strength_override", None)
    if override is not None:
        return float(override)
    return float(getattr(edge, "strength", 0.5) or 0.0)


def filter_effective(
    claims: list[Any], edges: list[Any]
) -> tuple[list[Any], list[Any]]:
    """Split reviewed claims/edges into the subset used for reasoning.

    Pure function — no I/O — so it can be exercised directly in tests.
    """
    kept_claims = [c for c in claims if is_claim_effective(c)]
    kept_ids = {str(c.id) for c in kept_claims}
    kept_edges = [e for e in edges if is_edge_effective(e, kept_ids)]
    return kept_claims, kept_edges


@dataclass
class GraphSnapshot:
    """An immutable view of the reviewed graph at one revision.

    This is what gets summarized for the LLM and what generated output is
    validated against — nothing may reference an element that is not in here.
    """

    project: Project
    graph_revision: int
    claims: list[Claim]
    edges: list[CausalEdge]
    evidence_by_edge: dict[str, list[Evidence]] = field(default_factory=dict)

    # Fast membership lookups, built in __post_init__.
    claims_by_id: dict[str, Claim] = field(default_factory=dict, repr=False)
    edges_by_id: dict[str, CausalEdge] = field(default_factory=dict, repr=False)
    evidence_by_id: dict[str, Evidence] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        """Index the claims and edges by id, once."""
        self.claims_by_id = {str(c.id): c for c in self.claims}
        self.edges_by_id = {str(e.id): e for e in self.edges}
        self.evidence_by_id = {
            str(ev.id): ev
            for evidences in self.evidence_by_edge.values()
            for ev in evidences
        }

    @property
    def is_empty(self) -> bool:
        """Whether there is anything to reason from."""
        return not self.claims

    def evidence_edge_id(self, evidence_id: str) -> str | None:
        """Return the edge an evidence item belongs to, if it is in scope."""
        ev = self.evidence_by_id.get(evidence_id)
        return str(ev.edge_id) if ev is not None else None


async def load_effective_snapshot(
    project_id: UUID,
    session: AsyncSession,
) -> GraphSnapshot:
    """Load the reviewed graph for *project_id*.

    Evidence is loaded eagerly with ``selectinload`` (one extra query for the
    whole edge set) rather than lazily per edge, which would be an N+1.

    Both queries order explicitly: the context builder assigns reference tokens
    (``C1``, ``E1``) positionally, so an unordered result set would hand the
    same graph different tokens on different runs and make a generation
    impossible to reproduce from its recorded revision.

    Raises:
        LookupError: if the project does not exist.
    """
    project = await session.get(Project, project_id)
    if project is None:
        raise LookupError(f"Project {project_id} not found")

    claims_result = await session.execute(
        select(Claim)
        .where(Claim.project_id == project_id)
        .order_by(Claim.order_index)
    )
    all_claims = list(claims_result.scalars().all())

    edges_result = await session.execute(
        select(CausalEdge)
        .where(CausalEdge.project_id == project_id)
        .order_by(CausalEdge.id)
        .options(selectinload(CausalEdge.evidences))
    )
    all_edges = list(edges_result.scalars().all())

    claims, edges = filter_effective(all_claims, all_edges)

    evidence_by_edge = {str(e.id): list(e.evidences or []) for e in edges}

    return GraphSnapshot(
        project=project,
        graph_revision=getattr(project, "graph_revision", 1) or 1,
        claims=claims,
        edges=edges,
        evidence_by_edge=evidence_by_edge,
    )
