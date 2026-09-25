"""Graph API routes.

Provides endpoints to retrieve the full causal graph (with computed beliefs,
sensitivity, and critical path), update individual edges, and interact with
the graph in real time via WebSocket.
"""

from __future__ import annotations

import json
import logging
from uuid import UUID

import networkx as nx
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from decision_studio.api.models.graph import (
    ClaimResponse,
    EdgeResponse,
    EdgeUpdateRequest,
    EvidenceResponse,
    GraphResponse,
)
from decision_studio.db.models import CausalEdge, Claim, Project
from decision_studio.pipeline.evidence_grounder import EvidenceGrounder
from decision_studio.db.session import async_session, get_session
from decision_studio.graph.belief_propagation import propagate_beliefs
from decision_studio.graph.stability import belief_intervals
from decision_studio.graph.critical_path import find_critical_path
from decision_studio.graph.edge_weight import inflation as edge_inflation
from decision_studio.reasoning.effective_graph import effective_strength

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["graph"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_nx_graph(
    claims: list[Claim],
    edges: list[CausalEdge],
) -> nx.DiGraph:
    """Build a NetworkX DiGraph from ORM claim and edge objects."""
    g = nx.DiGraph()

    for claim in claims:
        g.add_node(
            str(claim.id),
            text=claim.text,
            claim_type=claim.claim_type,
            confidence=claim.confidence,
            prior=getattr(claim, "prior", claim.confidence),
            order_index=claim.order_index,
            logic_gate=getattr(claim, "logic_gate", "or") or "or",
        )

    for edge in edges:
        # Skip feedback edges — they must not participate in belief propagation
        if getattr(edge, "is_feedback", False):
            continue
        g.add_edge(
            str(edge.source_claim_id),
            str(edge.target_claim_id),
            edge_id=str(edge.id),
            mechanism=edge.mechanism,
            strength=edge.strength,
            time_delay=edge.time_delay,
            conditions=edge.conditions,
            reversible=edge.reversible,
            evidence_score=edge.evidence_score,
            # Only contradiction may push an edge below the evidence floor.
            has_contradiction=any(
                ev.evidence_type == "contradicting" for ev in (edge.evidences or [])
            ),
            causal_type=getattr(edge, "causal_type", "direct") or "direct",
            condition_type=getattr(edge, "condition_type", "contributing") or "contributing",
            temporal_window=getattr(edge, "temporal_window", None),
            decay_type=getattr(edge, "decay_type", "none") or "none",
            bias_warnings=getattr(edge, "bias_warnings", None) or [],
        )

    return g


def _break_cycles(graph: nx.DiGraph) -> nx.DiGraph:
    """Break cycles by iteratively removing the weakest edge in each cycle.

    A safety net, not the primary mechanism. The pipeline already breaks cycles
    during DAG construction and records the result on the edges themselves, so
    a graph read normally finds none. Cycles reaching here mean either an
    analysis that predates that marking, or edges added by hand since.

    Which is why the per-edge lines are DEBUG and the summary is one INFO line.
    They were INFO each, and a large graph produced hundreds of identical lines
    on every single read — burying anything else in the log and saying nothing
    the summary does not.
    """
    max_iterations = graph.number_of_edges()
    broken = 0
    for _ in range(max_iterations):
        try:
            list(nx.topological_sort(graph))
            break
        except nx.NetworkXUnfeasible:
            try:
                cycle = nx.find_cycle(graph)
            except nx.NetworkXError:
                break
            weakest_edge = None
            weakest_score = float("inf")
            for u, v, *_ in cycle:
                data = graph.edges[u, v]
                score = data.get("strength", 0.5) * data.get("evidence_score", 0.5)
                if score < weakest_score:
                    weakest_score = score
                    weakest_edge = (u, v)
            if weakest_edge is None:
                break
            broken += 1
            logger.debug(
                "Breaking cycle in graph read: removing edge %s -> %s (score=%.3f)",
                weakest_edge[0], weakest_edge[1], weakest_score,
            )
            graph.remove_edge(*weakest_edge)
    if broken:
        # One line rather than one per edge. Worth an INFO because it means the
        # stored graph still contains cycles, which is a fact about the data
        # rather than about this request.
        logger.info(
            "Graph read broke %d cycle(s) not marked during analysis — "
            "re-running the analysis would record them once instead",
            broken,
        )

    return graph


def _assemble_graph_response(
    project_id: UUID,
    claims: list[Claim],
    edges: list[CausalEdge],
    graph: nx.DiGraph,
    sensitivity: dict[str, dict[str, float]],
    critical_path: list[str],
    has_temporal: bool = True,
    intervals: dict[str, tuple[float, float]] | None = None,
    graph_revision: int = 1,
    decision_objective: str | None = None,
) -> GraphResponse:
    """Build a GraphResponse from DB objects and computed graph attributes."""
    critical_path_set = set(critical_path)
    node_sensitivities = sensitivity.get("nodes", {})
    edge_sensitivities = sensitivity.get("edges", {})

    # Detect convergence points: nodes with in_degree > 1
    convergence_points = {
        str(node)
        for node in graph.nodes()
        if graph.in_degree(node) > 1
    }

    claim_responses: list[ClaimResponse] = []
    for claim in claims:
        node_id = str(claim.id)
        node_data = graph.nodes.get(node_id, {})
        claim_responses.append(
            ClaimResponse(
                id=claim.id,
                text=claim.text,
                claim_type=claim.claim_type,
                confidence=claim.confidence,
                belief=node_data.get("belief"),
                sensitivity=node_sensitivities.get(node_id),
                is_critical_path=node_id in critical_path_set,
                is_convergence_point=node_id in convergence_points,
                logic_gate=getattr(claim, "logic_gate", "or") or "or",
                order_index=claim.order_index,
                source_sentence=getattr(claim, "source_sentence", None),
                belief_low=intervals.get(node_id, (None, None))[0] if intervals else None,
                belief_high=intervals.get(node_id, (None, None))[1] if intervals else None,
                review_status=getattr(claim, "review_status", "accepted") or "accepted",
                is_active=getattr(claim, "is_active", True),
                user_note=getattr(claim, "user_note", None),
                prior=getattr(claim, "prior", claim.confidence),
                corroborated_by=getattr(claim, "corroborated_by", None),
                duplicate_count=getattr(claim, "duplicate_count", 0) or 0,
            )
        )

    edge_responses: list[EdgeResponse] = []
    for edge in edges:
        edge_key = f"{edge.source_claim_id}->{edge.target_claim_id}"
        evidence_list = [
            EvidenceResponse(
                id=ev.id,
                evidence_type=ev.evidence_type,
                source_url=ev.source_url,
                source_title=ev.source_title,
                source_type=ev.source_type,
                snippet=ev.snippet,
                relevance_score=ev.relevance_score,
                credibility_score=ev.credibility_score,
                source_tier=getattr(ev, "source_tier", 4) or 4,
                freshness_score=getattr(ev, "freshness_score", 0.5) or 0.5,
                published_date=getattr(ev, "published_date", None),
            )
            for ev in edge.evidences
        ]

        # Compute consensus from evidence list
        ev_dicts = [
            {"evidence_type": ev.evidence_type}
            for ev in edge.evidences
        ]
        consensus = EvidenceGrounder.compute_consensus_level(ev_dicts)

        edge_responses.append(
            EdgeResponse(
                id=edge.id,
                source_claim_id=edge.source_claim_id,
                target_claim_id=edge.target_claim_id,
                mechanism=edge.mechanism,
                strength=edge.strength,
                time_delay=edge.time_delay,
                conditions=edge.conditions if isinstance(edge.conditions, list) else None,
                reversible=edge.reversible,
                evidence_score=edge.evidence_score,
            # Only contradiction may push an edge below the evidence floor.
            has_contradiction=any(
                ev.evidence_type == "contradicting" for ev in (edge.evidences or [])
            ),
                causal_type=getattr(edge, "causal_type", "direct") or "direct",
                condition_type=getattr(edge, "condition_type", "contributing") or "contributing",
                temporal_window=getattr(edge, "temporal_window", None),
                decay_type=getattr(edge, "decay_type", "none") or "none",
                bias_warnings=getattr(edge, "bias_warnings", None) or [],
                consensus_level=consensus,
                sensitivity=edge_sensitivities.get(edge_key),
                is_feedback=getattr(edge, "is_feedback", False),
                evidences=evidence_list,
                statistical_validation=getattr(edge, "statistical_validation", None),
                stat_p_value=getattr(edge, "stat_p_value", None),
                stat_f_statistic=getattr(edge, "stat_f_statistic", None),
                stat_effect_size=getattr(edge, "stat_effect_size", None),
                stat_lag=getattr(edge, "stat_lag", None),
                review_status=getattr(edge, "review_status", "accepted") or "accepted",
                is_active=getattr(edge, "is_active", True),
                user_note=getattr(edge, "user_note", None),
                strength_override=getattr(edge, "strength_override", None),
                effective_strength=effective_strength(edge),
                effect=getattr(edge, "effect", edge.strength),
                link_confidence=getattr(edge, "link_confidence", 1.0),
                author_effect=getattr(edge, "author_effect", None),
                author_confidence=getattr(edge, "author_confidence", None),
                blind_scored=getattr(edge, "blind_scored", False),
                inflation=edge_inflation(
                    getattr(edge, "author_effect", None),
                    getattr(edge, "author_confidence", None),
                    getattr(edge, "effect", edge.strength),
                    getattr(edge, "link_confidence", 1.0),
                ),
            )
        )

    critical_path_uuids = [UUID(nid) for nid in critical_path]

    return GraphResponse(
        project_id=project_id,
        claims=claim_responses,
        edges=edge_responses,
        critical_path=critical_path_uuids,
        has_temporal=has_temporal,
        graph_revision=graph_revision,
        decision_objective=decision_objective,
    )


async def _load_project_graph(
    project_id: UUID,
    session: AsyncSession,
) -> tuple[Project, list[Claim], list[CausalEdge]]:
    """Load a project with its claims and edges (including evidences).

    Raises HTTPException(404) if the project does not exist.
    """
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    claims_result = await session.execute(
        select(Claim)
        .where(Claim.project_id == project_id)
        .order_by(Claim.order_index)
    )
    claims = list(claims_result.scalars().all())

    edges_result = await session.execute(
        select(CausalEdge)
        .where(CausalEdge.project_id == project_id)
        .options(selectinload(CausalEdge.evidences))
    )
    edges = list(edges_result.scalars().all())

    return project, claims, edges


async def _compute_full_graph(
    project_id: UUID,
    session: AsyncSession,
) -> GraphResponse:
    """Load project data, run graph analysis, and return a GraphResponse."""
    project, claims, edges = await _load_project_graph(project_id, session)
    has_temporal = getattr(project, 'has_temporal', True)

    graph_revision = getattr(project, "graph_revision", 1) or 1
    decision_objective = getattr(project, "decision_objective", None)

    if not claims:
        return GraphResponse(
            project_id=project_id, claims=[], edges=[], has_temporal=has_temporal,
            graph_revision=graph_revision, decision_objective=decision_objective,
        )

    graph = _build_nx_graph(claims, edges)
    graph = _break_cycles(graph)
    graph = propagate_beliefs(graph)
    # Monte Carlo rather than one-node worst-case perturbation: uncertainty
    # compounds along chains, and per-edge noise is scaled by link_confidence.
    intervals = belief_intervals(graph)
    # Skip expensive sensitivity analysis on graph load — it deep-copies the
    # graph 2× per edge and re-propagates beliefs each time (1,244+ runs on a
    # 622-edge graph).  Sensitivity is available via a dedicated endpoint.
    sensitivity: dict[str, dict[str, float]] = {"edges": {}, "nodes": {}}
    critical_path = find_critical_path(graph)

    return _assemble_graph_response(
        project_id, claims, edges, graph, sensitivity, critical_path,
        has_temporal=has_temporal,
        intervals=intervals,
        graph_revision=graph_revision,
        decision_objective=decision_objective,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/graph/{project_id}", response_model=GraphResponse)
async def get_graph(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> GraphResponse:
    """Retrieve the full causal graph for a project.

    Includes belief propagation scores, sensitivity analysis, and
    critical-path annotations.
    """
    return await _compute_full_graph(project_id, session)


@router.patch("/edge/{edge_id}", response_model=EdgeResponse)
async def update_edge(
    edge_id: UUID,
    req: EdgeUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> EdgeResponse:
    """Update an edge's causal strength.

    Returns the updated edge (without re-running full graph analysis).
    """
    result = await session.execute(
        select(CausalEdge)
        .where(CausalEdge.id == edge_id)
        .options(selectinload(CausalEdge.evidences))
    )
    edge = result.scalars().first()
    if edge is None:
        raise HTTPException(status_code=404, detail="Edge not found")

    edge.strength = req.strength
    await session.commit()
    await session.refresh(edge)

    evidence_list = [
        EvidenceResponse(
            id=ev.id,
            evidence_type=ev.evidence_type,
            source_url=ev.source_url,
            source_title=ev.source_title,
            source_type=ev.source_type,
            snippet=ev.snippet,
            relevance_score=ev.relevance_score,
            credibility_score=ev.credibility_score,
            source_tier=getattr(ev, "source_tier", 4) or 4,
            freshness_score=getattr(ev, "freshness_score", 0.5) or 0.5,
            published_date=getattr(ev, "published_date", None),
        )
        for ev in edge.evidences
    ]

    return EdgeResponse(
        id=edge.id,
        source_claim_id=edge.source_claim_id,
        target_claim_id=edge.target_claim_id,
        mechanism=edge.mechanism,
        strength=edge.strength,
        time_delay=edge.time_delay,
        conditions=edge.conditions if isinstance(edge.conditions, list) else None,
        reversible=edge.reversible,
        evidence_score=edge.evidence_score,
        causal_type=getattr(edge, "causal_type", "direct") or "direct",
        condition_type=getattr(edge, "condition_type", "contributing") or "contributing",
        temporal_window=getattr(edge, "temporal_window", None),
        decay_type=getattr(edge, "decay_type", "none") or "none",
        bias_warnings=getattr(edge, "bias_warnings", None) or [],
        is_feedback=getattr(edge, "is_feedback", False),
        evidences=evidence_list,
        statistical_validation=getattr(edge, "statistical_validation", None),
        stat_p_value=getattr(edge, "stat_p_value", None),
        stat_f_statistic=getattr(edge, "stat_f_statistic", None),
        stat_effect_size=getattr(edge, "stat_effect_size", None),
        stat_lag=getattr(edge, "stat_lag", None),
        review_status=getattr(edge, "review_status", "accepted") or "accepted",
        is_active=getattr(edge, "is_active", True),
        user_note=getattr(edge, "user_note", None),
        strength_override=getattr(edge, "strength_override", None),
        effective_strength=effective_strength(edge),
        effect=getattr(edge, "effect", edge.strength),
        link_confidence=getattr(edge, "link_confidence", 1.0),
        author_effect=getattr(edge, "author_effect", None),
        author_confidence=getattr(edge, "author_confidence", None),
        blind_scored=getattr(edge, "blind_scored", False),
    )


@router.websocket("/ws/graph/{project_id}")
async def graph_websocket(websocket: WebSocket, project_id: UUID) -> None:
    """WebSocket for real-time graph interaction.

    The client can send JSON messages to update edges::

        {"action": "update_edge", "edge_id": "<uuid>", "strength": 0.7}

    The server responds with the full updated GraphResponse.
    """
    await websocket.accept()

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"error": "Invalid JSON"})
                continue

            action = message.get("action")

            if action == "update_edge":
                edge_id_str = message.get("edge_id")
                new_strength = message.get("strength")

                if edge_id_str is None or new_strength is None:
                    await websocket.send_json(
                        {"error": "Missing edge_id or strength"}
                    )
                    continue

                try:
                    edge_uuid = UUID(edge_id_str)
                    new_strength = float(new_strength)
                    if not (0.0 <= new_strength <= 1.0):
                        raise ValueError("strength must be between 0 and 1")
                except (ValueError, TypeError) as exc:
                    await websocket.send_json({"error": str(exc)})
                    continue

                # Update the edge in the database and re-compute graph
                async with async_session() as session:
                    result = await session.execute(
                        select(CausalEdge).where(CausalEdge.id == edge_uuid)
                    )
                    edge = result.scalars().first()
                    if edge is None:
                        await websocket.send_json({"error": "Edge not found"})
                        continue

                    edge.strength = new_strength
                    await session.commit()

                    # Re-compute the full graph
                    graph_response = await _compute_full_graph(
                        project_id, session
                    )

                await websocket.send_json(
                    graph_response.model_dump(mode="json")
                )

            else:
                await websocket.send_json(
                    {"error": f"Unknown action: {action}"}
                )

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for project %s", project_id)
    except Exception as exc:
        logger.exception(
            "WebSocket error for project %s: %s", project_id, exc
        )
        try:
            await websocket.close(code=1011, reason=str(exc))
        except Exception:
            pass
