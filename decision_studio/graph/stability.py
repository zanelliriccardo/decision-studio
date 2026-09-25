"""Monte Carlo stability: do the conclusions survive noise on their inputs?

Every weight in a Decision Studio graph came from a language model producing plausible
decimals. They are estimates carrying error, so a comparison that turns on a
0.02 margin is reporting noise as a finding.

This module re-runs propagation many times with every edge weight perturbed, and
reports how often each answer wins rather than which answer wins once.

**What this replaces.** ``belief_propagation.compute_belief_intervals`` perturbs
one node's incoming edges, recomputes *that node only*, and reads its parents'
beliefs as fixed point values — despite a docstring claiming it re-propagates.
Uncertainty therefore never compounds along a chain, and a node five hops
downstream gets an interval computed as though everything upstream were known
exactly. On a simple two-hop chain the reported interval is half the width it
should be. It also moves every parent in the *same* direction, a perfectly
correlated worst case that essentially never occurs.

**Per-edge noise.** Sigma is scaled by ``link_confidence`` (see
``decision_studio.graph.edge_weight``): a link we are 90% sure exists is shaken gently,
one we are 20% sure of is shaken hard. This is where splitting ``strength`` into
effect and confidence starts paying for itself — before the split there was no
number to scale by.

**Common random numbers, applied selectively.** Edges that every option agrees
on share one jitter draw per run, so unrelated noise cancels instead of drowning
the comparison. Edges whose weight *differs* between options are the
intervention itself: each option's value there is its own uncertain estimate, so
those get independent draws. Sharing them would cancel exactly the uncertainty
under test, and a one-hundredth difference between two invented numbers would
come back looking perfectly decisive.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from decision_studio.graph.belief_propagation import _evidence_modulation, _root_prior

logger = logging.getLogger(__name__)

#: Default simulation count. Enough to separate a 52/48 split from a 70/30 one
#: without making the endpoint slow; this is pure arithmetic, no API calls.
DEFAULT_RUNS = 200

#: Baseline standard deviation of the perturbation applied to an edge weight.
#: Roughly "these numbers are good to about +/- 0.12", which is generous to a
#: language model's calibration.
DEFAULT_SIGMA = 0.12

#: Floor on the sigma multiplier. Even a link we are certain exists has an
#: uncertain effect *size*, so nothing is ever held perfectly still.
MIN_JITTER_FACTOR = 0.25

#: Fixed seed so a stability report is reproducible from its graph revision.
DEFAULT_SEED = 20260725

#: A belief difference smaller than this is not worth calling a divergence.
MATERIAL_DELTA = 0.05

#: Scores this close are a tie, not an ordering. Without this, `max()` would
#: hand every tie to whichever option happens to be first in the dict, and two
#: identical options would report a 100% win rate for one of them.
TIE_EPSILON = 1e-9


def edge_sigma(link_confidence: float, base_sigma: float = DEFAULT_SIGMA) -> float:
    """Perturbation scale for one edge, scaled by how sure we are it is real.

    Monotone in confidence: confidence 1.0 gives ``MIN_JITTER_FACTOR * base``,
    confidence 0.0 gives the full ``base``.
    """
    confidence = max(0.0, min(1.0, float(link_confidence)))
    factor = MIN_JITTER_FACTOR + (1.0 - MIN_JITTER_FACTOR) * (1.0 - confidence)
    return base_sigma * factor


@dataclass
class _CompiledGraph:
    """Propagation-ready view of a graph, built once and reused per run.

    Re-running ``propagate_beliefs`` 200 times would mean 200 topological sorts
    and 200 rounds of dict lookups on NetworkX attribute maps. Compiling once
    also means the caller's graph is never mutated, which the existing
    interval code does do.
    """

    order: list[str]
    parents: dict[str, list[str]]
    priors: dict[str, float]
    gates: dict[str, str]
    #: (parent, child) -> (base_weight, evidence_modulation, sigma, is_inhibiting)
    edges: dict[tuple[str, str], tuple[float, float, float, bool]]


def compile_graph(graph: nx.DiGraph, base_sigma: float = DEFAULT_SIGMA) -> _CompiledGraph:
    """Flatten a graph into the minimum needed to propagate it repeatedly."""
    try:
        order = list(nx.topological_sort(graph))
    except nx.NetworkXUnfeasible:
        # Cycles are broken upstream; if one survives, fall back to insertion
        # order rather than failing the whole analysis.
        logger.warning("Stability: graph is not a DAG, using insertion order")
        order = list(graph.nodes)

    parents = {n: list(graph.predecessors(n)) for n in order}
    priors = {n: _root_prior(graph, n) for n in order}
    gates = {n: graph.nodes[n].get("logic_gate", "or") or "or" for n in order}

    edges: dict[tuple[str, str], tuple[float, float, float, bool]] = {}
    for source, target, data in graph.edges(data=True):
        weight = data.get("strength", 0.5)
        modulation = _evidence_modulation(data.get("evidence_score", 0.5))
        confidence = data.get("link_confidence")
        if confidence is None:
            # Pre-split edge: no confidence to scale by, so use full sigma.
            confidence = 0.0
        edges[(source, target)] = (
            weight,
            modulation,
            edge_sigma(confidence, base_sigma),
            data.get("causal_type") == "inhibiting",
        )

    return _CompiledGraph(order, parents, priors, gates, edges)


def draw_jitter(
    compiled: _CompiledGraph, rng: random.Random
) -> dict[tuple[str, str], float]:
    """One perturbation draw: an additive delta per edge."""
    return {key: rng.gauss(0.0, params[2]) for key, params in compiled.edges.items()}


def propagate_once(
    compiled: _CompiledGraph, jitter: dict[tuple[str, str], float] | None = None
) -> dict[str, float]:
    """Propagate beliefs with an optional per-edge perturbation.

    Mirrors ``_noisy_or_belief_full`` and ``_and_gate_belief`` exactly, including
    inhibiting edges and AND gates, so stability output is comparable with the
    point estimate rather than a different model.
    """
    beliefs: dict[str, float] = {}

    for node in compiled.order:
        predecessors = compiled.parents.get(node, [])
        if not predecessors:
            beliefs[node] = compiled.priors[node]
            continue

        if compiled.gates.get(node) == "and":
            belief = 1.0
            for parent in predecessors:
                weight, modulation, _, _ = compiled.edges[(parent, node)]
                if jitter:
                    weight = max(0.0, min(1.0, weight + jitter.get((parent, node), 0.0)))
                belief *= beliefs.get(parent, 0.5) * weight * modulation
            beliefs[node] = max(0.0, min(1.0, belief))
            continue

        noisy_or_product = 1.0
        inhibition_factor = 1.0
        for parent in predecessors:
            weight, modulation, _, inhibiting = compiled.edges[(parent, node)]
            if jitter:
                weight = max(0.0, min(1.0, weight + jitter.get((parent, node), 0.0)))
            contribution = beliefs.get(parent, 0.5) * weight * modulation
            if inhibiting:
                inhibition_factor *= 1.0 - contribution
            else:
                noisy_or_product *= 1.0 - contribution
        beliefs[node] = max(0.0, min(1.0, (1.0 - noisy_or_product) * inhibition_factor))

    return beliefs


@dataclass
class NodeStability:
    """Distribution of one node's belief across the simulation."""

    point: float
    p10: float
    p50: float
    p90: float
    mean: float

    @property
    def width(self) -> float:
        """Distance between the tenth and ninetieth percentile."""
        return self.p90 - self.p10

    def as_dict(self) -> dict[str, float]:
        """This result, for the API."""
        return {
            "point": round(self.point, 4),
            "p10": round(self.p10, 4),
            "p50": round(self.p50, 4),
            "p90": round(self.p90, 4),
            "mean": round(self.mean, 4),
            "width": round(self.width, 4),
        }


