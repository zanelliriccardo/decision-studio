"""Causes that are not independent: where noisy-OR overstates a belief.

Noisy-OR combines a node's causes as independent chances: the effect happens
unless every cause fails to trigger it, ``1 - Π(1 - c_i)``. When two causes
share an upstream driver they rise and fall together, and counting them as two
separate chances inflates the effect. "Budget cut" (50%) causing both "hiring
freeze" and "tooling delayed", both causing "miss the date": noisy-OR says 75%,
but if the budget is not cut neither happens, and the honest figure is nearer
50%.

This module does not replace the model; it bounds it. For every OR node whose
causes share an ancestor within ``SHARED_DEPTH`` hops, the causes in each
related group are combined as if they moved together — the largest single
contribution, the Fréchet lower bound for a union of positively dependent
events — and the whole graph is propagated again. Each node then carries two
figures: the belief as usually computed (independent causes) and the belief if
related causes are one cause. The truth lies between them; a large gap means
the number shown depends on an independence assumption the map cannot support.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from decision_studio.graph.belief_propagation import _evidence_modulation, _root_prior

#: How far up to look for a shared driver. Two hops catches the common case
#: (a sibling pair, or a cause that also feeds the other cause) without calling
#: every pair of causes in a dense map "related" through a distant root.
SHARED_DEPTH = 2

#: A gap below this is not worth showing.
MATERIAL_GAP = 0.05


@dataclass
class SharedCause:
    """A node whose causes are not independent."""

    node: str
    #: Groups of parents that share a driver (each of size >= 2).
    groups: list[set[str]]
    #: The shared upstream claims.
    shared: set[str] = field(default_factory=set)


def _ancestors_within(graph: nx.DiGraph, node: str, depth: int) -> set[str]:
    """The node and its ancestors up to ``depth`` hops."""
    seen = {node}
    frontier = {node}
    for _ in range(depth):
        frontier = {p for n in frontier for p in graph.predecessors(n)} - seen
        seen |= frontier
    return seen


def find_shared_causes(graph: nx.DiGraph, depth: int = SHARED_DEPTH) -> dict[str, SharedCause]:
    """OR nodes with two or more non-inhibiting causes that share a driver."""
    found: dict[str, SharedCause] = {}
    for node in graph.nodes:
        if (graph.nodes[node].get("logic_gate", "or") or "or") == "and":
            continue
        parents = [
            p for p in graph.predecessors(node)
            if graph.edges[p, node].get("causal_type") != "inhibiting"
        ]
        if len(parents) < 2:
            continue
        reach = {p: _ancestors_within(graph, p, depth) for p in parents}
        # Union-find over parents: two are related when their reaches overlap.
        group_of = {p: {p} for p in parents}
        shared: set[str] = set()
        for i, a in enumerate(parents):
            for b in parents[i + 1:]:
                common = reach[a] & reach[b]
                if common and group_of[a] is not group_of[b]:
                    merged = group_of[a] | group_of[b]
                    for member in merged:
                        group_of[member] = merged
                if common:
                    shared |= common
        groups = {id(g): g for g in group_of.values() if len(g) > 1}
        if groups:
            found[node] = SharedCause(node=node, groups=list(groups.values()), shared=shared)
    return found


def dependent_beliefs(graph: nx.DiGraph, shared: dict[str, SharedCause]) -> dict[str, float]:
    """Beliefs if related causes move together (their largest contribution counts).

    Mirrors ``propagate_beliefs`` exactly except at the nodes in ``shared``, and
    propagates the lower figures downstream so the bound compounds like the
    belief does.
    """
    try:
        order = list(nx.topological_sort(graph))
    except nx.NetworkXUnfeasible:
        order = list(graph.nodes)

    beliefs: dict[str, float] = {}
    for node in order:
        parents = list(graph.predecessors(node))
        if not parents:
            beliefs[node] = _root_prior(graph, node)
            continue

        def contribution(parent: str) -> float:
            data = graph.edges[parent, node]
            effective = data.get("strength", 0.5) * _evidence_modulation(
                data.get("evidence_score", 0.5), data.get("has_contradiction", False)
            )
            return beliefs.get(parent, 0.5) * effective

        if (graph.nodes[node].get("logic_gate", "or") or "or") == "and":
            product = 1.0
            for parent in parents:
                product *= contribution(parent)
            beliefs[node] = max(0.0, min(1.0, product))
            continue

        inhibition = 1.0
        causes: list[str] = []
        for parent in parents:
            if graph.edges[parent, node].get("causal_type") == "inhibiting":
                inhibition *= 1.0 - contribution(parent)
            else:
                causes.append(parent)

        grouped: list[list[str]] = []
        in_group: set[str] = set()
        for group in (shared[node].groups if node in shared else []):
            members = [p for p in causes if p in group]
            grouped.append(members)
            in_group |= set(members)
        grouped += [[p] for p in causes if p not in in_group]

        product = 1.0
        for members in grouped:
            product *= 1.0 - max(contribution(p) for p in members)
        beliefs[node] = max(0.0, min(1.0, (1.0 - product) * inhibition))
    return beliefs


def dependence_report(graph: nx.DiGraph) -> dict[str, dict]:
    """Per node whose belief depends materially on causes being independent.

    ``{node: {"belief_if_dependent": float, "shared_with": [ids]}}``, only for
    nodes where the gap to the propagated ``belief`` is at least MATERIAL_GAP.
    Reads ``belief`` from the graph, so call it after ``propagate_beliefs``.
    """
    shared = find_shared_causes(graph)
    if not shared:
        return {}
    lower = dependent_beliefs(graph, shared)
    report: dict[str, dict] = {}
    for node, value in lower.items():
        belief = graph.nodes[node].get("belief")
        if belief is None or belief - value < MATERIAL_GAP:
            continue
        drivers = shared[node].shared if node in shared else set()
        report[node] = {
            "belief_if_dependent": round(value, 4),
            "shared_with": sorted(drivers),
        }
    return report
