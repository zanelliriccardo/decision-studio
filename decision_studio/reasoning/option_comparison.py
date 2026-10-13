"""What the causal map predicts for each option.

Theories argue for and against options in prose; this asks the graph itself.
For each option on the anchor, the graph is set to "this option is chosen" and
propagated, and the success criteria are read off. Repeated with every link
weight shaken within its uncertainty (graph/stability.py), it says how often
each option comes out ahead: the win rate.

## How an option enters a graph that has no option nodes

Options are deliberately not nodes (reasoning/decision_anchor.py): a choice has
no probability. What the graph does have are **levers** — claims the relevance
scorer tagged ``decision_role="lever"`` with ``bears_on`` naming the options
they are a property of ("committing to Q3 compresses testing to two weeks").

Choosing an option is an intervention in Pearl's sense, ``do(O1)``:

* levers that belong to O1 and not to every option become true (prior 1),
* levers that belong only to other options become false (prior 0),
* either way their incoming links are cut: choosing O1 makes its levers true by
  fiat, whatever normally causes them,
* levers shared by every option, or tied to none, are left alone.

Everything else — contingencies, mechanisms — propagates as it does on the
graph screen, from the same reviewed graph.

## What this is not

A forecast. It is what the causal map, as reviewed, implies: the links were
inferred by a model and their strengths are estimates. The win rate says how
robust the ranking is to those estimates being off, not how likely the world is
to go this way. The screen and the report say so.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import networkx as nx
from sqlalchemy.ext.asyncio import AsyncSession

from decision_studio.graph.option_sensitivity import (
    FLIPS,
    DriverImpact,
    perturbation_drivers,
    rank_drivers,
)
from decision_studio.graph.stability import DEFAULT_RUNS, WEIGHTED, compare_options
from decision_studio.graph.value_of_information import link_uncertainty
from decision_studio.reasoning import decision_priorities, decision_robustness
from decision_studio.reasoning.decision_anchor import ORIGIN_FRAME, ROLE_OUTCOME, project_anchor
from decision_studio.reasoning.effective_graph import load_effective_snapshot

logger = logging.getLogger(__name__)

ROLE_LEVER = "lever"

#: Drivers shown per comparison. The full ranking feeds information priority.
MAX_DRIVERS = 5
#: Inputs that move the gap by less than half a point, and flip nothing, are
#: not shown as drivers or information needs: at that size they are noise.
MIN_REPORTED_IMPACT = 0.005


def is_reportable(impact: DriverImpact) -> bool:
    return impact.impact >= MIN_REPORTED_IMPACT or impact.flip == FLIPS or any(
        status == FLIPS for status in impact.outcome_flips.values())


@dataclass
class OptionRow:
    key: str
    label: str
    #: Levers switched on / off by choosing this option: (claim id, text).
    levers_on: list[tuple[str, str]] = field(default_factory=list)
    levers_off: list[tuple[str, str]] = field(default_factory=list)
    #: Whether any switched lever has a causal path to a success criterion.
    reaches_outcome: bool = False
    #: Per outcome key: {point, p10, p50, p90, p_best}.
    outcomes: dict[str, dict[str, float]] = field(default_factory=dict)
    score: float | None = None
    p_best: float | None = None
    #: The weighted view under the decider's priorities (decision_priorities.py).
    weighted: decision_priorities.WeightedView | None = None

    @property
    def status(self) -> str:
        if not self.levers_on and not self.levers_off:
            return "not_modelled"
        if not self.reaches_outcome:
            return "no_path"
        if not self.levers_on:
            return "only_as_alternative"
        return "modelled"


@dataclass
class OptionComparison:
    options: list[OptionRow]
    #: (key, label) of each success criterion, in anchor order.
    outcomes: list[tuple[str, str]]
    decisive: bool = False
    leader: str | None = None
    runs: int = 0
    #: Why the comparison could not be made, when it could not.
    unavailable: str | None = None
    #: Every success criterion with the importance the decider gave it.
    priorities: list[decision_priorities.Priority] = field(default_factory=list)
    #: Pairwise robustness, one entry per pair of options.
    robustness: list[dict[str, Any]] = field(default_factory=list)
    #: The two options with the highest weighted view: what the drivers explain.
    headline_pair: tuple[str, str] | None = None
    #: Inputs ranked by effect on the headline pair (all of them; MAX_DRIVERS shown).
    driver_impacts: list[DriverImpact] = field(default_factory=list)
    drivers: list[dict[str, Any]] = field(default_factory=list)
    #: Filled by reasoning/information_priority.py.
    information_priority: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcomes": [{"key": k, "label": label} for k, label in self.outcomes],
            "options": [
                {
                    "key": o.key, "label": o.label, "status": o.status,
                    "levers_on": [{"claim_id": c, "text": t} for c, t in o.levers_on],
                    "levers_off": [{"claim_id": c, "text": t} for c, t in o.levers_off],
                    "reaches_outcome": o.reaches_outcome,
                    "outcomes": o.outcomes, "score": o.score, "p_best": o.p_best,
                    "weighted": o.weighted.as_dict() if o.weighted else None,
                }
                for o in self.options
            ],
            "decisive": self.decisive,
            "leader": self.leader,
            "runs": self.runs,
            "unavailable": self.unavailable,
            "priorities": [p.as_dict() for p in self.priorities],
            "robustness": self.robustness,
            "headline_pair": list(self.headline_pair) if self.headline_pair else None,
            "drivers": self.drivers,
            "information_priority": self.information_priority,
        }


def intervene(
    graph: nx.DiGraph, on: list[str], off: list[str]
) -> nx.DiGraph:
    """``do()``: fix the given nodes true or false and cut what feeds them."""
    chosen = graph.copy()
    for node, value in [(n, 1.0) for n in on] + [(n, 0.0) for n in off]:
        if node not in chosen:
            continue
        chosen.remove_edges_from(list(chosen.in_edges(node)))
        chosen.nodes[node]["prior"] = value
    return chosen


def option_levers(
    claims: list[Any], option_keys: list[str]
) -> dict[str, tuple[list[Any], list[Any]]]:
    """For each option, the lever claims it switches on and off."""
    all_keys = set(option_keys)
    levers = [
        c for c in claims
        if getattr(c, "decision_role", None) == ROLE_LEVER
        and getattr(c, "origin", None) != ORIGIN_FRAME
    ]
    result: dict[str, tuple[list[Any], list[Any]]] = {}
    for key in option_keys:
        on, off = [], []
        for claim in levers:
            bears = set(getattr(claim, "bears_on", None) or []) & all_keys
            if not bears or bears == all_keys:
                continue  # true whatever is chosen, or tied to no option
            (on if key in bears else off).append(claim)
        result[key] = (on, off)
    return result


def build_comparison(
    graph: nx.DiGraph,
    claims: list[Any],
    anchor: dict[str, Any] | None,
    *,
    runs: int = DEFAULT_RUNS,
    priorities: dict[str, str] | None = None,
    explain: bool = True,
) -> OptionComparison:
    """The comparison, from a propagation-ready graph and the reviewed claims.

    Args:
        priorities: outcome key -> importance, as the decider set them. Missing
            criteria take the default (decision_priorities.DEFAULT_IMPORTANCE).
        explain: rank the drivers too. Off for callers that only need the
            outcomes under a variant of the graph (scenarios, sub-decisions).
    """
    options = list((anchor or {}).get("options", []))
    outcome_labels = {o["key"]: o["label"] for o in (anchor or {}).get("outcomes", [])}

    outcome_nodes: dict[str, str] = {}
    for claim in claims:
        if getattr(claim, "decision_role", None) != ROLE_OUTCOME:
            continue
        if getattr(claim, "origin", None) != ORIGIN_FRAME:
            continue
        metadata = getattr(claim, "metadata_", None) or {}
        keys = [metadata.get("anchor_key")] + list(getattr(claim, "bears_on", None) or [])
        for key in keys:
            if key in outcome_labels and str(claim.id) in graph:
                outcome_nodes.setdefault(key, str(claim.id))
    outcomes = [(k, outcome_labels[k]) for k in outcome_labels if k in outcome_nodes]

    comparison = OptionComparison(
        options=[OptionRow(key=o["key"], label=o["label"]) for o in options],
        outcomes=outcomes,
        priorities=decision_priorities.resolve(outcomes, priorities),
    )
    if len(options) < 2:
        comparison.unavailable = "Fewer than two options are on the table."
        return comparison
    if not outcomes:
        comparison.unavailable = "No success criterion is in the graph."
        return comparison

    by_key = {row.key: row for row in comparison.options}
    levers = option_levers(claims, [o["key"] for o in options])
    targets = set(outcome_nodes.values())
    graphs: dict[str, nx.DiGraph] = {}
    for key, (on, off) in levers.items():
        row = by_key[key]
        row.levers_on = [(str(c.id), c.text) for c in on if str(c.id) in graph]
        row.levers_off = [(str(c.id), c.text) for c in off if str(c.id) in graph]
        switched = [cid for cid, _ in row.levers_on + row.levers_off]
        row.reaches_outcome = any(
            targets & nx.descendants(graph, cid) for cid in switched
        )
        graphs[key] = intervene(
            graph, [c for c, _ in row.levers_on], [c for c, _ in row.levers_off]
        )

    if not any(row.levers_on or row.levers_off for row in comparison.options):
        comparison.unavailable = (
            "No claim in the graph describes what any option involves, so the map "
            "cannot tell the options apart."
        )
        return comparison

    weights_by_key = decision_priorities.normalized_weights(comparison.priorities)
    weights_by_node = {outcome_nodes[k]: w for k, w in weights_by_key.items()}
    forecasts, decisive = compare_options(
        graphs, list(outcome_nodes.values()), runs=runs, weights=weights_by_node or None,
    )
    node_to_key = {node: key for key, node in outcome_nodes.items()}
    for key, forecast in forecasts.items():
        row = by_key[key]
        row.score = round(forecast.score, 4)
        row.p_best = round(forecast.p_best, 3)
        for node, stats in forecast.outcomes.items():
            row.outcomes[node_to_key[node]] = {
                "point": round(stats.point, 4),
                "p10": round(stats.p10, 4),
                "p50": round(stats.p50, 4),
                "p90": round(stats.p90, 4),
                "p_best": round(forecast.p_best_by_outcome.get(node, 0.0), 3),
            }
        row.weighted = decision_priorities.weighted_view(
            {k: v["point"] for k, v in row.outcomes.items()}, weights_by_key
        )
    comparison.runs = runs
    if weights_by_key:
        comparison.decisive = decisive
        leader = max(comparison.options, key=lambda r: (r.p_best or 0.0, r.key))
        comparison.leader = leader.key if decisive else None
    # With every criterion set to "none" there is no weighted view, and the
    # equal-weight ranking compare_options falls back to would be a hidden score.

    comparison.robustness = _robustness(comparison, forecasts, outcome_nodes)
    # Drivers explain the gap on the weighted view. With every criterion set to
    # "not a factor" there is no weighted view, and ranking drivers on an
    # equal-weight gap instead would be a hidden weighting presented as the
    # decider's: leave them (and what builds on them) empty.
    if explain and weights_by_key:
        _explain_drivers(comparison, graph, graphs, outcome_nodes, weights_by_key, claims)
    return comparison


def outcome_node_map(claims: list[Any], anchor: dict[str, Any] | None, graph: nx.DiGraph) -> dict[str, str]:
    """Outcome key (Y1..) -> the graph node that stands for it."""
    labels = {o["key"] for o in (anchor or {}).get("outcomes", [])}
    nodes: dict[str, str] = {}
    for claim in claims:
        if getattr(claim, "decision_role", None) != ROLE_OUTCOME or getattr(claim, "origin", None) != ORIGIN_FRAME:
            continue
        metadata = getattr(claim, "metadata_", None) or {}
        for key in [metadata.get("anchor_key")] + list(getattr(claim, "bears_on", None) or []):
            if key in labels and str(claim.id) in graph:
                nodes.setdefault(key, str(claim.id))
    return nodes


def _robustness(comparison: OptionComparison, forecasts: dict, outcome_nodes: dict[str, str]) -> list[dict[str, Any]]:
    """Every pair of options, per criterion and on the weighted view."""
    labels = {row.key: row.label for row in comparison.options}
    by_key = {row.key: row for row in comparison.options}
    keys = [row.key for row in comparison.options]
    pairs: list[dict[str, Any]] = []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            shares = forecasts[a].higher_than.get(b, {})
            rows = []
            verdicts = []
            for key, label in comparison.outcomes:
                value_a = by_key[a].outcomes[key]["point"]
                value_b = by_key[b].outcomes[key]["point"]
                verdict = decision_robustness.classify(
                    a, b, value_a, value_b, shares.get(outcome_nodes[key], 0.5))
                verdicts.append(verdict)
                rows.append({
                    "key": key, "label": label, "value_a": value_a, "value_b": value_b,
                    **verdict.as_dict(),
                    "sentence": decision_robustness.describe(verdict, f"{key} {label}", labels),
                })
            weighted = None
            if by_key[a].weighted and by_key[b].weighted:
                verdict = decision_robustness.classify(
                    a, b, by_key[a].weighted.score, by_key[b].weighted.score,
                    shares.get(WEIGHTED, 0.5))
                weighted = {
                    "value_a": round(by_key[a].weighted.score, 4),
                    "value_b": round(by_key[b].weighted.score, 4),
                    **verdict.as_dict(),
                    "sentence": decision_robustness.describe(
                        verdict, "the weighted view", labels),
                }
            pairs.append({
                "a": a, "b": b, "outcomes": rows, "weighted": weighted,
                "summary": decision_robustness.summarise_pair(a, b, verdicts),
            })
    return pairs


def _pct(value: float) -> str:
    return f"{round(value * 100)}%"


def _gap_phrase(gap: float, a: str, b: str, labels: dict[str, str]) -> str:
    if abs(gap) < 0.005:
        return "the two are level"
    leader = a if gap > 0 else b
    points = round(abs(gap) * 100)
    return f"{labels[leader]} higher by {points} point{'' if points == 1 else 's'}"


def _explain_drivers(
    comparison: OptionComparison,
    graph: nx.DiGraph,
    graphs: dict[str, nx.DiGraph],
    outcome_nodes: dict[str, str],
    weights_by_key: dict[str, float],
    claims: list[Any],
) -> None:
    """Rank the inputs behind the gap between the two leading options."""
    ranked_rows = sorted(
        comparison.options,
        key=lambda r: (-(r.weighted.score if r.weighted else (r.score or 0.0)), r.key),
    )
    a, b = ranked_rows[0].key, ranked_rows[1].key
    comparison.headline_pair = (a, b)
    fixed = {cid for row in comparison.options for cid, _ in row.levers_on + row.levers_off}
    base, drivers = perturbation_drivers(graphs, list(outcome_nodes.values()), fixed_nodes=fixed)
    weights_by_node = {outcome_nodes[k]: w for k, w in weights_by_key.items()}
    comparison.driver_impacts = rank_drivers(base, drivers, a, b, weights_by_node)

    text = {str(c.id): c.text for c in claims}
    labels = {row.key: row.label for row in comparison.options}
    node_to_key = {node: key for key, node in outcome_nodes.items()}
    comparison.drivers = [
        describe_driver(impact, graph, text, labels, a, b, node_to_key)
        for impact in [i for i in comparison.driver_impacts if is_reportable(i)][:MAX_DRIVERS]
    ]


def driver_uncertainty(impact: DriverImpact, graph: nx.DiGraph) -> float:
    """How little is known about the input, 0-1 (value_of_information.link_uncertainty)."""
    driver = impact.driver
    if driver.kind == "link" and graph.has_edge(driver.source, driver.target):
        data = graph.edges[driver.source, driver.target]
        return link_uncertainty(data.get("link_confidence"), data.get("evidence_score"))
    # A claim's prior: most uncertain at 50%, least at 0% or 100%.
    return round(4 * driver.current * (1 - driver.current), 4)


def describe_driver(
    impact: DriverImpact,
    graph: nx.DiGraph,
    text: dict[str, str],
    labels: dict[str, str],
    a: str,
    b: str,
    node_to_key: dict[str, str],
) -> dict[str, Any]:
    """One driver for the API and the report, with a sentence that explains it."""
    driver = impact.driver
    if driver.kind == "link":
        label = f"{text.get(driver.source, '?')} → {text.get(driver.target, '?')}"
        what = "Link strength"
        edge_id = graph.edges[driver.source, driver.target].get("edge_id") if graph.has_edge(
            driver.source, driver.target) else None
    else:
        label = text.get(driver.key, "?")
        what = "Likelihood this holds"
        edge_id = None
    # A link's range comes from its own simulated uncertainty; a root claim's is a
    # fixed what-if (the simulations do not vary priors), and is named as such.
    range_name = "plausible range" if driver.kind == "link" else "what-if range (±20 points)"
    flips = [node_to_key.get(n, n) for n, status in impact.outcome_flips.items() if status == FLIPS]
    explanation = (
        f"{what}: {_pct(driver.current)} now, {range_name} {_pct(driver.low)}–{_pct(driver.high)}. "
        f"At the low end, {_gap_phrase(impact.low_gap, a, b, labels)} on the weighted view; "
        f"at the high end, {_gap_phrase(impact.high_gap, a, b, labels)}."
    )
    if impact.flip == FLIPS:
        explanation += " Within its plausible range this input can reverse the comparison."
    elif impact.flip == "erases":
        explanation += " Within its plausible range this input can close the gap."
    return {
        "kind": driver.kind,
        "key": driver.key,
        "edge_id": edge_id,
        "claim_id": driver.key if driver.kind == "claim" else None,
        "label": label,
        "current": round(driver.current, 4),
        "low": round(driver.low, 4),
        "high": round(driver.high, 4),
        "uncertainty": driver_uncertainty(impact, graph),
        **impact.as_dict(),
        "flips_outcomes": flips,
        "explanation": explanation,
    }


async def compare_project_options(
    session: AsyncSession, project_id: UUID, *, runs: int = DEFAULT_RUNS
) -> OptionComparison:
    """What the reviewed graph predicts for each option of the project's decision."""
    from decision_studio.reasoning.link_tests import snapshot_graph

    from decision_studio.reasoning.information_priority import attach_information_priority

    anchor = await project_anchor(session, project_id)
    snapshot = await load_effective_snapshot(project_id, session)
    graph = snapshot_graph(snapshot)
    comparison = build_comparison(
        graph, snapshot.claims, anchor, runs=runs,
        priorities=decision_priorities.clean_priorities(
            getattr(snapshot.project, "outcome_priorities", None)),
    )
    await attach_information_priority(session, project_id, comparison, graph, snapshot.claims)
    logger.info(
        "Option comparison for %s: %d option(s), decisive=%s, %s",
        project_id, len(comparison.options), comparison.decisive,
        comparison.unavailable or "computed",
    )
    return comparison
