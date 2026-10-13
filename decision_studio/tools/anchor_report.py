"""How closely a project's graph is anchored to its decision.

Written to measure the change the decision anchor was built to make. Before it,
twelve documents produced 476 claims in 58 components, with nothing in the
graph standing for the decision and no way to say which claims bore on it. Run
this on a project before and after anchoring it::

    python -m decision_studio.tools.anchor_report <project-id>
    python -m decision_studio.tools.anchor_report <project-id> --json

An old project has no anchor, so most rows read "n/a". To compare like with
like, save an anchor for it (the summary page, or
``PUT /api/v1/graph/{id}/decision-anchor``): that adds the outcome nodes, links
them into the existing graph and scores every claim, without re-running the
pipeline. Then run this again. A fresh run with an anchor is the other half of
the comparison, since extraction and discovery themselves change.

It writes nothing to the database.

What the numbers mean:

* **Reach an outcome** — claims with a directed causal path to an outcome node.
  The headline: the share of the graph that bears on the decision *by
  structure*, whatever the model said about each claim.
* **Stated relevance** — the model's per-claim score. High share at >= 0.5 with
  low reach means claims were judged relevant but not linked: look at causal
  inference. The reverse means the model under-read claims the graph connects —
  those are the **peripheral** claims, and they are the interesting ones.
* **Components / isolated** — fragmentation, as ``dag_builder`` logs it.
* **Theories reaching an outcome** — current theories citing an outcome node.
  A theory that reaches none describes the situation instead of the choice.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from typing import Any
from uuid import UUID

import networkx as nx

from decision_studio.graph.anchoring import (
    anchor_distances,
    in_lens,
    is_peripheral,
)
from decision_studio.reasoning.decision_anchor import ORIGIN_FRAME, ROLE_OUTCOME


def compute_report(
    claims: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    theory_claims: dict[str, set[str]] | None = None,
    anchor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Anchoring metrics over the effective graph.

    ``claims`` carry ``id``, ``origin``, ``decision_role``, ``relevance``;
    ``edges`` carry ``source`` and ``target`` claim ids. Only active elements
    should be passed — this measures the graph the reasoning sees.
    """
    ids = {c["id"] for c in claims}
    outcomes = [
        c["id"] for c in claims
        if c.get("origin") == ORIGIN_FRAME and c.get("decision_role") == ROLE_OUTCOME
    ]
    subject = [c for c in claims if c["id"] not in set(outcomes)]

    graph = nx.DiGraph()
    graph.add_nodes_from(ids)
    graph.add_edges_from(
        (e["source"], e["target"]) for e in edges
        if e["source"] in ids and e["target"] in ids
    )
    undirected = graph.to_undirected()
    components = list(nx.connected_components(undirected)) if ids else []

    distances = anchor_distances(graph, outcomes) if outcomes else {}
    reaching = [c for c in subject if c["id"] in distances]
    scored = [c for c in subject if c.get("relevance") is not None]
    relevances = [c["relevance"] for c in scored]

    def share(part: int, whole: int) -> float | None:
        return round(part / whole, 3) if whole else None

    theory_claims = theory_claims or {}
    outcome_set = set(outcomes)
    theories_reaching = sum(1 for cited in theory_claims.values() if cited & outcome_set)

    return {
        "anchored": anchor is not None,
        "options": len((anchor or {}).get("options", [])),
        "outcome_nodes": len(outcomes),
        "claims": len(subject),
        "edges": graph.number_of_edges(),
        "components": len(components),
        "largest_component": max((len(c) for c in components), default=0),
        "isolated": sum(1 for n in graph.nodes if graph.degree(n) == 0),
        "reach_outcome": len(reaching) if outcomes else None,
        "reach_outcome_share": share(len(reaching), len(subject)) if outcomes else None,
        "edges_into_outcomes": sum(
            1 for _, target in graph.edges if target in outcome_set
        ),
        "scored": len(scored),
        "relevance_mean": round(sum(relevances) / len(relevances), 3) if relevances else None,
        "relevance_high_share": share(sum(1 for r in relevances if r >= 0.5), len(scored)),
        "relevance_background_share": share(sum(1 for r in relevances if r < 0.2), len(scored)),
        "in_lens": sum(
            1 for c in subject if in_lens(c.get("relevance"), distances.get(c["id"]))
        ) if (outcomes or scored) else None,
        "peripheral": sum(
            1 for c in subject if is_peripheral(c.get("relevance"), distances.get(c["id"]))
        ),
        "roles": dict(Counter(c.get("decision_role") or "unscored" for c in subject)),
        "theories": len(theory_claims),
        "theories_reaching_outcome": theories_reaching if outcomes else None,
    }


