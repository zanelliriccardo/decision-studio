"""Which assumptions drive the difference between two options.

The option comparison says how often one option comes out higher once every
link strength is shaken at once. This says *which* inputs that depends on. It is
one-at-a-time sensitivity, run on the very graphs the comparison uses:

1. every uncertain input that can reach a success criterion is taken in turn —
   a link strength, or the prior of a root claim the options do not set;
2. it is moved to the low and then the high end of its plausible range, with
   every other input held at its central value;
3. the option graphs are propagated (``stability.propagate_once``, the same
   arithmetic as the comparison and the graph screen) and the success criteria
   read;
4. how much the gap between two options moves across that range is the input's
   impact; whether the gap changes sign within it is whether the input can
   *flip* the comparison.

Plausible ranges come from what the model already uses:

* a link strength ±``LINK_SPREAD_SIGMAS`` × its Monte Carlo sigma (which is
  scaled by the link's own confidence, graph/stability.edge_sigma), clipped to
  [0, 1];
* a root claim's prior ±``PRIOR_SPREAD``, clipped to [0, 1]. The Monte Carlo
  does not vary priors, so a claim driver is a what-if on the inputs, reported
  as such.

Deterministic: no random draws, so the same graph gives the same ranking. No
model call. Nothing is invented: only existing links and claims are moved.
Interactions between inputs are ignored — the honest simplification of a
one-at-a-time method, stated wherever the result is shown.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping

import networkx as nx

from decision_studio.graph.stability import DEFAULT_SIGMA, compile_graph, propagate_once

LINK_SPREAD_SIGMAS = 2.0
PRIOR_SPREAD = 0.20
#: A gap within this of zero counts as no gap when deciding whether it flipped.
FLIP_EPSILON = 0.005
#: Inputs that move the gap less than this are not drivers.
MIN_IMPACT = 1e-6

FLIPS = "flips"          # the gap changes sign within the plausible range
ERASES = "erases"        # the gap closes to nothing but does not reverse
NO_FLIP = "no_flip"


@dataclass
class Driver:
    """One uncertain input and what the success criteria do across its range."""

    kind: str  # link or claim
    key: str   # "source->target" for a link, the claim id for a claim
    source: str | None
    target: str | None
    current: float
    low: float
    high: float
    #: option id -> outcome node -> (belief at low, belief at high)
    effects: dict[str, dict[str, tuple[float, float]]] = field(default_factory=dict)


def perturbation_drivers(
    option_graphs: Mapping[str, nx.DiGraph],
    outcome_nodes: list[str],
    *,
    fixed_nodes: set[str] | None = None,
    sigma: float = DEFAULT_SIGMA,
) -> tuple[dict[str, dict[str, float]], list[Driver]]:
    """Central beliefs per option, and every input moved across its range.

    Args:
        option_graphs: option id -> the graph with that option chosen.
        outcome_nodes: the success criteria.
        fixed_nodes: claims the options set (their levers); never perturbed.

    Returns:
        ``(base, drivers)``: base is option id -> outcome node -> belief.
    """
    fixed = set(fixed_nodes or ()) | set(outcome_nodes)
    compiled = {oid: compile_graph(g, sigma) for oid, g in option_graphs.items()}
    base = {
        oid: {n: beliefs.get(n, 0.0) for n in outcome_nodes}
        for oid, beliefs in ((oid, propagate_once(c)) for oid, c in compiled.items())
    }

    relevant: set[str] = set()
    for graph in option_graphs.values():
        for node in outcome_nodes:
            if node in graph:
                relevant |= nx.ancestors(graph, node) | {node}

    drivers: list[Driver] = []

    # Links: every edge into a node that can reach a success criterion.
    edge_keys = sorted({key for c in compiled.values() for key in c.edges if key[1] in relevant})
    for key in edge_keys:
        weight, _, edge_sigma, _ = next(c.edges[key] for c in compiled.values() if key in c.edges)
        spread = LINK_SPREAD_SIGMAS * edge_sigma
        low, high = max(0.0, weight - spread), min(1.0, weight + spread)
        if high - low <= 0:
            continue
        driver = Driver("link", f"{key[0]}->{key[1]}", key[0], key[1], weight, low, high)
        for oid, c in compiled.items():
            if key not in c.edges:
                driver.effects[oid] = {n: (base[oid][n], base[oid][n]) for n in outcome_nodes}
                continue
            at_low = propagate_once(c, {key: low - weight})
            at_high = propagate_once(c, {key: high - weight})
            driver.effects[oid] = {n: (at_low.get(n, 0.0), at_high.get(n, 0.0)) for n in outcome_nodes}
        drivers.append(driver)

    # Root claims no option sets: their prior is an input too.
    roots = sorted(
        node for node in relevant - fixed
        if all(node not in c.parents or not c.parents[node] for c in compiled.values())
        and any(node in c.priors for c in compiled.values())
    )
    for node in roots:
        current = next(c.priors[node] for c in compiled.values() if node in c.priors)
        low, high = max(0.0, current - PRIOR_SPREAD), min(1.0, current + PRIOR_SPREAD)
        driver = Driver("claim", node, None, None, current, low, high)
        for oid, c in compiled.items():
            if node not in c.priors:
                driver.effects[oid] = {n: (base[oid][n], base[oid][n]) for n in outcome_nodes}
                continue
            at_low = propagate_once(replace(c, priors={**c.priors, node: low}))
            at_high = propagate_once(replace(c, priors={**c.priors, node: high}))
            driver.effects[oid] = {n: (at_low.get(n, 0.0), at_high.get(n, 0.0)) for n in outcome_nodes}
        drivers.append(driver)

    return base, drivers


def _score(values: Mapping[str, float], weights: Mapping[str, float]) -> float:
    total = sum(weights.values())
    if total <= 0:
        return 0.0
    return sum(values.get(n, 0.0) * w for n, w in weights.items()) / total


def _sign(value: float) -> int:
    if value > FLIP_EPSILON:
        return 1
    if value < -FLIP_EPSILON:
        return -1
    return 0


def flip_status(base_gap: float, low_gap: float, high_gap: float) -> str:
    """Whether moving the input across its range reverses or closes the gap."""
    direction = _sign(base_gap)
    if direction == 0:
        return NO_FLIP
    signs = {_sign(low_gap), _sign(high_gap)}
    if -direction in signs:
        return FLIPS
    if 0 in signs:
        return ERASES
    return NO_FLIP


@dataclass
class DriverImpact:
    """One input's effect on the gap between options A and B."""

    driver: Driver
    #: Gap A - B on the weighted view: at the central value, low end, high end.
    base_gap: float
    low_gap: float
    high_gap: float
    impact: float
    flip: str
    #: outcome node -> flip status of the per-criterion gap.
    outcome_flips: dict[str, str]
    #: outcome node -> (gap at low, gap at high)
    outcome_gaps: dict[str, tuple[float, float]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "base_gap": round(self.base_gap, 4), "low_gap": round(self.low_gap, 4),
            "high_gap": round(self.high_gap, 4), "impact": round(self.impact, 4),
            "flip": self.flip,
        }


