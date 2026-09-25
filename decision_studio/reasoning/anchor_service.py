"""Reading, drafting and saving the decision anchor of a project.

Saving an anchor after the graph exists is the case that needs care. People
often work out what they are deciding only after seeing what the documents
contain (HANDOVER §4.3), so the anchor has to be editable afterwards — and
editing it must not mean re-running a twenty-minute pipeline. Two things follow
from an edit, both far cheaper than a run:

* **Outcome nodes are synchronised.** A renamed outcome keeps its node and its
  links; a new outcome gets a node and incremental inference against the
  existing claims (only pairs involving it, so no rejected link is regenerated);
  a removed outcome's node is deactivated, not deleted, so undoing the edit
  restores it.
* **Every claim is re-scored** against the new anchor, one call per forty
  claims.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_studio.db.models import Claim, Project
from decision_studio.llm.client import LLMClient, get_llm_client
from decision_studio.reasoning.decision_anchor import (
    ORIGIN_FRAME,
    ROLE_OUTCOME,
    STATUS_CONFIRMED,
    anchor_keys,
    draft_anchor,
    normalise_anchor,
    outcome_claim_text,
    render_anchor,
    score_relevance,
)
from decision_studio.reasoning.review import mark_reasoning_stale

logger = logging.getLogger(__name__)


class AnchorError(ValueError):
    """Raised when a submitted anchor cannot be used."""


def inference_context(project: Project) -> str | None:
    """The context the pipeline inferred links with: the anchor, then the intake answers.

    Shared with manual authoring so a link inferred for a claim added by hand is
    judged against the same reading of the material as the rest of the graph.
    """
    anchor = normalise_anchor(getattr(project, "decision_anchor", None))
    parts = (render_anchor(anchor), getattr(project, "intake_context", None) or "")
    return "\n".join(p for p in parts if p) or None


async def _require_project(session: AsyncSession, project_id: UUID) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise LookupError(f"Project {project_id} not found")
    return project


async def used_keys(session: AsyncSession, project: Project) -> set[str]:
    """Every option and outcome key this project has used, deleted ones included.

    The previous anchor shows what the user last saw; the outcome nodes also
    remember outcomes removed in earlier edits, whose deactivated nodes still
    carry their links.
    """
    keys = anchor_keys(normalise_anchor(project.decision_anchor))
    result = await session.execute(
        select(Claim.metadata_).where(
            Claim.project_id == project.id,
            Claim.origin == ORIGIN_FRAME,
            Claim.decision_role == ROLE_OUTCOME,
        )
    )
    keys |= {
        (meta or {}).get("anchor_key") for meta in result.scalars().all()
        if (meta or {}).get("anchor_key")
    }
    return keys


async def get_anchor(session: AsyncSession, project_id: UUID) -> dict[str, Any] | None:
    """The project's anchor, cleaned, or None."""
    project = await _require_project(session, project_id)
    return normalise_anchor(project.decision_anchor)


async def draft_for_project(
    session: AsyncSession,
    project_id: UUID,
    *,
    llm: LLMClient | None = None,
) -> dict[str, Any] | None:
    """Draft an anchor from the objective and the material.

    Stored only when the project has no confirmed anchor: a draft must never
    overwrite what the user has already corrected. Returns the draft either way,
    so the caller can offer it.
    """
    project = await _require_project(session, project_id)
    draft = await draft_anchor(
        llm or get_llm_client(enable_cache=False),
        project.decision_objective,
        project.input_text or "",
    )
    current = normalise_anchor(project.decision_anchor)
    if draft is not None and (current is None or current["status"] != STATUS_CONFIRMED):
        project.decision_anchor = draft
        await session.commit()
    return draft