async def load(project_id: UUID) -> tuple[dict | None, list[dict], list[dict], dict[str, set[str]]]:
    """The project's anchor, active claims, active edges and current theory citations."""
    from sqlalchemy import select

    from decision_studio.db.models import CausalEdge, Claim, Project, Theory, TheoryClaim
    from decision_studio.db.session import async_session
    from decision_studio.reasoning.decision_anchor import normalise_anchor
    from decision_studio.reasoning.effective_graph import (
        is_claim_effective,
        is_edge_effective,
    )

    async with async_session() as session:
        project = await session.get(Project, project_id)
        if project is None:
            return None, [], [], {}
        db_claims = [
            c for c in (
                await session.execute(select(Claim).where(Claim.project_id == project_id))
            ).scalars().all()
            if is_claim_effective(c)
        ]
        active = {str(c.id) for c in db_claims}
        db_edges = [
            e for e in (
                await session.execute(
                    select(CausalEdge).where(CausalEdge.project_id == project_id)
                )
            ).scalars().all()
            if is_edge_effective(e, active) and not e.is_feedback
        ]
        rows = (
            await session.execute(
                select(TheoryClaim.theory_id, TheoryClaim.claim_id)
                .join(Theory, Theory.id == TheoryClaim.theory_id)
                .where(Theory.project_id == project_id, Theory.is_current.is_(True))
            )
        ).all()

    theory_claims: dict[str, set[str]] = {}
    for theory_id, claim_id in rows:
        theory_claims.setdefault(str(theory_id), set()).add(str(claim_id))

    claims = [
        {
            "id": str(c.id),
            "origin": c.origin,
            "decision_role": c.decision_role,
            "relevance": c.relevance,
        }
        for c in db_claims
    ]
    edges = [
        {"source": str(e.source_claim_id), "target": str(e.target_claim_id)}
        for e in db_edges
    ]
    return normalise_anchor(project.decision_anchor), claims, edges, theory_claims


def _fmt(value: Any, percent: bool = False) -> str:
    if value is None:
        return "n/a"
    if percent:
        return f"{100 * value:.0f}%"
    return str(value)


def render(report: dict[str, Any]) -> str:
    """The report as aligned text."""
    rows = [
        ("Anchored", "yes" if report["anchored"] else "no"),
        ("Options / outcome nodes", f"{report['options']} / {report['outcome_nodes']}"),
        ("Claims (excl. outcomes)", _fmt(report["claims"])),
        ("Edges", _fmt(report["edges"])),
        ("Components / largest", f"{report['components']} / {report['largest_component']}"),
        ("Isolated claims", _fmt(report["isolated"])),
        ("Reach an outcome", f"{_fmt(report['reach_outcome'])} "
                             f"({_fmt(report['reach_outcome_share'], True)})"),
        ("Edges into outcomes", _fmt(report["edges_into_outcomes"])),
        ("Claims scored", _fmt(report["scored"])),
        ("Mean stated relevance", _fmt(report["relevance_mean"])),
        ("Stated relevance >= 0.5", _fmt(report["relevance_high_share"], True)),
        ("Stated relevance < 0.2", _fmt(report["relevance_background_share"], True)),
        ("In the decision lens", _fmt(report["in_lens"])),
        ("Peripheral but connected", _fmt(report["peripheral"])),
        ("Theories / reaching outcome", f"{report['theories']} / "
                                        f"{_fmt(report['theories_reaching_outcome'])}"),
    ]
    width = max(len(label) for label, _ in rows)
    lines = [f"{label:<{width}}  {value}" for label, value in rows]
    roles = ", ".join(f"{k} {v}" for k, v in sorted(report["roles"].items()))
    lines.append(f"{'Roles':<{width}}  {roles or 'n/a'}")
    return "\n".join(lines)


async def main() -> int:
    """Print the anchoring report for one project."""
    parser = argparse.ArgumentParser(
        description="Measure how closely a project's graph is anchored to its decision.",
    )
    parser.add_argument("project_id")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    args = parser.parse_args()

    anchor, claims, edges, theory_claims = await load(UUID(args.project_id))
    if not claims:
        print("No claims found for that project.", file=sys.stderr)
        return 1

    report = compute_report(claims, edges, theory_claims, anchor)
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