def _percentile(sorted_values: list[float], fraction: float) -> float:
    """Linear-interpolated percentile of a sorted sample."""
    if not sorted_values:
        return 0.0
    index = int(fraction * (len(sorted_values) - 1))
    return sorted_values[max(0, min(len(sorted_values) - 1, index))]


def node_stability(
    graph: nx.DiGraph,
    *,
    runs: int = DEFAULT_RUNS,
    sigma: float = DEFAULT_SIGMA,
    seed: int = DEFAULT_SEED,
) -> dict[str, NodeStability]:
    """Belief distribution per node under perturbed edge weights.

    Unlike the interval function it replaces, uncertainty compounds: a jittered
    parent belief feeds its child, so deep nodes correctly show wider bands.
    """
    compiled = compile_graph(graph, sigma)
    point = propagate_once(compiled)

    if runs <= 0 or not compiled.edges:
        return {
            node: NodeStability(value, value, value, value, value)
            for node, value in point.items()
        }

    rng = random.Random(seed)
    samples: dict[str, list[float]] = {node: [] for node in compiled.order}
    for _ in range(runs):
        beliefs = propagate_once(compiled, draw_jitter(compiled, rng))
        for node, value in beliefs.items():
            samples[node].append(value)

    result: dict[str, NodeStability] = {}
    for node, values in samples.items():
        values.sort()
        result[node] = NodeStability(
            point=point.get(node, 0.5),
            p10=_percentile(values, 0.10),
            p50=_percentile(values, 0.50),
            p90=_percentile(values, 0.90),
            mean=sum(values) / len(values),
        )
    return result


