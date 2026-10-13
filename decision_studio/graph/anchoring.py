"""How far each claim sits from the decision, measured on the graph.

The model's relevance score is a reading of one claim in isolation. It misses
the case that matters most: a claim that looks like background, and turns out
to feed a chain ending at an outcome. That is the surprising factor this tool
exists to surface, and a relevance filter based on the model's reading alone
would discard it.

So relevance has two sources here, and the effective value is the larger:

* **stated** — the model's 0-1 score from extraction or re-scoring;
* **structural** — derived from the number of causal hops between the claim and
  the nearest outcome node, following edge direction.

Taking the maximum means a claim can only be *promoted* by structure, never
demoted by it: a claim the model rates as decisive stays decisive even where
causal inference failed to connect it — a missed edge is not evidence of
irrelevance.

All functions are pure and take plain dicts or a networkx graph, so they are
shared by the pipeline (which works on index-keyed dicts) and the API (which
works on UUID-keyed graphs).
"""

from __future__ import annotations

from collections import deque
from typing import Any, Hashable, Iterable

import networkx as nx

#: Structural relevance by hop count to the nearest outcome.
#:
#: Hand-chosen, like every threshold in HANDOVER §10, and uncalibrated. The
#: shape is what matters: an outcome itself is 1.0, a direct cause 0.85, and the
#: value decays so a claim four hops out still outranks one with no path at all.
STRUCTURAL_BY_DISTANCE = {0: 1.0, 1: 0.85, 2: 0.65, 3: 0.45}
STRUCTURAL_FAR = 0.3

#: Hops within which the decision lens shows a claim.
LENS_MAX_DISTANCE = 3
#: Stated relevance at which the lens shows a claim regardless of distance.
LENS_MIN_RELEVANCE = 0.5
#: Below this stated relevance, a claim on a path to an outcome is "peripheral
#: but connected" — the model read it as background, the graph disagrees.
PERIPHERAL_BELOW = 0.4


def anchor_distances(
    graph: nx.DiGraph,
    outcome_nodes: Iterable[Hashable],
) -> dict[Hashable, int]:
    """Hops from each node to the nearest outcome, following edge direction.

    Only nodes with a directed path to an outcome appear: a claim *caused by* an
    outcome is a consequence of success, not a factor in reaching it. Outcomes
    themselves are at distance 0.
    """
    distances: dict[Hashable, int] = {}
    queue: deque[Hashable] = deque()
    for node in outcome_nodes:
        if graph.has_node(node):
            distances[node] = 0
            queue.append(node)

    while queue:
        node = queue.popleft()
        for parent in graph.predecessors(node):
            if parent not in distances:
                distances[parent] = distances[node] + 1
                queue.append(parent)
    return distances


def structural_relevance(distance: int | None) -> float:
    """Relevance implied by graph position alone. 0.0 with no path."""
    if distance is None:
        return 0.0
    return STRUCTURAL_BY_DISTANCE.get(distance, STRUCTURAL_FAR)


def effective_relevance(stated: float | None, distance: int | None) -> float | None:
    """The larger of stated and structural relevance.

    None when neither exists — a project without an anchor has no notion of
    relevance, and inventing a zero would rank every claim as irrelevant.
    """
    if stated is None and distance is None:
        return None
    return max(stated or 0.0, structural_relevance(distance))


def is_peripheral(stated: float | None, distance: int | None) -> bool:
    """Read as background, but on a causal path to an outcome."""
    return (
        stated is not None
        and stated < PERIPHERAL_BELOW
        and distance is not None
        and distance > 0
    )


def in_lens(stated: float | None, distance: int | None) -> bool:
    """Whether the decision lens shows this claim by default."""
    if distance is not None and distance <= LENS_MAX_DISTANCE:
        return True
    return stated is not None and stated >= LENS_MIN_RELEVANCE


# ---------------------------------------------------------------------------
# Pipeline helpers: claims are dicts, edges refer to them by list index.
# ---------------------------------------------------------------------------


def is_outcome_claim(claim: dict[str, Any]) -> bool:
    """An anchor outcome node."""
    return claim.get("decision_role") == "outcome" and claim.get("origin") == "frame"


def outcome_indices(claims: list[dict[str, Any]]) -> list[int]:
    """Indices of the anchor outcome nodes in a claim list."""
    return [i for i, c in enumerate(claims) if is_outcome_claim(c)]


def index_graph(claims: list[dict[str, Any]], edges: list[dict[str, Any]]) -> nx.DiGraph:
    """A plain directed graph over claim indices, for distance computations."""
    graph = nx.DiGraph()
    graph.add_nodes_from(range(len(claims)))
    for edge in edges:
        source, target = edge.get("source_idx"), edge.get("target_idx")
        if isinstance(source, int) and isinstance(target, int):
            graph.add_edge(source, target)
    return graph


def claim_distances(
    claims: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> dict[int, int]:
    """Hop distance to the nearest outcome for each claim index."""
    outcomes = outcome_indices(claims)
    if not outcomes:
        return {}
    return anchor_distances(index_graph(claims, edges), outcomes)


def edge_priority(edge: dict[str, Any], claims: list[dict[str, Any]]) -> float:
    """Sort key for the edge budget: strength, weighted by relevance.

    Strength alone kept the most confident links whether or not they bore on
    anything. Weighting by the more relevant endpoint means a strong link
    between two background facts yields its slot to a moderate one feeding an
    outcome. Unscored endpoints weigh 1.0, which is exactly the old ordering —
    so a project without an anchor prunes as it always did.
    """
    strength = float(edge.get("strength", 0.0) or 0.0)
    relevances: list[float] = []
    for key in ("source_idx", "target_idx"):
        index = edge.get(key)
        if not isinstance(index, int) or not 0 <= index < len(claims):
            continue
        claim = claims[index]
        if is_outcome_claim(claim):
            relevances.append(1.0)
        elif claim.get("relevance") is not None:
            relevances.append(float(claim["relevance"]))
    if not relevances:
        return strength
    return strength * (0.5 + 0.5 * max(relevances))


def anchored_edges(
    claims: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Edges worth expanding from: on a path to an outcome, or between relevant claims.

    Discovery reads the evidence found for each edge and extracts new claims
    from it. Run over every edge, it follows the documents wherever they go —
    three layers deep into web snippets about whatever the graph happened to
    contain. Restricted to these edges, it follows the decision.

    Returns every edge when the project has no anchor, and when nothing is
    anchored yet: expanding everything is the old behaviour, and expanding
    nothing would end discovery on a graph that has simply not connected yet.
    """
    if not outcome_indices(claims) and all(c.get("relevance") is None for c in claims):
        return edges

    distances = claim_distances(claims, edges)
    kept = []
    for edge in edges:
        source, target = edge.get("source_idx"), edge.get("target_idx")
        # The edge lies on a path to an outcome exactly when its target
        # reaches one: source -> target -> ... -> outcome.
        if target in distances:
            kept.append(edge)
            continue
        relevant = [
            claims[i].get("relevance") or 0.0
            for i in (source, target)
            if isinstance(i, int) and 0 <= i < len(claims)
        ]
        if relevant and min(relevant) >= LENS_MIN_RELEVANCE:
            kept.append(edge)
    return kept or edges
