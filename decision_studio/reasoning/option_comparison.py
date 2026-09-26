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

from decision_studio.graph.stability import DEFAULT_RUNS, compare_options
from decision_studio.reasoning.decision_anchor import ORIGIN_FRAME, ROLE_OUTCOME, project_anchor
from decision_studio.reasoning.effective_graph import load_effective_snapshot

logger = logging.getLogger(__name__)

ROLE_LEVER = "lever"


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
                }
                for o in self.options
            ],
            "decisive": self.decisive,
            "leader": self.leader,
            "runs": self.runs,
            "unavailable": self.unavailable,
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
) -> OptionComparison:
    """The comparison, from a propagation-ready graph and the reviewed claims."""
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

    forecasts, decisive = compare_options(graphs, list(outcome_nodes.values()), runs=runs)
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
    comparison.runs = runs
    comparison.decisive = decisive
    leader = max(comparison.options, key=lambda r: r.p_best or 0.0)
    comparison.leader = leader.key if decisive else None
    return comparison


async def compare_project_options(
    session: AsyncSession, project_id: UUID, *, runs: int = DEFAULT_RUNS
) -> OptionComparison:
    """What the reviewed graph predicts for each option of the project's decision."""
    from decision_studio.reasoning.link_tests import snapshot_graph

    anchor = await project_anchor(session, project_id)
    snapshot = await load_effective_snapshot(project_id, session)
    comparison = build_comparison(snapshot_graph(snapshot), snapshot.claims, anchor, runs=runs)
    logger.info(
        "Option comparison for %s: %d option(s), decisive=%s, %s",
        project_id, len(comparison.options), comparison.decisive,
        comparison.unavailable or "computed",
    )
    return comparison
