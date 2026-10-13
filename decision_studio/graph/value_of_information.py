"""Which link in a theory is most worth testing.

A theory's causal chain is only as good as its weakest link, but "weakest" is
two things at once:

* **leverage** — how much belief in the chain's destination moves when this
  link's strength moves. Measured, not guessed: the link is perturbed by the
  same ±0.20 that ``sensitivity.py`` uses and beliefs are re-propagated.
* **uncertainty** — how little the graph knows about the link. From the link's
  own confidence and its evidence.

Their product is the priority. A link the outcome hardly depends on is not worth
testing however doubtful; a link it depends on entirely is not worth testing if
it is already nailed down. The link that scores high on both is the one whose
test result would most change what the decider should believe — the working
definition of value of information here, and an uncalibrated one: the weights
are conventions, exposed like every threshold in HANDOVER §10.
"""

from __future__ import annotations

import copy
from typing import Any, Iterable

import networkx as nx

from decision_studio.graph.belief_propagation import propagate_beliefs

PERTURBATION = 0.20


def link_uncertainty(link_confidence: float | None, evidence_score: float | None) -> float:
    """How little the graph knows about one link, 0-1.

    Link confidence is whether the link exists at all; evidence halves or keeps
    it. With neither known the answer is "mostly unknown", not zero.
    """
    confidence = 0.5 if link_confidence is None else max(0.0, min(1.0, link_confidence))
    evidence = 0.5 if evidence_score is None else max(0.0, min(1.0, evidence_score))
    return round(1.0 - confidence * (0.5 + 0.5 * evidence), 4)


def break_cycles(graph: nx.DiGraph) -> nx.DiGraph:
    """Remove the weakest edge of each cycle until none remain. Mutates and returns."""
    while True:
        try:
            cycle = nx.find_cycle(graph)
        except nx.NetworkXNoCycle:
            return graph
        weakest = min(cycle, key=lambda e: graph.edges[e[0], e[1]].get("strength", 0.5))
        graph.remove_edge(weakest[0], weakest[1])


def _belief_of(graph: nx.DiGraph, target: str) -> float:
    working = copy.deepcopy(graph)
    propagate_beliefs(working)
    return working.nodes[target].get("belief", 0.5)


def link_leverage(graph: nx.DiGraph, source: str, target_of_edge: str, destination: str) -> float:
    """Largest movement in the destination's belief when one link is perturbed."""
    if not graph.has_edge(source, target_of_edge) or destination not in graph:
        return 0.0
    baseline = _belief_of(graph, destination)
    original = graph.edges[source, target_of_edge].get("strength", 0.5)
    deltas = []
    for strength in (min(1.0, original + PERTURBATION), max(0.0, original - PERTURBATION)):
        graph.edges[source, target_of_edge]["strength"] = strength
        deltas.append(abs(_belief_of(graph, destination) - baseline))
    graph.edges[source, target_of_edge]["strength"] = original
    return round(max(deltas), 4)


def rank_links(
    graph: nx.DiGraph,
    links: Iterable[dict[str, Any]],
    destination: str,
) -> list[dict[str, Any]]:
    """Rank a chain's links by leverage x uncertainty, highest first.

    ``links`` carry ``edge_id``, ``source``, ``target`` and ``uncertainty``.
    When no link has any leverage — the destination is not downstream of the
    chain, or propagation saturates — ranking falls back to uncertainty alone
    rather than returning a list of ties.
    """
    ranked = []
    for link in links:
        leverage = link_leverage(graph, link["source"], link["target"], destination)
        ranked.append({**link, "leverage": leverage})
    if not any(r["leverage"] > 0 for r in ranked):
        for r in ranked:
            r["priority"] = round(r["uncertainty"], 4)
    else:
        for r in ranked:
            r["priority"] = round(r["leverage"] * r["uncertainty"], 4)
    ranked.sort(key=lambda r: r["priority"], reverse=True)
    return ranked
