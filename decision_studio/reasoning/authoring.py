"""Manual graph authoring, and the incremental recompute it triggers.

Until now human review was authoritative for *removing* elements and silent for
*adding* them. That asymmetry was incoherent with everything else here: if human
judgement outranks model inference — and the whole design says it does — then it
has to be able to say "you missed something", not only "you got that wrong".

It also fails the domain. In a strategic decision the factors that matter are
routinely not written down: the thing everyone in the room knows and nobody put
in a document. A model that can only be pruned cannot be corrected.

## What happens after an addition

Adding a claim invalidates work downstream of it, but **not** uniformly, and the
difference is a correctness requirement rather than an optimisation:

* **Causal inference** must run for the new claim against the existing ones, and
  *only* those pairs. Re-running it wholesale would regenerate edges the user has
  already rejected — the human review would be silently undone by the very act of
  accepting a human addition.
* **Blind re-scoring** applies to newly inferred AI edges only. A user-authored
  edge is deliberately exempt: that pass exists to correct a model that scored
  its own proposal, and there is no such bias to correct here.
* **Evidence grounding** applies to new edges only, for the same reason.
* **DAG construction and belief propagation** must re-run over the whole graph,
  because a single new node changes topology, cycles and every downstream belief.
  These are pure computation, so they are cheap and always safe to redo.

The split is exposed in :class:`RecomputePlan` rather than hidden, so the caller
can see what a change costs before paying for it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from decision_studio.db.models import CausalEdge, Claim, GraphOperation, Project
from decision_studio.graph.edge_weight import edge_strength
from decision_studio.llm.client import LLMClient, get_llm_client
from decision_studio.reasoning.review import mark_reasoning_stale

logger = logging.getLogger(__name__)

VALID_CLAIM_TYPES = ("FACT", "ASSUMPTION", "PREDICTION", "OPINION")


class AuthoringError(ValueError):
    """Raised when a manual addition would be invalid or would corrupt the graph."""


@dataclass
class RecomputePlan:
    """What a graph change invalidates, and what it will cost to restore.

    Made explicit so the user can see that adding one node means N LLM calls
    before they trigger it, rather than discovering it from the bill.
    """

    new_claim_ids: list[str] = field(default_factory=list)
    new_edge_ids: list[str] = field(default_factory=list)
    needs_causal_inference: bool = False
    needs_evidence_grounding: bool = False
    needs_propagation: bool = True
    estimated_llm_calls: int = 0
    #: Elements deliberately skipped, with the reason. Shown to the user so an
    #: exemption never looks like an oversight.
    skipped: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """The recompute plan, for the API."""
        return {
            "new_claim_ids": self.new_claim_ids,
            "new_edge_ids": self.new_edge_ids,
            "needs_causal_inference": self.needs_causal_inference,
            "needs_evidence_grounding": self.needs_evidence_grounding,
            "needs_propagation": self.needs_propagation,
            "estimated_llm_calls": self.estimated_llm_calls,
            "skipped": self.skipped,
        }


async def _bump_and_log(
    session: AsyncSession,
    project: Project,
    *,
    operation_type: str,
    target_type: str,
    claim_id: UUID | None = None,
    edge_id: UUID | None = None,
    after_state: dict[str, Any] | None = None,
    note: str | None = None,
) -> GraphOperation:
    """Record an authoring operation exactly like a review operation.

    ``before_state`` is None because the element did not exist. Undo therefore
    deactivates rather than deletes, consistent with the rule that nothing here
    is ever destroyed.
    """
    revision_before = getattr(project, "graph_revision", 1) or 1
    project.graph_revision = revision_before + 1

    operation = GraphOperation(
        project_id=project.id,
        operation_type=operation_type,
        target_type=target_type,
        claim_id=claim_id,
        edge_id=edge_id,
        before_state=None,
        after_state=after_state,
        revision_before=revision_before,
        revision_after=project.graph_revision,
        source="user",
        note=note,
    )
    session.add(operation)
    return operation


async def add_claim(
    session: AsyncSession,
    project_id: UUID,
    *,
    text: str,
    claim_type: str = "ASSUMPTION",
    prior: float = 0.5,
    confidence: float = 0.8,
    user_note: str | None = None,
) -> tuple[Claim, RecomputePlan]:
    """Add a claim the documents did not contain.

    Defaults to ASSUMPTION: something the user asserts from their own knowledge
    is, epistemically, an assumption of the model until evidence says otherwise.
    ``confidence`` defaults high because the user is stating it firmly; ``prior``
    stays at 0.5 because firmness is not truth — the same distinction applied to
    extracted claims.

    Raises:
        LookupError: unknown project.
        AuthoringError: invalid text or claim type.
    """
    project = await session.get(Project, project_id)
    if project is None:
        raise LookupError(f"Project {project_id} not found")

    cleaned = (text or "").strip()
    if not cleaned:
        raise AuthoringError("A claim needs text")
    if len(cleaned) > 2000:
        raise AuthoringError("Claim text is too long (max 2000 characters)")
    if claim_type.upper() not in VALID_CLAIM_TYPES:
        raise AuthoringError(
            f"Unknown claim type '{claim_type}'. Expected one of: "
            + ", ".join(VALID_CLAIM_TYPES)
        )

    highest = await session.scalar(
        select(Claim.order_index)
        .where(Claim.project_id == project_id)
        .order_by(Claim.order_index.desc())
        .limit(1)
    )

    claim = Claim(
        project_id=project_id,
        text=cleaned,
        claim_type=claim_type.upper(),
        confidence=max(0.0, min(1.0, confidence)),
        prior=max(0.0, min(1.0, prior)),
        order_index=(highest or -1) + 1,
        origin="user",
        review_status="accepted",
        is_active=True,
        user_note=(user_note or "").strip() or None,
        # The user is the source. Recording it explicitly keeps the interest
        # model honest rather than defaulting to "unknown".
        source_interest="disinterested",
        source_role="added directly by the decision owner",
        reviewed_at=datetime.now(timezone.utc),
    )
    session.add(claim)
    await session.flush()

    await _bump_and_log(
        session, project,
        operation_type="add_claim",
        target_type="claim",
        claim_id=claim.id,
        after_state={"text": cleaned, "claim_type": claim.claim_type, "origin": "user"},
        note=user_note,
    )
    await mark_reasoning_stale(
        session, project_id, reason="A claim was added to the graph"
    )
    await session.commit()
    await session.refresh(claim)

    # Upper bound on the inference cost: one call per pair of the new claim with
    # each existing active claim, in both directions. The inferrer prunes pairs
    # by embedding similarity first, so the real figure is usually lower --
    # over-stating it is the safe direction for a number shown before spending.
    active_claims = await session.scalar(
        select(func.count())
        .select_from(Claim)
        .where(Claim.project_id == project_id, Claim.is_active.is_(True))
    ) or 1
    plan = RecomputePlan(
        new_claim_ids=[str(claim.id)],
        needs_causal_inference=True,
        needs_evidence_grounding=False,
        estimated_llm_calls=max(0, (active_claims - 1) * 2),
    )
    logger.info("Claim %s added manually to project %s", claim.id, project_id)
    return claim, plan


async def add_edge(
    session: AsyncSession,
    project_id: UUID,
    *,
    source_claim_id: UUID,
    target_claim_id: UUID,
    mechanism: str,
    effect: float = 0.5,
    link_confidence: float = 0.5,
    user_note: str | None = None,
) -> tuple[CausalEdge, RecomputePlan]:
    """Add a causal link the model did not infer.

    Refuses a self-loop and a duplicate of an existing active edge; both would
    corrupt propagation, and a duplicate would also double-count the link.

    Raises:
        LookupError: unknown project or endpoint.
        AuthoringError: invalid link.
    """
    project = await session.get(Project, project_id)
    if project is None:
        raise LookupError(f"Project {project_id} not found")

    if source_claim_id == target_claim_id:
        raise AuthoringError("A claim cannot cause itself")

    cleaned = (mechanism or "").strip()
    if not cleaned:
        raise AuthoringError("A causal link needs a mechanism: how does the cause act?")

    for claim_id, label in ((source_claim_id, "source"), (target_claim_id, "target")):
        claim = await session.get(Claim, claim_id)
        if claim is None or claim.project_id != project_id:
            raise LookupError(f"The {label} claim was not found in this project")

    existing = await session.scalar(
        select(CausalEdge.id).where(
            CausalEdge.project_id == project_id,
            CausalEdge.source_claim_id == source_claim_id,
            CausalEdge.target_claim_id == target_claim_id,
            CausalEdge.is_active.is_(True),
        )
    )
    if existing is not None:
        raise AuthoringError(
            "That causal link already exists. Edit its strength instead of adding "
            "a second one."
        )

    effect = max(0.0, min(1.0, effect))
    link_confidence = max(0.0, min(1.0, link_confidence))

    edge = CausalEdge(
        project_id=project_id,
        source_claim_id=source_claim_id,
        target_claim_id=target_claim_id,
        mechanism=cleaned,
        effect=effect,
        link_confidence=link_confidence,
        strength=edge_strength(effect, link_confidence),
        # Not searched yet. The evidence floor keeps it propagating meanwhile,
        # rather than treating "nobody has looked" as refutation.
        evidence_score=0.5,
        origin="user",
        review_status="accepted",
        is_active=True,
        user_note=(user_note or "").strip() or None,
        reviewed_at=datetime.now(timezone.utc),
    )
    session.add(edge)
    await session.flush()

    await _bump_and_log(
        session, project,
        operation_type="add_edge",
        target_type="edge",
        edge_id=edge.id,
        after_state={
            "mechanism": cleaned,
            "effect": effect,
            "link_confidence": link_confidence,
            "origin": "user",
        },
        note=user_note,
    )
    await mark_reasoning_stale(
        session, project_id, reason="A causal link was added to the graph"
    )
    await session.commit()
    await session.refresh(edge)

    plan = RecomputePlan(
        new_edge_ids=[str(edge.id)],
        needs_causal_inference=False,
        needs_evidence_grounding=True,
        estimated_llm_calls=1,
        skipped=[
            "Blind re-scoring skipped: you authored this link, and that pass "
            "exists to correct a model scoring its own proposal."
        ],
    )
    logger.info("Edge %s added manually to project %s", edge.id, project_id)
    return edge, plan


# DEAD-CODE-CANDIDATE DC-20: no route or caller; undo goes through review.undo_operation. See docs/DEAD_CODE_REPORT.md
async def undo_addition(
    session: AsyncSession, project_id: UUID, operation_id: UUID
) -> GraphOperation:
    """Reverse an addition by deactivating, never by deleting.

    Consistent with the rest of the system: an element the user added and then
    withdrew is still part of the reasoning history, and its edges keep their
    provenance.

    Raises:
        LookupError: unknown operation.
        AuthoringError: the operation was not an addition, or was already undone.
    """
    operation = await session.get(GraphOperation, operation_id)
    if operation is None or operation.project_id != project_id:
        raise LookupError(f"Operation {operation_id} not found in project")
    if operation.operation_type not in ("add_claim", "add_edge"):
        raise AuthoringError("That operation was not an addition")
    if operation.undone_at is not None:
        raise AuthoringError("That addition has already been undone")

    project = await session.get(Project, project_id)
    if project is None:
        raise LookupError(f"Project {project_id} not found")

    if operation.operation_type == "add_claim":
        target = await session.get(Claim, operation.claim_id)
        if target is not None:
            target.is_active = False
            target.review_status = "not_relevant"
            # Incident edges go with it: a link from a withdrawn claim is not a
            # causal link. They are deactivated, not deleted.
            incident = (
                await session.execute(
                    select(CausalEdge).where(
                        CausalEdge.project_id == project_id,
                        (CausalEdge.source_claim_id == target.id)
                        | (CausalEdge.target_claim_id == target.id),
                    )
                )
            ).scalars().all()
            for edge in incident:
                edge.is_active = False
    else:
        target = await session.get(CausalEdge, operation.edge_id)
        if target is not None:
            target.is_active = False
            target.review_status = "not_relevant"

    undo_op = await _bump_and_log(
        session, project,
        operation_type=f"undo:{operation.operation_type}",
        target_type=operation.target_type,
        claim_id=operation.claim_id,
        edge_id=operation.edge_id,
        after_state={"is_active": False},
        note=f"Undo of addition {operation_id}",
    )
    await session.flush()
    operation.undone_at = datetime.now(timezone.utc)
    operation.undone_by_operation_id = undo_op.id

    await mark_reasoning_stale(
        session, project_id, reason="A manual addition was withdrawn"
    )
    await session.commit()
    await session.refresh(undo_op)
    return undo_op


async def infer_links_for_new_claims(
    session: AsyncSession,
    project_id: UUID,
    new_claim_ids: list[UUID],
    *,
    llm: LLMClient | None = None,
) -> list[CausalEdge]:
    """Infer causal links between newly added claims and the existing graph.

    Only pairs involving a new claim are considered. Re-running inference over
    everything would regenerate links the user has already rejected, which would
    make accepting one human correction quietly undo all the others.

    Raises:
        LookupError: unknown project.
    """
    if not new_claim_ids:
        return []

    project = await session.get(Project, project_id)
    if project is None:
        raise LookupError(f"Project {project_id} not found")

    result = await session.execute(
        select(Claim)
        .where(Claim.project_id == project_id, Claim.is_active.is_(True))
        .order_by(Claim.order_index)
    )
    claims = list(result.scalars().all())
    if len(claims) < 2:
        return []

    new_ids = {str(cid) for cid in new_claim_ids}

    # The inferrer prunes candidate pairs by embedding similarity, so every
    # claim in the payload needs a vector. A manually added claim has none yet,
    # and the pipeline's stored ones may be absent for older projects.
    #
    # Where a vector is missing we substitute a shared placeholder. That makes
    # the similarity of any pair involving it 1.0, so the pruner keeps it: with
    # no embedding we cannot judge whether two claims are related, and
    # considering the pair is the honest failure mode. Silently dropping it
    # would mean a manually added claim quietly acquired no links at all.
    dimension = _embedding_dimension(claims)
    placeholder = [1.0] * dimension

    payload = [
        {
            "text": c.text,
            "type": c.claim_type,
            "confidence": c.confidence,
            "prior": c.prior,
            "order_index": c.order_index,
            "embedding": _as_vector(c.embedding, placeholder),
            # Carried so the inferrer can keep anchor outcomes as sinks.
            "origin": c.origin,
            "decision_role": c.decision_role,
            "relevance": c.relevance,
        }
        for c in claims
    ]
    new_indices = {i for i, c in enumerate(claims) if str(c.id) in new_ids}
    if not new_indices:
        return []

    from decision_studio.pipeline.causal_inferrer import CausalInferrer

    from decision_studio.reasoning.anchor_service import inference_context

    inferrer = CausalInferrer(llm or get_llm_client(enable_cache=False))
    # The same context the pipeline inferred the rest of the graph with: a link
    # for a hand-added claim judged without the decision or the intake answers
    # would rest on a different reading of the material from its neighbours.
    raw_edges = await inferrer.infer_incremental(
        payload, new_indices, extra_context=inference_context(project)
    )

    existing_pairs = {
        (str(e.source_claim_id), str(e.target_claim_id))
        for e in (
            await session.execute(
                select(CausalEdge).where(CausalEdge.project_id == project_id)
            )
        ).scalars().all()
    }

    created: list[CausalEdge] = []
    for raw in raw_edges:
        try:
            source = claims[int(raw["source_idx"])]
            target = claims[int(raw["target_idx"])]
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        if source.id == target.id:
            continue
        if (str(source.id), str(target.id)) in existing_pairs:
            # Already present, possibly rejected. Leave the human decision alone.
            continue

        effect = float(raw.get("effect", raw.get("strength", 0.5)))
        confidence = float(raw.get("link_confidence", 1.0))
        edge = CausalEdge(
            project_id=project_id,
            source_claim_id=source.id,
            target_claim_id=target.id,
            mechanism=raw.get("mechanism", ""),
            effect=effect,
            link_confidence=confidence,
            strength=edge_strength(effect, confidence),
            evidence_score=0.5,
            origin="ai",
        )
        session.add(edge)
        created.append(edge)
        existing_pairs.add((str(source.id), str(target.id)))

    if created:
        project.graph_revision = (project.graph_revision or 1) + 1
        await mark_reasoning_stale(
            session,
            project_id,
            reason=f"{len(created)} causal link(s) inferred from a new claim",
        )

    await session.commit()
    for edge in created:
        await session.refresh(edge)

    logger.info(
        "Incremental inference: %d new link(s) for %d new claim(s) in project %s",
        len(created), len(new_claim_ids), project_id,
    )
    return created


# DEAD-CODE-CANDIDATE DC-23 (runs, no effect): propagates and discards the result — beliefs are recomputed on every graph read anyway. The /recompute endpoint and the frontend call to it can go with it. See docs/DEAD_CODE_REPORT.md
async def recompute_beliefs(session: AsyncSession, project_id: UUID) -> dict[str, Any]:
    """Rebuild the DAG and re-propagate beliefs over the whole graph.

    Pure computation — no LLM, no network — so it is cheap and always safe to
    run after any structural change. Unlike the inference stages it *must* cover
    the whole graph: one new node changes topology, cycles and every downstream
    belief.
    """
    from decision_studio.api.routes.graph import _build_nx_graph, _break_cycles
    from decision_studio.graph.belief_propagation import propagate_beliefs

    claims = (
        await session.execute(
            select(Claim).where(Claim.project_id == project_id).order_by(Claim.order_index)
        )
    ).scalars().all()
    edges = (
        await session.execute(
            select(CausalEdge)
            .where(CausalEdge.project_id == project_id)
            .options(selectinload(CausalEdge.evidences))
        )
    ).scalars().all()

    if not claims:
        return {"claims": 0, "edges": 0, "cycles_broken": 0}

    graph = _break_cycles(_build_nx_graph(list(claims), list(edges)))
    propagate_beliefs(graph)

    logger.info(
        "Recomputed beliefs for project %s: %d claims, %d edges",
        project_id, len(claims), len(edges),
    )
    return {
        "claims": len(claims),
        "edges": len(edges),
        "nodes_propagated": graph.number_of_nodes(),
    }


def _embedding_dimension(claims: list[Claim], default: int = 1024) -> int:
    """Width of the stored embeddings, or a sane default when none exist."""
    for claim in claims:
        vector = getattr(claim, "embedding", None)
        if vector is not None and len(vector) > 0:
            return len(vector)
    return default


def _as_vector(stored: Any, placeholder: list[float]) -> list[float]:
    """Stored embedding as a plain list, falling back to the placeholder."""
    if stored is None:
        return placeholder
    try:
        vector = [float(v) for v in stored]
    except (TypeError, ValueError):
        return placeholder
    return vector if vector else placeholder
