"""Base case, upside and downside: the option comparison under explicit assumptions.

A scenario changes existing inputs of the one reviewed graph — link strengths
and root-claim priors — and reruns the existing option comparison on it. No
second graph is stored or built: each case is the snapshot graph with a handful
of values replaced, discarded after the run.

* **Base case**: the reviewed graph as it stands.
* **Upside / downside**, automatic: the ``AUTO_INPUTS`` (5) uncertain inputs that
  move the *level* of the weighted view most (averaged over the options),
  from the same one-at-a-time sensitivity run as the drivers
  (graph/option_sensitivity.py), each set to the end of its plausible range
  that raises (upside) or lowers (downside) that level. So "downside" means the
  world is less kind to every option, not that one option is punished.
* **Upside / downside**, the decider's: once they edit a case, its assumptions
  are stored as a row of the existing ``scenario`` table (``decision_case``,
  ``edge_overrides`` by edge id, ``claim_overrides`` by claim id) and used
  verbatim until reset.

These are scenario assumptions, not forecasts: every screen and report section
that shows them says which inputs were changed and to what.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import networkx as nx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_studio.db.models import Scenario
from decision_studio.graph.stability import DEFAULT_RUNS
from decision_studio.reasoning import decision_priorities
from decision_studio.reasoning.option_comparison import (
    OptionComparison,
    build_comparison,
    outcome_node_map,
)

CASES = ("base", "upside", "downside")
CASE_LABELS = {"base": "Base case", "upside": "Upside", "downside": "Downside"}
AUTO_INPUTS = 5
#: Scenario runs are summaries; fewer simulations than the headline comparison.
SCENARIO_RUNS = 100


@dataclass
class Assumption:
    kind: str  # link or claim
    #: The edge id for a link, the claim id for a claim.
    id: str
    label: str
    base: float
    value: float

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "id": self.id, "label": self.label,
                "base": round(self.base, 4), "value": round(self.value, 4)}


def _edge_index(graph: nx.DiGraph) -> dict[str, tuple[str, str]]:
    return {data["edge_id"]: (s, t) for s, t, data in graph.edges(data=True) if data.get("edge_id")}


def automatic_assumptions(
    comparison: OptionComparison,
    graph: nx.DiGraph,
    text: dict[str, str],
    outcome_nodes: dict[str, str],
    *,
    limit: int = AUTO_INPUTS,
) -> dict[str, list[Assumption]]:
    """Upside and downside from the inputs that move the weighted view's level most."""
    if comparison.unavailable or not comparison.driver_impacts:
        return {"upside": [], "downside": []}
    weights = {
        outcome_nodes[k]: w
        for k, w in decision_priorities.normalized_weights(comparison.priorities).items()
        if k in outcome_nodes
    } or {n: 1.0 for n in outcome_nodes.values()}
    total = sum(weights.values())

    def level(effects: dict[str, dict[str, tuple[float, float]]], end: int) -> float:
        per_option = [
            sum(values[n][end] * w for n, w in weights.items() if n in values) / total
            for values in effects.values()
        ]
        return sum(per_option) / len(per_option)

    scored = []
    for impact in comparison.driver_impacts:
        driver = impact.driver
        delta = level(driver.effects, 1) - level(driver.effects, 0)
        if abs(delta) > 1e-6:
            scored.append((abs(delta), driver.key, driver, delta))
    scored.sort(key=lambda item: (-item[0], item[1]))

    cases: dict[str, list[Assumption]] = {"upside": [], "downside": []}
    for _, _, driver, delta in scored[:limit]:
        if driver.kind == "link":
            data = graph.edges[driver.source, driver.target] if graph.has_edge(driver.source, driver.target) else {}
            ident = data.get("edge_id")
            if not ident:
                continue
            label = f"{text.get(driver.source, '?')} → {text.get(driver.target, '?')}"
        else:
            ident, label = driver.key, text.get(driver.key, "?")
        better, worse = (driver.high, driver.low) if delta > 0 else (driver.low, driver.high)
        cases["upside"].append(Assumption(driver.kind, ident, label, driver.current, better))
        cases["downside"].append(Assumption(driver.kind, ident, label, driver.current, worse))
    return cases


def stored_assumptions(row: Scenario, graph: nx.DiGraph, text: dict[str, str]) -> list[Assumption]:
    """The decider's own assumptions for a case, skipping inputs no longer in the graph."""
    edges = _edge_index(graph)
    out = []
    for edge_id, value in (row.edge_overrides or {}).items():
        if edge_id in edges:
            s, t = edges[edge_id]
            out.append(Assumption("link", edge_id, f"{text.get(s, '?')} → {text.get(t, '?')}",
                                  graph.edges[s, t].get("strength", 0.5), float(value)))
    for claim_id, value in (row.claim_overrides or {}).items():
        if claim_id in graph:
            out.append(Assumption("claim", claim_id, text.get(claim_id, "?"),
                                  graph.nodes[claim_id].get("prior", 0.5), float(value)))
    return out


def apply_assumptions(graph: nx.DiGraph, assumptions: list[Assumption]) -> nx.DiGraph:
    """A copy of the graph with the assumptions' values in place. The graph is untouched."""
    varied = graph.copy()
    edges = _edge_index(varied)
    for a in assumptions:
        value = max(0.0, min(1.0, a.value))
        if a.kind == "link" and a.id in edges:
            s, t = edges[a.id]
            varied.edges[s, t]["strength"] = value
        elif a.kind == "claim" and a.id in varied:
            varied.nodes[a.id]["prior"] = value
    return varied


