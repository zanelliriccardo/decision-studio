"""Sub-decisions: how an option depends on the choices made inside it.

"Commit to Q3" is rarely one thing: it comes with a staffing choice, a vendor
choice, a scope choice. V1 keeps this deliberately light: a sub-decision hangs
under one parent option and has two to four choices, each defined by existing
claims in the graph ("what this choice involves"). No new claims, no tree of
options, no second graph.

Each choice is evaluated as an intervention on the same map, exactly like an
option (reasoning/option_comparison.intervene):

    do(parent option's levers)  +  do(this choice's claims = true)
                                +  do(the other choices' claims = false)

and the choices are compared with the existing Monte Carlo
(graph/stability.compare_options) under the decider's priorities. So the result
reads "under Q3, the staffing choice moves the weighted view from 42 to 58
points; Contractors is robustly higher", in the same vocabulary as the option
comparison (reasoning/decision_robustness.py). It never picks a choice.

The main option comparison is unchanged: it evaluates each option with its
sub-choices as the map currently has them. This view shows how much that
depends on the sub-decision.

Stored on ``project.sub_decisions``: a list of
``{key, parent, label, choices: [{key, label, claim_ids}]}``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import networkx as nx
from sqlalchemy.ext.asyncio import AsyncSession

from decision_studio.graph.stability import WEIGHTED, compare_options
from decision_studio.reasoning import decision_priorities, decision_robustness
from decision_studio.reasoning.decision_anchor import ORIGIN_FRAME, ROLE_OUTCOME
from decision_studio.reasoning.option_comparison import intervene, option_levers, outcome_node_map

MAX_SUB_DECISIONS = 6
MIN_CHOICES, MAX_CHOICES = 2, 4
MAX_LABEL = 200
SUB_DECISION_RUNS = 100


def normalise(
    raw: Any, option_keys: set[str], usable_claims: set[str], *, strict: bool = False
) -> list[dict[str, Any]]:
    """Clean stored or submitted sub-decisions and assign keys (S1.., S1a..).

    Args:
        usable_claims: ids of claims a choice may reference (in the graph, not
            a success criterion).
        strict: raise on anything invalid instead of dropping it (for input).

    Raises:
        ValueError: when ``strict`` and the input is invalid.
    """
    def fail(message: str) -> None:
        if strict:
            raise ValueError(message)

    out: list[dict[str, Any]] = []
    for item in (raw or [])[:MAX_SUB_DECISIONS] if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        parent = item.get("parent")
        label = str(item.get("label") or "").strip()[:MAX_LABEL]
        if parent not in option_keys:
            fail(f"Unknown parent option: {parent}")
            continue
        if not label:
            fail("A sub-decision needs a label")
            continue
        key = f"S{len(out) + 1}"
        choices = []
        for choice in item.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            choice_label = str(choice.get("label") or "").strip()[:MAX_LABEL]
            claim_ids = [str(c) for c in choice.get("claim_ids") or []]
            unknown = [c for c in claim_ids if c not in usable_claims]
            if unknown:
                fail(f"Choice “{choice_label}” refers to claims not in the reviewed graph")
                claim_ids = [c for c in claim_ids if c in usable_claims]
            if not choice_label or not claim_ids:
                fail("Every choice needs a label and at least one claim describing what it involves")
                continue
            choices.append({"key": f"{key}{chr(ord('a') + len(choices))}", "label": choice_label,
                            "claim_ids": list(dict.fromkeys(claim_ids))})
        if not MIN_CHOICES <= len(choices) <= MAX_CHOICES:
            fail(f"A sub-decision needs {MIN_CHOICES} to {MAX_CHOICES} choices")
            continue
        out.append({"key": key, "parent": parent, "label": label, "choices": choices})
    return out


def usable_claim_ids(claims: list[Any], graph: nx.DiGraph) -> set[str]:
    return {
        str(c.id) for c in claims
        if str(c.id) in graph
        and not (getattr(c, "origin", None) == ORIGIN_FRAME and getattr(c, "decision_role", None) == ROLE_OUTCOME)
    }


def evaluate(
    graph: nx.DiGraph,
    claims: list[Any],
    anchor: dict[str, Any] | None,
    sub_decisions: list[dict[str, Any]],
    *,
    priorities: dict[str, str] | None = None,
    runs: int = SUB_DECISION_RUNS,
) -> list[dict[str, Any]]:
    """Every sub-decision with each choice's option-implied outcomes and weighted view."""
    options = {o["key"]: o["label"] for o in (anchor or {}).get("options", [])}
    outcome_nodes = outcome_node_map(claims, anchor, graph)
    outcome_labels = {o["key"]: o["label"] for o in (anchor or {}).get("outcomes", [])}
    outcomes = [(k, outcome_labels[k]) for k in outcome_labels if k in outcome_nodes]
    resolved = decision_priorities.resolve(outcomes, priorities)
    weights_by_key = decision_priorities.normalized_weights(resolved)
    weights_by_node = {outcome_nodes[k]: w for k, w in weights_by_key.items()}
    levers = option_levers(claims, list(options))
    text = {str(c.id): c.text for c in claims}
    targets = set(outcome_nodes.values())

    results = []
    for sd in sub_decisions:
        parent_on, parent_off = levers.get(sd["parent"], ([], []))
        on = [str(c.id) for c in parent_on if str(c.id) in graph]
        off = [str(c.id) for c in parent_off if str(c.id) in graph]
        entry: dict[str, Any] = {
            "key": sd["key"], "parent": sd["parent"], "parent_label": options.get(sd["parent"], ""),
            "label": sd["label"], "outcomes": [{"key": k, "label": label} for k, label in outcomes],
            "choices": [], "spread": None, "verdict": None, "sentence": None, "unavailable": None,
        }
        if not outcomes:
            entry["unavailable"] = "No success criterion is in the graph."
            results.append(entry)
            continue
        graphs = {}
        for choice in sd["choices"]:
            mine = set(choice["claim_ids"])
            others = {c for other in sd["choices"] if other is not choice for c in other["claim_ids"]} - mine
            # The choice's own claims win over the parent's switched-off levers
            # (intervene applies "off" after "on", so a claim in both would be
            # silently switched off and the choice would change nothing).
            graphs[choice["key"]] = intervene(
                graph, [c for c in on if c not in others] + sorted(mine),
                [c for c in off if c not in mine] + sorted(others),
            )
        forecasts, _ = compare_options(graphs, list(outcome_nodes.values()), runs=runs,
                                       weights=weights_by_node or None)
        node_to_key = {n: k for k, n in outcome_nodes.items()}
        for choice in sd["choices"]:
            forecast = forecasts[choice["key"]]
            values = {node_to_key[n]: s.point for n, s in forecast.outcomes.items()}
            view = decision_priorities.weighted_view(values, weights_by_key)
            entry["choices"].append({
                "key": choice["key"], "label": choice["label"],
                "claims": [{"id": c, "text": text.get(c, "?")} for c in choice["claim_ids"]],
                "reaches_outcome": any(targets & nx.descendants(graph, c) for c in choice["claim_ids"] if c in graph),
                "outcomes": {
                    node_to_key[n]: {"point": round(s.point, 4), "p10": round(s.p10, 4), "p90": round(s.p90, 4)}
                    for n, s in forecast.outcomes.items()
                },
                "weighted": round(view.score, 4) if view else None,
            })
        scored = [c for c in entry["choices"] if c["weighted"] is not None]
        if len(scored) >= 2:
            ranked = sorted(scored, key=lambda c: (-c["weighted"], c["key"]))
            top, second = ranked[0], ranked[1]
            share = forecasts[top["key"]].higher_than.get(second["key"], {}).get(WEIGHTED, 0.5)
            verdict = decision_robustness.classify(top["key"], second["key"], top["weighted"],
                                                   second["weighted"], share)
            entry["verdict"] = verdict.as_dict()
            low, high = min(c["weighted"] for c in scored), max(c["weighted"] for c in scored)
            entry["spread"] = round(high - low, 4)
            labels = {c["key"]: c["label"] for c in entry["choices"]}
            entry["sentence"] = (
                f"Under {sd['parent']} {entry['parent_label']}, the {sd['label'].lower()} choice moves the "
                f"weighted view from {round(low * 100)} to {round(high * 100)} points. "
                + decision_robustness.describe(verdict, "the weighted view", labels)
            )
        elif not scored:
            entry["unavailable"] = "Every success criterion is set to “not a factor”: there is no weighted view."
        if not any(c["reaches_outcome"] for c in entry["choices"]):
            entry["unavailable"] = ("None of the claims behind these choices has a causal path to a "
                                    "success criterion, so the map cannot tell them apart.")
        results.append(entry)
    return results