def rank_drivers(
    base: Mapping[str, Mapping[str, float]],
    drivers: list[Driver],
    a: str,
    b: str,
    weights: Mapping[str, float],
) -> list[DriverImpact]:
    """Inputs ordered by how much they move the A - B gap on the weighted view.

    Ties are broken by input key, so the order is deterministic. Inputs that do
    not move the gap at all are dropped.
    """
    base_gap = _score(base[a], weights) - _score(base[b], weights)
    ranked: list[DriverImpact] = []
    for driver in drivers:
        low_a = {n: v[0] for n, v in driver.effects[a].items()}
        high_a = {n: v[1] for n, v in driver.effects[a].items()}
        low_b = {n: v[0] for n, v in driver.effects[b].items()}
        high_b = {n: v[1] for n, v in driver.effects[b].items()}
        low_gap = _score(low_a, weights) - _score(low_b, weights)
        high_gap = _score(high_a, weights) - _score(high_b, weights)
        impact = abs(high_gap - low_gap)
        outcome_gaps = {
            n: (low_a[n] - low_b[n], high_a[n] - high_b[n]) for n in driver.effects[a]
        }
        outcome_impact = max((abs(h - l) for l, h in outcome_gaps.values()), default=0.0)
        if impact < MIN_IMPACT and outcome_impact < MIN_IMPACT:
            continue
        ranked.append(DriverImpact(
            driver=driver, base_gap=base_gap, low_gap=low_gap, high_gap=high_gap,
            impact=impact,
            flip=flip_status(base_gap, low_gap, high_gap),
            outcome_flips={
                n: flip_status(base[a][n] - base[b][n], lo, hi)
                for n, (lo, hi) in outcome_gaps.items()
            },
            outcome_gaps=outcome_gaps,
        ))
    ranked.sort(key=lambda d: (-round(d.impact, 9), d.driver.key))
    return ranked