def summarise_case(comparison: OptionComparison) -> dict[str, Any]:
    """What a case implies: per option outcomes and weighted view, and the headline verdict."""
    headline = None
    ranked = sorted(comparison.options, key=lambda r: -(r.weighted.score if r.weighted else 0.0))
    if len(ranked) >= 2 and not comparison.unavailable:
        pair = {ranked[0].key, ranked[1].key}
        for row in comparison.robustness:
            if {row["a"], row["b"]} == pair and row.get("weighted"):
                headline = {k: row["weighted"][k] for k in ("higher", "verdict", "share")}
    return {
        "options": [
            {
                "key": o.key, "label": o.label,
                "outcomes": {k: {x: v[x] for x in ("point", "p10", "p90")} for k, v in o.outcomes.items()},
                "weighted": round(o.weighted.score, 4) if o.weighted else None,
            }
            for o in comparison.options
        ],
        "headline": headline,
        "unavailable": comparison.unavailable,
    }


def build_scenarios(
    graph: nx.DiGraph,
    claims: list[Any],
    anchor: dict[str, Any] | None,
    base: OptionComparison,
    stored: dict[str, Scenario],
    *,
    priorities: dict[str, str] | None = None,
    runs: int = SCENARIO_RUNS,
) -> dict[str, Any]:
    """Base, upside and downside, each a rerun of the option comparison."""
    text = {str(c.id): c.text for c in claims}
    outcome_nodes = outcome_node_map(claims, anchor, graph)
    automatic = automatic_assumptions(base, graph, text, outcome_nodes)
    cases = [{
        "key": "base", "label": CASE_LABELS["base"], "source": "base", "assumptions": [],
        **summarise_case(base),
    }]
    for case in ("upside", "downside"):
        row = stored.get(case)
        assumptions = stored_assumptions(row, graph, text) if row is not None else automatic[case]
        varied = build_comparison(apply_assumptions(graph, assumptions), claims, anchor,
                                  runs=runs, priorities=priorities, explain=False)
        cases.append({
            "key": case, "label": CASE_LABELS[case],
            "source": "user" if row is not None else "automatic",
            "assumptions": [a.as_dict() for a in assumptions],
            **summarise_case(varied),
        })
    return {
        "outcomes": [{"key": k, "label": label} for k, label in base.outcomes],
        "cases": cases,
        "unavailable": base.unavailable,
    }


async def decision_cases(session: AsyncSession, project_id: UUID) -> dict[str, Scenario]:
    rows = (await session.execute(
        select(Scenario).where(Scenario.project_id == project_id, Scenario.decision_case.is_not(None))
        .order_by(Scenario.created_at)
    )).scalars()
    return {row.decision_case: row for row in rows}


async def project_scenarios(
    session: AsyncSession, project_id: UUID, base: OptionComparison | None = None
) -> dict[str, Any]:
    """The three cases for a project, computing the base comparison when not given."""
    from decision_studio.reasoning.decision_anchor import project_anchor
    from decision_studio.reasoning.effective_graph import load_effective_snapshot
    from decision_studio.reasoning.link_tests import snapshot_graph
    from decision_studio.reasoning.option_comparison import compare_project_options

    if base is None:
        base = await compare_project_options(session, project_id)
    snapshot = await load_effective_snapshot(project_id, session)
    return build_scenarios(
        snapshot_graph(snapshot), snapshot.claims, await project_anchor(session, project_id), base,
        await decision_cases(session, project_id),
        priorities=decision_priorities.clean_priorities(getattr(snapshot.project, "outcome_priorities", None)),
    )


async def save_case(
    session: AsyncSession, project_id: UUID, case: str, assumptions: list[dict[str, Any]]
) -> None:
    """Store the decider's assumptions for upside or downside.

    Raises:
        ValueError: unknown case, value out of range, or an input not in the graph.
    """
    from decision_studio.reasoning.effective_graph import load_effective_snapshot
    from decision_studio.reasoning.link_tests import snapshot_graph

    if case not in ("upside", "downside"):
        raise ValueError("Only the upside and downside take assumptions")
    graph = snapshot_graph(await load_effective_snapshot(project_id, session))
    edges = _edge_index(graph)
    edge_overrides: dict[str, float] = {}
    claim_overrides: dict[str, float] = {}
    for item in assumptions:
        value = float(item["value"])
        if not 0.0 <= value <= 1.0:
            raise ValueError("Values are probabilities or strengths, between 0 and 1")
        if item["kind"] == "link" and item["id"] in edges:
            edge_overrides[item["id"]] = value
        elif item["kind"] == "claim" and item["id"] in graph:
            if graph.in_degree(item["id"]) > 0:
                raise ValueError("Only a root claim's likelihood can be set; others follow from their causes")
            claim_overrides[item["id"]] = value
        else:
            raise ValueError(f"{item['kind']} {item['id']} is not in the reviewed graph")
    row = (await decision_cases(session, project_id)).get(case)
    if row is None:
        row = Scenario(project_id=project_id, name=CASE_LABELS[case], decision_case=case,
                       description="The decider's assumptions for this case of the option comparison.")
        session.add(row)
    row.edge_overrides = edge_overrides
    row.claim_overrides = claim_overrides
    await session.commit()


async def reset_case(session: AsyncSession, project_id: UUID, case: str) -> bool:
    """Back to the automatic case. True when there was something to reset."""
    row = (await decision_cases(session, project_id)).get(case)
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True
