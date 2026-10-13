"""Noisy-OR belief propagation along a causal DAG.

Propagates belief scores through the graph in topological order using
the Noisy-OR model with evidence modulation.
"""

from __future__ import annotations

import logging

import networkx as nx

logger = logging.getLogger(__name__)

#: Minimum evidence modulation for an edge that was not contradicted. Silence
#: must not be read as refutation -- see _evidence_modulation.
EVIDENCE_FLOOR = 0.30

#: Minimum evidence modulation for an edge that was not contradicted. Silence
#: must not be read as refutation -- see _evidence_modulation.
EVIDENCE_FLOOR = 0.30


def _root_prior(graph, node_id: str) -> float:
    """Seed value for a root node's belief.

    Reads ``prior`` -- the probability the claim is TRUE -- and falls back to
    ``confidence`` only for graphs built before the two were separated.
    ``confidence`` measures how firmly the source asserted the claim, which is a
    property of the writing: a vendor's emphatic promise scores high and is
    usually wrong, while a hedged internal admission scores low and is usually
    right. Seeding beliefs with it inverts exactly the cases that matter.
    """
    node = graph.nodes[node_id]
    if "prior" in node and node["prior"] is not None:
        return node["prior"]
    return node.get("confidence", 0.5)


def _evidence_modulation(
    evidence_score: float, has_contradiction: bool = False
) -> float:
    """How much retrieved evidence should modulate an edge's transmission.

    A floor applies unless the edge was actively contradicted, because a low
    ``evidence_score`` means two entirely different things:

      * "we searched and found nothing supporting this", or
      * "this is an internal fact that no public source could ever confirm".

    The original curve mapped both to ~0, so an unsearchable internal fact --
    "our engineering freeze slipped" -- contributed nothing to any belief, while
    a claim disproved by three sources contributed exactly the same nothing. For
    strategic decisions, where most causal steps are internal and unpublishable,
    that silently deleted the most important part of the graph.

    Absence of evidence widens uncertainty. Only contradiction lowers belief.
    """
    score = max(0.0, min(1.0, evidence_score))
    if has_contradiction:
        # There is a reason to disbelieve this, so it may fall a long way.
        return max(0.05, score ** 1.5)
    return max(EVIDENCE_FLOOR, score ** 1.5)


def _noisy_or_belief_full(
    graph: nx.DiGraph, node_id: str, predecessors: list[str]
) -> float:
    """Compute Noisy-OR belief with inhibiting edge support.

    Normal (non-inhibiting) parents contribute to the OR product.
    Inhibiting parents reduce the final belief multiplicatively.

    With no inhibitors: identical to the original algorithm.
    """
    noisy_or_product = 1.0
    inhibition_factor = 1.0

    for parent_id in predecessors:
        parent_belief = graph.nodes[parent_id].get("belief", 0.5)
        edge_data = graph.edges[parent_id, node_id]
        strength = edge_data.get("strength", 0.5)
        ev_score = edge_data.get("evidence_score", 0.5)
        # The contradiction flag was set on every edge and read by nothing, so
        # a link three sources contradicted kept the same floor as one nobody
        # had searched for — the opposite of what _evidence_modulation states.
        effective = strength * _evidence_modulation(
            ev_score, edge_data.get("has_contradiction", False)
        )
        causal_type = edge_data.get("causal_type", "direct")

        if causal_type == "inhibiting":
            inhibition_factor *= 1.0 - parent_belief * effective
        else:
            noisy_or_product *= 1.0 - parent_belief * effective

    belief = (1.0 - noisy_or_product) * inhibition_factor
    return max(0.0, min(1.0, belief))