def belief_intervals(
    graph: nx.DiGraph,
    *,
    runs: int = DEFAULT_RUNS,
    sigma: float = DEFAULT_SIGMA,
    seed: int = DEFAULT_SEED,
) -> dict[str, tuple[float, float]]:
    """Drop-in replacement for ``compute_belief_intervals``.

    Same shape — ``{node_id: (low, high)}`` — so existing callers need no change,
    but the bounds are p10/p90 of a joint simulation rather than a correlated
    worst case that never compounds.
    """
    return {
        node: (stats.p10, stats.p90)
        for node, stats in node_stability(graph, runs=runs, sigma=sigma, seed=seed).items()
    }


@dataclass
class ComparisonStability:
    """How reliably two graphs differ at a given node."""

    node_id: str
    belief_a: float
    belief_b: float
    delta: float
    #: Share of runs in which the sign of the difference matched the point estimate.
    agreement: float
    #: Share of runs in which the difference exceeded MATERIAL_DELTA.
    material_rate: float

    @property
    def robust(self) -> bool:
        """True when the divergence is not an artefact of the input noise."""
        return self.agreement >= 0.90 and self.material_rate >= 0.50

    def as_dict(self) -> dict[str, Any]:
        """This result, for the API."""
        return {
            "node_id": self.node_id,
            "belief_a": round(self.belief_a, 4),
            "belief_b": round(self.belief_b, 4),
            "delta": round(self.delta, 4),
            "agreement": round(self.agreement, 3),
            "material_rate": round(self.material_rate, 3),
            "robust": self.robust,
        }


def compare_stability(
    graph_a: nx.DiGraph,
    graph_b: nx.DiGraph,
    *,
    runs: int = DEFAULT_RUNS,
    sigma: float = DEFAULT_SIGMA,
    seed: int = DEFAULT_SEED,
) -> dict[str, ComparisonStability]:
    """Compare two graphs under shared noise.

    Edges present in both graphs receive the *same* perturbation within a run
    (common random numbers), so the measured difference is attributable to the
    graphs rather than to two independent noise draws.
    """
    compiled_a = compile_graph(graph_a, sigma)
    compiled_b = compile_graph(graph_b, sigma)

    point_a = propagate_once(compiled_a)
    point_b = propagate_once(compiled_b)
    shared_nodes = set(point_a) & set(point_b)

    rng = random.Random(seed)
    all_edges = set(compiled_a.edges) | set(compiled_b.edges)
    # Sigma per edge: whichever graph knows about it. Sorted for determinism.
    sigmas = {
        key: (compiled_a.edges.get(key) or compiled_b.edges[key])[2]
        for key in sorted(all_edges)
    }

    agreements = {node: 0 for node in shared_nodes}
    materials = {node: 0 for node in shared_nodes}

    for _ in range(runs):
        jitter = {key: rng.gauss(0.0, s) for key, s in sigmas.items()}
        beliefs_a = propagate_once(compiled_a, jitter)
        beliefs_b = propagate_once(compiled_b, jitter)
        for node in shared_nodes:
            run_delta = beliefs_a[node] - beliefs_b[node]
            point_delta = point_a[node] - point_b[node]
            if run_delta * point_delta > 0 or (run_delta == 0 and point_delta == 0):
                agreements[node] += 1
            if abs(run_delta) >= MATERIAL_DELTA:
                materials[node] += 1

    divisor = max(runs, 1)
    return {
        node: ComparisonStability(
            node_id=node,
            belief_a=point_a[node],
            belief_b=point_b[node],
            delta=point_a[node] - point_b[node],
            agreement=agreements[node] / divisor,
            material_rate=materials[node] / divisor,
        )
        for node in shared_nodes
    }


@dataclass
class RankStability:
    """How often each option ranked first once the inputs were shaken."""

    option_id: str
    score: float
    p_first: float
    p10: float
    p50: float
    p90: float
    samples: list[float] = field(default_factory=list, repr=False)

    def as_dict(self) -> dict[str, Any]:
        """This result, for the API."""
        return {
            "option_id": self.option_id,
            "score": round(self.score, 4),
            "p_first": round(self.p_first, 3),
            "p10": round(self.p10, 4),
            "p50": round(self.p50, 4),
            "p90": round(self.p90, 4),
        }