async def save_anchor(
    session: AsyncSession,
    project_id: UUID,
    raw: dict[str, Any],
    *,
    llm: LLMClient | None = None,
) -> dict[str, Any]:
    """Save a user-confirmed anchor, and bring an existing graph in line with it.

    Returns the saved anchor and a report of what changed. Before a run, only
    the anchor is stored: the pipeline creates outcome nodes and scores claims
    itself.

    Raises:
        LookupError: unknown project.
        AnchorError: the anchor has no decision.
    """
    project = await _require_project(session, project_id)
    previous = normalise_anchor(project.decision_anchor)
    anchor = normalise_anchor(
        raw, status=STATUS_CONFIRMED, reserved=await used_keys(session, project)
    )
    if anchor is None:
        raise AnchorError("The anchor needs a decision")

    project.decision_anchor = anchor
    # One decision, stated once: everything that reads the objective reads the
    # anchor's decision.
    project.decision_objective = anchor["decision"]
    await session.commit()

    report: dict[str, Any] = {
        "outcomes_added": 0, "outcomes_updated": 0, "outcomes_retired": 0,
        "links_inferred": 0, "claims_rescored": 0, "claims_total": 0,
    }

    claim_count = await session.scalar(
        select(func.count()).select_from(Claim).where(Claim.project_id == project_id)
    )
    if not claim_count:
        return {"anchor": anchor, "report": report}

    client = llm or get_llm_client(enable_cache=False)
    new_ids = await _sync_outcome_nodes(session, project, anchor, report)

    if new_ids:
        from decision_studio.reasoning.authoring import infer_links_for_new_claims

        links = await infer_links_for_new_claims(session, project_id, new_ids, llm=client)
        report["links_inferred"] = len(links)

    if previous != anchor:
        await _rescore_claims(session, project_id, anchor, client, report)
        await mark_reasoning_stale(
            session, project_id, reason="The decision anchor changed"
        )
        await session.commit()

    logger.info("Decision anchor saved for project %s: %s", project_id, report)
    return {"anchor": anchor, "report": report}


async def _sync_outcome_nodes(
    session: AsyncSession,
    project: Project,
    anchor: dict[str, Any],
    report: dict[str, Any],
) -> list[UUID]:
    """Make the graph's outcome nodes match the anchor's outcomes. Returns new node ids."""
    result = await session.execute(
        select(Claim).where(
            Claim.project_id == project.id,
            Claim.origin == ORIGIN_FRAME,
            Claim.decision_role == ROLE_OUTCOME,
        )
    )
    existing = {
        (c.metadata_ or {}).get("anchor_key"): c for c in result.scalars().all()
    }

    wanted = {o["key"]: o for o in anchor["outcomes"]}
    new_claims: list[Claim] = []
    changed = False

    highest = await session.scalar(
        select(func.max(Claim.order_index)).where(Claim.project_id == project.id)
    )
    next_index = (highest if highest is not None else -1) + 1

    for key, outcome in wanted.items():
        text = outcome_claim_text(outcome)
        node = existing.get(key)
        if node is not None:
            if node.text != text or not node.is_active:
                node.text = text
                node.is_active = True
                report["outcomes_updated"] += 1
                changed = True
            continue
        node = Claim(
            project_id=project.id,
            text=text,
            claim_type="PREDICTION",
            confidence=0.5,
            prior=0.5,
            order_index=next_index,
            origin=ORIGIN_FRAME,
            decision_role=ROLE_OUTCOME,
            relevance=1.0,
            bears_on=[key],
            metadata_={"anchor_key": key},
            source_interest="disinterested",
            source_role="the decision anchor",
        )
        next_index += 1
        session.add(node)
        new_claims.append(node)
        report["outcomes_added"] += 1
        changed = True

    for key, node in existing.items():
        if key not in wanted and node.is_active:
            # Deactivated, not deleted: the links into it are the user's work
            # as much as the model's, and re-adding the outcome restores them.
            node.is_active = False
            report["outcomes_retired"] += 1
            changed = True

    if changed:
        project.graph_revision = (project.graph_revision or 1) + 1
    await session.commit()
    return [c.id for c in new_claims]


async def _rescore_claims(
    session: AsyncSession,
    project_id: UUID,
    anchor: dict[str, Any],
    llm: LLMClient,
    report: dict[str, Any],
) -> None:
    """Score every non-anchor claim against the anchor.

    A claim whose batch fails keeps its previous scores. Stale scores against a
    similar anchor are more useful than none, and the report says how many were
    refreshed.
    """
    result = await session.execute(
        select(Claim)
        .where(Claim.project_id == project_id, Claim.origin != ORIGIN_FRAME)
        .order_by(Claim.order_index)
    )
    claims = list(result.scalars().all())
    report["claims_total"] = len(claims)
    scores = await score_relevance(llm, anchor, [c.text for c in claims])
    for claim, score in zip(claims, scores):
        if score is None:
            continue
        claim.decision_role = score["decision_role"]
        claim.relevance = score["relevance"]
        claim.relevance_reason = score["relevance_reason"]
        claim.bears_on = score["bears_on"]
        report["claims_rescored"] += 1
    await session.commit()
