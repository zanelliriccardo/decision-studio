"""Information priority: which open uncertainty is most worth investigating first.

Not a formal expected value of information, and not in money: an explainable
heuristic over quantities the analysis already has.

    score = uncertainty × impact × relevance

* **uncertainty** (0–1): how little is known about the input. For a link,
  ``value_of_information.link_uncertainty`` (its confidence and evidence); for a
  root claim, ``4·p·(1−p)`` (largest at 50%).
* **impact** (0–1): how far moving the input across its plausible range moves
  the gap between the two leading options on the weighted view
  (graph/option_sensitivity.py), in points out of 100, divided by
  ``FULL_IMPACT_POINTS`` (20) and capped at 1. Absolute rather than relative to
  the largest driver, so a 3-point movement is never called high impact just
  because nothing moves more.
* **relevance** (0.5–1): 1 when the input can reverse that comparison, 0.75
  when it can close the gap, 0.5 when it only widens or narrows it.

Each item says why it is listed. When an open link test already exists for the
link, it is the action; otherwise the action names the existing link or claim.
Nothing here invents a source, a claim or an event.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import networkx as nx
from sqlalchemy.ext.asyncio import AsyncSession

from decision_studio.graph.option_sensitivity import ERASES, FLIPS
from decision_studio.reasoning.option_comparison import OptionComparison, driver_uncertainty

MAX_ITEMS = 5
RELEVANCE = {FLIPS: 1.0, ERASES: 0.75}
DEFAULT_RELEVANCE = 0.5
#: A 20-point movement of the weighted gap counts as full impact.
FULL_IMPACT_POINTS = 20.0
#: Bands on the 0-1 uncertainty and impact terms. For impact: high from 10
#: points of movement, medium from 3.
HIGH, MEDIUM = 0.50, 0.15
UNCERTAINTY_HIGH, UNCERTAINTY_MEDIUM = 0.66, 0.33


def band(value: float, high: float = UNCERTAINTY_HIGH, medium: float = UNCERTAINTY_MEDIUM) -> str:
    """high / medium / low, for display next to the number."""
    if value >= high:
        return "high"
    if value >= medium:
        return "medium"
    return "low"


def _points(value: float) -> str:
    points = round(value * 100)
    return f"{points} point" if points == 1 else f"{points} points"


def rank_information(
    comparison: OptionComparison,
    graph: nx.DiGraph,
    text: dict[str, str],
    open_tests_by_edge: dict[str, Any] | None = None,
    *,
    limit: int = MAX_ITEMS,
) -> list[dict[str, Any]]:
    """The top information needs for the headline comparison, most valuable first."""
    impacts = comparison.driver_impacts
    if comparison.unavailable or not impacts or not comparison.headline_pair:
        return []
    a, b = comparison.headline_pair
    labels = {row.key: row.label for row in comparison.options}
    tests = open_tests_by_edge or {}

    items = []
    for impact in impacts:
        uncertainty = driver_uncertainty(impact, graph)
        impact_share = min(1.0, impact.impact * 100 / FULL_IMPACT_POINTS)
        relevance = RELEVANCE.get(impact.flip, DEFAULT_RELEVANCE)
        score = uncertainty * impact_share * relevance
        if score <= 0:
            continue
        driver = impact.driver
        edge_id = None
        test = None
        if driver.kind == "link":
            source, target = text.get(driver.source, "?"), text.get(driver.target, "?")
            if graph.has_edge(driver.source, driver.target):
                edge_id = graph.edges[driver.source, driver.target].get("edge_id")
            test = tests.get(edge_id) if edge_id else None
            subject = f"{source} → {target}"
            action = (test.statement if test is not None
                      else f"Check how strongly “{source}” drives “{target}”.")
        else:
            subject = text.get(driver.key, "?")
            action = f"Establish whether “{subject}” holds."
        why = (
            f"{band(uncertainty).capitalize()} uncertainty; "
            f"{band(impact_share, HIGH, MEDIUM)} impact on {labels[a]} vs {labels[b]} — "
            f"across its plausible range the weighted gap moves by {_points(impact.impact)}"
        )
        if impact.flip == FLIPS:
            why += " and can reverse the comparison."
        elif impact.flip == ERASES:
            why += " and can close it."
        else:
            why += "."
        items.append({
            "kind": driver.kind,
            "key": driver.key,
            "edge_id": edge_id,
            "claim_id": driver.key if driver.kind == "claim" else None,
            "subject": subject,
            "action": action,
            "how": (test.cheapest_test or None) if test is not None else None,
            "hypothesis_id": str(test.id) if test is not None else None,
            "uncertainty": round(uncertainty, 4),
            "uncertainty_band": band(uncertainty),
            "impact": round(impact_share, 4),
            "impact_band": band(impact_share, HIGH, MEDIUM),
            "can_flip": impact.flip == FLIPS,
            "score": round(score, 4),
            "why": why,
        })
    items.sort(key=lambda item: (-item["score"], item["key"]))
    return items[:limit]


async def attach_information_priority(
    session: AsyncSession,
    project_id: UUID,
    comparison: OptionComparison,
    graph: nx.DiGraph,
    claims: list[Any],
) -> None:
    """Fill ``comparison.information_priority`` from the ranked drivers and open link tests."""
    from decision_studio.reasoning.link_tests import list_hypotheses

    if comparison.unavailable or not comparison.driver_impacts:
        return
    open_tests: dict[str, Any] = {}
    for hypothesis in await list_hypotheses(session, project_id):
        # Most valuable open test first (list order), one per link.
        if hypothesis.status == "open":
            open_tests.setdefault(str(hypothesis.edge_id), hypothesis)
    comparison.information_priority = rank_information(
        comparison, graph, {str(c.id): c.text for c in claims}, open_tests,
    )