def _and_gate_belief(
    graph: nx.DiGraph, node_id: str, predecessors: list[str]
) -> float:
    """Compute AND-gate belief: product of all parent contributions.

    Only non-zero when ALL parents are active. A single inactive parent
    drives the result toward zero.
    """
    belief = 1.0
    for parent_id in predecessors:
        parent_belief = graph.nodes[parent_id].get("belief", 0.5)
        edge_data = graph.edges[parent_id, node_id]
        strength = edge_data.get("strength", 0.5)
        ev_score = edge_data.get("evidence_score", 0.5)
        effective = strength * _evidence_modulation(
            ev_score, edge_data.get("has_contradiction", False)
        )
        belief *= parent_belief * effective

    return max(0.0, min(1.0, belief))


def propagate_beliefs(graph: nx.DiGraph) -> nx.DiGraph:
    """Propagate beliefs through a DAG using gate-aware computation.

    For each node processed in topological order:
    - Root nodes (no parents): belief = claim truth prior.
    - AND-gate nodes: belief = product(parent_belief * effective_strength).
    - OR-gate nodes: Noisy-OR with inhibiting edge support.

    Args:
        graph: A directed acyclic graph with node attributes "confidence"
            and edge attributes "strength" and "evidence_score".

    Returns:
        The same graph with updated "belief" attributes on each node.
    """
    try:
        topo_order = list(nx.topological_sort(graph))
    except nx.NetworkXUnfeasible:
        logger.error("Cannot propagate beliefs: graph contains cycles")
        return graph

    for node_id in topo_order:
        predecessors = list(graph.predecessors(node_id))

        if not predecessors:
            # Root node: belief equals the claim's truth prior
            graph.nodes[node_id]["belief"] = _root_prior(graph, node_id)
        else:
            logic_gate = graph.nodes[node_id].get("logic_gate", "or")
            if logic_gate == "and":
                belief = _and_gate_belief(graph, node_id, predecessors)
            else:
                belief = _noisy_or_belief_full(graph, node_id, predecessors)

            graph.nodes[node_id]["belief"] = belief

    logger.debug("Belief propagation complete for %d nodes", len(topo_order))
    return graph


# DEAD-CODE-CANDIDATE DC-15: marked DEPRECATED in its docstring; no callers (graph/stability.py replaced it). See docs/DEAD_CODE_REPORT.md
def compute_belief_intervals(
    graph: nx.DiGraph, perturbation: float = 0.1
) -> dict[str, tuple[float, float]]:
    """DEPRECATED. Local worst-case bounds; use ``graph.stability.belief_intervals``.

    Despite what this docstring used to claim, it does NOT re-propagate. It
    perturbs one node's incoming edges, recomputes that node alone, and reads
    its parents' beliefs as fixed point values -- so uncertainty never compounds
    along a chain and deep nodes get intervals computed as though everything
    upstream were known exactly. On a two-hop chain the result is half the width
    it should be.

    It also moves every parent in the same direction, which is a perfectly
    correlated worst case rather than a distribution.

    Retained only for callers that need the old numbers for comparison.
    """
    intervals: dict[str, tuple[float, float]] = {}
    try:
        topo_order = list(nx.topological_sort(graph))
    except nx.NetworkXUnfeasible:
        return intervals

    for node_id in topo_order:
        predecessors = list(graph.predecessors(node_id))
        if not predecessors:
            prior = _root_prior(graph, node_id)
            intervals[node_id] = (prior, prior)
            continue

        logic_gate = graph.nodes[node_id].get("logic_gate", "or")
        beliefs: list[float] = []
        for delta in [-perturbation, perturbation]:
            # Temporarily perturb all parent edge strengths
            original_strengths: dict[str, float] = {}
            for p in predecessors:
                original_strengths[p] = graph.edges[p, node_id].get("strength", 0.5)
                graph.edges[p, node_id]["strength"] = max(
                    0.0, min(1.0, original_strengths[p] + delta)
                )

            if logic_gate == "and":
                b = _and_gate_belief(graph, node_id, predecessors)
            else:
                b = _noisy_or_belief_full(graph, node_id, predecessors)
            beliefs.append(b)

            # Restore original strengths
            for p in predecessors:
                graph.edges[p, node_id]["strength"] = original_strengths[p]

        intervals[node_id] = (min(beliefs), max(beliefs))

    return intervals