async def project_sub_decisions(session: AsyncSession, project_id: UUID) -> list[dict[str, Any]]:
    """The project's sub-decisions, evaluated on the reviewed graph."""
    from decision_studio.reasoning.decision_anchor import project_anchor
    from decision_studio.reasoning.effective_graph import load_effective_snapshot
    from decision_studio.reasoning.link_tests import snapshot_graph

    snapshot = await load_effective_snapshot(project_id, session)
    raw = getattr(snapshot.project, "sub_decisions", None)
    if not raw:
        return []
    anchor = await project_anchor(session, project_id)
    graph = snapshot_graph(snapshot)
    cleaned = normalise(raw, {o["key"] for o in (anchor or {}).get("options", [])},
                        usable_claim_ids(snapshot.claims, graph))
    return evaluate(graph, snapshot.claims, anchor, cleaned,
                    priorities=decision_priorities.clean_priorities(
                        getattr(snapshot.project, "outcome_priorities", None)))


async def save_sub_decisions(session: AsyncSession, project_id: UUID, raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace the project's sub-decisions after validating them against the graph.

    Raises:
        ValueError: invalid input (unknown option or claim, wrong number of choices).
    """
    from decision_studio.reasoning.decision_anchor import project_anchor
    from decision_studio.reasoning.effective_graph import load_effective_snapshot
    from decision_studio.reasoning.link_tests import snapshot_graph

    snapshot = await load_effective_snapshot(project_id, session)
    anchor = await project_anchor(session, project_id)
    cleaned = normalise(raw, {o["key"] for o in (anchor or {}).get("options", [])},
                        usable_claim_ids(snapshot.claims, snapshot_graph(snapshot)), strict=True)
    snapshot.project.sub_decisions = cleaned or None
    await session.commit()
    return cleaned