def rank_stability(
    options: dict[str, nx.DiGraph],
    outcome_nodes: list[str],
    *,
    baseline: nx.DiGraph | None = None,
    runs: int = DEFAULT_RUNS,
    sigma: float = DEFAULT_SIGMA,
    seed: int = DEFAULT_SEED,
) -> tuple[dict[str, RankStability], bool]:
    """Rank options by their effect on outcome nodes, and say how solid it is.

    Args:
        options: option id -> its graph.
        outcome_nodes: nodes whose beliefs constitute the score. A lower belief
            on a problem outcome is better, so the score is negated.
        baseline: graph to measure movement against. Absolute beliefs are used
            when omitted.
        runs: simulations.

    Returns:
        ``(per_option_stability, decisive)``. ``decisive`` is False when the
        leader wins fewer than 60% of runs — at which point the ranking should
        not be reported as a finding.
    """
    if not options:
        return {}, False

    compiled = {oid: compile_graph(g, sigma) for oid, g in options.items()}
    compiled_baseline = compile_graph(baseline, sigma) if baseline is not None else None

    def score(beliefs: dict[str, float], base: dict[str, float] | None) -> float:
        """Total belief across the outcome nodes, for one simulated run."""
        total = 0.0
        for node in outcome_nodes:
            value = beliefs.get(node, 0.0)
            if base is not None:
                value -= base.get(node, 0.0)
            total += -value  # lowering a problem outcome is an improvement
        return total

    point_scores = {
        oid: score(
            propagate_once(c),
            propagate_once(compiled_baseline) if compiled_baseline else None,
        )
        for oid, c in compiled.items()
    }

    rng = random.Random(seed)
    all_compiled = list(compiled.values()) + (
        [compiled_baseline] if compiled_baseline else []
    )
    all_edges = sorted({key for c in all_compiled for key in c.edges})

    sigmas: dict[tuple[str, str], float] = {}
    for key in all_edges:
        for c in all_compiled:
            if key in c.edges:
                sigmas[key] = c.edges[key][2]
                break

    # Common random numbers cancel noise that is genuinely *common* -- but an
    # edge whose weight differs between options is the intervention itself, and
    # each option's value for it is a separate uncertain estimate. Sharing one
    # draw across those would cancel the very uncertainty we are testing, and a
    # 0.01 difference in a made-up number would look perfectly decisive.
    # So: shared draw for edges every option agrees on, independent draws for
    # the edges that distinguish them.
    shared_edges: set[tuple[str, str]] = set()
    for key in all_edges:
        weights = {
            round(c.edges[key][0], 9) for c in all_compiled if key in c.edges
        }
        present_everywhere = all(key in c.edges for c in all_compiled)
        if present_everywhere and len(weights) == 1:
            shared_edges.add(key)

    samples: dict[str, list[float]] = {oid: [] for oid in options}
    firsts: dict[str, float] = {oid: 0.0 for oid in options}

    for _ in range(runs):
        shared_jitter = {
            key: rng.gauss(0.0, sigmas[key]) for key in all_edges if key in shared_edges
        }

        def jitter_for(c: _CompiledGraph) -> dict[tuple[str, str], float]:
            """Noise for one scenario: shared where the scenarios share an edge.

            Selective common random numbers. Fully shared noise understates the
            difference between scenarios; fully independent noise swamps it.
            """
            draw = dict(shared_jitter)
            for key in c.edges:
                if key not in shared_edges:
                    draw[key] = rng.gauss(0.0, sigmas[key])
            return draw

        base_beliefs = (
            propagate_once(compiled_baseline, jitter_for(compiled_baseline))
            if compiled_baseline
            else None
        )
        run_scores = {
            oid: score(propagate_once(c, jitter_for(c)), base_beliefs)
            for oid, c in compiled.items()
        }
        for oid, value in run_scores.items():
            samples[oid].append(value)

        best = max(run_scores.values())
        winners = [oid for oid, v in run_scores.items() if v >= best - TIE_EPSILON]
        for oid in winners:
            firsts[oid] += 1.0 / len(winners)

    result: dict[str, RankStability] = {}
    for oid in options:
        values = sorted(samples[oid])
        result[oid] = RankStability(
            option_id=oid,
            score=point_scores[oid],
            p_first=firsts[oid] / max(runs, 1),
            p10=_percentile(values, 0.10),
            p50=_percentile(values, 0.50),
            p90=_percentile(values, 0.90),
            samples=values,
        )

    leader = max(result.values(), key=lambda r: r.p_first)
    decisive = len(options) == 1 or leader.p_first >= 0.60
    return result, decisive
