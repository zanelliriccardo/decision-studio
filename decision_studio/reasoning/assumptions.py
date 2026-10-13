"""The assumption register: the claims the decision rests on, most at stake first.

Nothing is invented. An assumption is an existing claim in the reviewed graph
that the options do not set themselves — a contingency, a mechanism, a fact
taken as given — and that can reach a success criterion. For each one the
register gathers what the analysis already knows:

* current belief (propagated on the reviewed graph, the same numbers the graph
  screen shows);
* related options (``bears_on`` and the theories that cite it) and the success
  criteria it has a causal path to;
* the documents behind its links (reasoning/evidence_quality.summarise_documents);
* whether a theory that cites it is out of date, or it was marked as needing
  evidence;
* whether it is a sensitivity driver of the option comparison, and whether moving
  it within its plausible range could materially alter that comparison
  (graph/option_sensitivity.py).

## Ranking

``priority = uncertainty × influence``

* **uncertainty** = ``4·b·(1−b)`` of the current belief (1 at 50%, 0 at 0/100%);
* **influence** = the largest movement, caused by the claim (as a root claim's
  prior or through the links into and out of it), of the gap between the two
  leading options — on the weighted view or on any single success criterion,
  whichever is larger — in points ÷ 20, capped at 1 (the same scale as
  information priority), multiplied by 1 if it can reverse the comparison,
  0.75 if it can close the gap, 0.5 otherwise. The per-criterion gap counts
  because an assumption that swings one criterion matters even when the
  priorities happen to hide it.

An assumption that moves every option alike (a market that lifts or sinks all
of them) does not change the comparison but does change whether any option
succeeds. It is kept, at a quarter of the weight, and labelled
``affects = "all_options"``; one that moves the gap is ``"comparison"``.

Claims with no influence on the comparison are left out. When no comparison
can be made, the model's relevance score stands in for influence and each row
says so.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import networkx as nx
from sqlalchemy.ext.asyncio import AsyncSession

from decision_studio.graph.belief_propagation import propagate_beliefs
from decision_studio.graph.option_sensitivity import ERASES, FLIPS
from decision_studio.reasoning.decision_anchor import ORIGIN_FRAME, ROLE_OUTCOME
from decision_studio.reasoning.evidence_quality import summarise_documents
from decision_studio.reasoning.information_priority import (
    DEFAULT_RELEVANCE,
    FULL_IMPACT_POINTS,
    RELEVANCE,
)
from decision_studio.reasoning.option_comparison import (
    MAX_DRIVERS,
    OptionComparison,
    is_reportable,
    outcome_node_map,
)

MAX_ASSUMPTIONS = 8
#: An assumption that moves every option alike counts at a quarter of the weight.
ALL_OPTIONS_WEIGHT = 0.25
#: Moving the weighted gap by at least this much (5 points) counts as material.
MATERIAL_SHIFT = 0.05


def _uncertainty(belief: float | None) -> float:
    b = 0.5 if belief is None else max(0.0, min(1.0, belief))
    return round(4 * b * (1 - b), 4)


def build_register(
    graph: nx.DiGraph,
    claims: list[Any],
    anchor: dict[str, Any] | None,
    comparison: OptionComparison | None,
    theories: list[Any],
    evidence_by_edge: dict[str, list[Any]],
    *,
    limit: int = MAX_ASSUMPTIONS,
) -> dict[str, Any]:
    """The register, as plain data for the API and the report."""
    propagated = propagate_beliefs(graph.copy())
    outcomes = outcome_node_map(claims, anchor, graph)
    outcome_of_node = {node: key for key, node in outcomes.items()}
    option_keys = {o["key"] for o in (anchor or {}).get("options", [])}
    switched = set()
    if comparison is not None:
        switched = {cid for row in comparison.options for cid, _ in row.levers_on + row.levers_off}

    # Influence of each claim on the comparison, from the ranked drivers.
    influence: dict[str, tuple[float, str, int | None]] = {}
    level: dict[str, float] = {}
    use_drivers = comparison is not None and not comparison.unavailable and comparison.driver_impacts
    if use_drivers:
        reportable = [i for i in comparison.driver_impacts if is_reportable(i)]
        rank_of = {id(i): rank for rank, i in enumerate(reportable, start=1)}
        for impact in comparison.driver_impacts:
            driver = impact.driver
            involved = [driver.key] if driver.kind == "claim" else [driver.source, driver.target]
            per_criterion = max((abs(h - l) for l, h in impact.outcome_gaps.values()), default=0.0)
            size = max(impact.impact, per_criterion)
            flip = impact.flip
            if flip == "no_flip" and FLIPS in impact.outcome_flips.values():
                flip = FLIPS
            nodes = {n for values in driver.effects.values() for n in values}
            moved = max(
                (sum(abs(v[n][1] - v[n][0]) for v in driver.effects.values()) / len(driver.effects)
                 for n in nodes), default=0.0)
            for claim_id in involved:
                best = influence.get(claim_id)
                if best is None or size > best[0]:
                    influence[claim_id] = (size, flip, rank_of.get(id(impact)))
                level[claim_id] = max(level.get(claim_id, 0.0), moved)

    cited_by: dict[str, list[Any]] = {}
    for theory in theories:
        for link in getattr(theory, "claim_links", []) or []:
            cited_by.setdefault(str(link.claim_id), []).append(theory)

    rows = []
    for claim in claims:
        cid = str(claim.id)
        if cid not in graph or cid in switched or cid in outcome_of_node:
            continue
        if getattr(claim, "origin", None) == ORIGIN_FRAME or getattr(claim, "decision_role", None) == ROLE_OUTCOME:
            continue
        reaches = sorted(
            outcome_of_node[n] for n in nx.descendants(graph, cid) if n in outcome_of_node
        )
        if not reaches:
            continue
        belief = propagated.nodes[cid].get("belief")
        uncertainty = _uncertainty(belief)

        affects = None
        if use_drivers:
            impact, flip, rank = influence.get(cid, (0.0, "no_flip", None))
            on_gap = min(1.0, impact * 100 / FULL_IMPACT_POINTS) * RELEVANCE.get(flip, DEFAULT_RELEVANCE)
            on_level = min(1.0, level.get(cid, 0.0) * 100 / FULL_IMPACT_POINTS) * ALL_OPTIONS_WEIGHT
            weight = max(on_gap, on_level)
            affects = "comparison" if on_gap >= on_level else "all_options"
            basis = "comparison"
        else:
            impact, flip, rank = 0.0, "no_flip", None
            weight = float(getattr(claim, "relevance", None) or 0.0) * DEFAULT_RELEVANCE
            basis = "relevance"
        priority = round(uncertainty * weight, 4)
        if priority <= 0:
            continue

        theories_here = cited_by.get(cid, [])
        options = sorted(
            (set(getattr(claim, "bears_on", None) or []) & option_keys)
            | {t.option_key for t in theories_here if getattr(t, "option_key", None) in option_keys}
        )
        stale = [t.title for t in theories_here if getattr(t, "is_stale", False)]
        edges = [e for e in (list(graph.in_edges(cid, data=True)) + list(graph.out_edges(cid, data=True)))]
        documents = []
        for _, _, data in edges:
            documents += evidence_by_edge.get(data.get("edge_id") or "", [])
        rows.append({
            "claim_id": cid,
            "text": claim.text,
            "decision_role": getattr(claim, "decision_role", None),
            "belief": round(belief, 4) if belief is not None else None,
            "uncertainty": uncertainty,
            "options": options,
            "outcomes": reaches,
            "evidence": summarise_documents(documents),
            "needs_evidence": getattr(claim, "review_status", None) == "needs_evidence",
            "stale": bool(stale),
            "stale_theories": stale,
            "driver_rank": rank if rank is not None and rank <= MAX_DRIVERS else None,
            "impact": round(impact, 4),
            "can_alter": use_drivers and (flip in (FLIPS, ERASES) or impact >= MATERIAL_SHIFT),
            "flip": flip,
            "affects": affects,
            "level_impact": round(level.get(cid, 0.0), 4),
            "influence_basis": basis,
            "priority": priority,
        })
    rows.sort(key=lambda r: (-r["priority"], r["text"]))
    return {
        "assumptions": rows[:limit],
        "total": len(rows),
        "influence_basis": "comparison" if use_drivers else "relevance",
    }


async def assumption_register(
    session: AsyncSession, project_id: UUID, comparison: OptionComparison | None = None
) -> dict[str, Any]:
    """The register for a project, computing the comparison when not given."""
    from decision_studio.reasoning.decision_anchor import project_anchor
    from decision_studio.reasoning.effective_graph import load_effective_snapshot
    from decision_studio.reasoning.link_tests import snapshot_graph
    from decision_studio.reasoning.option_comparison import compare_project_options
    from decision_studio.reasoning.theories import list_current_theories

    if comparison is None:
        comparison = await compare_project_options(session, project_id)
    snapshot = await load_effective_snapshot(project_id, session)
    return build_register(
        snapshot_graph(snapshot), snapshot.claims, await project_anchor(session, project_id),
        comparison, await list_current_theories(session, project_id), snapshot.evidence_by_edge,
    )
