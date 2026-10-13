"""Testing a theory link by link.

The theory-based view derives hypotheses from a theory and tests them before
committing. A whole theory is rarely testable at once; its links usually are.
This module picks the links worth testing (graph/value_of_information.py),
turns them into falsifiable hypotheses, and records what the tests found — as
evidence against the theory's conviction (reasoning/theory_value.py).

Hypotheses are keyed by ``theory_key``, like conviction, so a regenerated
theory keeps the tests already run on it. Proposing again replaces only the
hypotheses still open: a result someone went and got is never discarded.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import networkx as nx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_studio.db.models import LinkHypothesis, Theory
from decision_studio.graph.value_of_information import (
    break_cycles,
    link_uncertainty,
    rank_links,
)
from decision_studio.llm.client import LLMClient, get_llm_client
from decision_studio.llm.prompts import language_instruction
from decision_studio.llm.prompts.link_hypotheses import (
    LINK_HYPOTHESIS_SCHEMA,
    LINK_HYPOTHESIS_SYSTEM,
)
from decision_studio.reasoning.decision_anchor import ORIGIN_FRAME, ROLE_OUTCOME, project_anchor, render_anchor
from decision_studio.reasoning.effective_graph import (
    GraphSnapshot,
    effective_strength,
    load_effective_snapshot,
)
from decision_studio.reasoning.theory_value import LIKELIHOOD_SCALE, record_evidence

logger = logging.getLogger(__name__)

#: Links turned into hypotheses per request. Three is enough to find the one
#: that matters; ten would be a research programme nobody runs.
MAX_LINKS = 3

RESULTS = ("held", "refuted", "inconclusive")

#: Default likelihood ratio of each result. A link holding is support, not
#: proof — the rest of the chain may still fail — so it moves conviction less
#: than a refutation, which breaks the chain outright.
DEFAULT_RESULT_LR = {
    "held": LIKELIHOOD_SCALE["for"],
    "refuted": LIKELIHOOD_SCALE["strongly_against"],
    "inconclusive": LIKELIHOOD_SCALE["neutral"],
}

#: The same, by the decisiveness the decider stated before testing. "Moderate"
#: is ``DEFAULT_RESULT_LR``, so results recorded without one are unchanged.
RESULT_LR_BY_DECISIVENESS = {
    "weak": {"held": 1.5, "refuted": 0.5, "inconclusive": 1.0},
    "moderate": DEFAULT_RESULT_LR,
    "decisive": {"held": 3.0, "refuted": 0.1, "inconclusive": 1.0},
}


def result_likelihood(result: str, decisiveness: str | None) -> float:
    from decision_studio.reasoning.theory_value import decisiveness_of

    return RESULT_LR_BY_DECISIVENESS[decisiveness_of(decisiveness)][result]


class LinkTestError(ValueError):
    """Raised when a theory has nothing that can be tested link by link."""


def snapshot_graph(snapshot: GraphSnapshot) -> nx.DiGraph:
    """The reviewed graph as networkx, with what propagation needs."""
    graph = nx.DiGraph()
    for claim in snapshot.claims:
        graph.add_node(
            str(claim.id),
            prior=claim.prior,
            confidence=claim.confidence,
            logic_gate=getattr(claim, "logic_gate", "or") or "or",
        )
    for edge in snapshot.edges:
        if getattr(edge, "is_feedback", False):
            continue
        graph.add_edge(
            str(edge.source_claim_id),
            str(edge.target_claim_id),
            strength=effective_strength(edge),
            evidence_score=edge.evidence_score,
            # The same inputs the graph screen propagates with, so a test's
            # leverage and an option's forecast agree with the beliefs shown.
            has_contradiction=any(
                ev.evidence_type == "contradicting"
                for ev in snapshot.evidence_by_edge.get(str(edge.id), [])
            ),
            link_confidence=getattr(edge, "link_confidence", None),
            causal_type=getattr(edge, "causal_type", "direct") or "direct",
            edge_id=str(edge.id),
        )
    return break_cycles(graph)


def chain_links(theory: Theory, snapshot: GraphSnapshot) -> tuple[list[dict[str, Any]], str | None]:
    """The theory's chain links still in the graph, and the chain's destination.

    The destination is the last outcome node on the chain when it reaches one,
    otherwise the chain's last claim: a theory that stops short of the decision
    is still tested against where it does arrive.
    """
    links: list[dict[str, Any]] = []
    claims_in_order: list[str] = []
    for step in theory.causal_chain or []:
        if not isinstance(step, dict):
            continue
        if step.get("claim_id"):
            claims_in_order.append(step["claim_id"])
        edge = snapshot.edges_by_id.get(step.get("edge_id") or "")
        if edge is None:
            continue
        links.append({
            "edge_id": str(edge.id),
            "source": str(edge.source_claim_id),
            "target": str(edge.target_claim_id),
            "uncertainty": link_uncertainty(
                getattr(edge, "link_confidence", None), edge.evidence_score
            ),
            "mechanism": edge.mechanism,
        })
        claims_in_order += [str(edge.source_claim_id), str(edge.target_claim_id)]

    in_graph = [c for c in claims_in_order if c in snapshot.claims_by_id]
    outcomes = [
        c for c in in_graph
        if snapshot.claims_by_id[c].origin == ORIGIN_FRAME
        and snapshot.claims_by_id[c].decision_role == ROLE_OUTCOME
    ]
    destination = outcomes[-1] if outcomes else (in_graph[-1] if in_graph else None)
    return links, destination


async def propose_hypotheses(
    session: AsyncSession,
    project_id: UUID,
    theory_id: UUID,
    *,
    llm: LLMClient | None = None,
    max_links: int = MAX_LINKS,
) -> list[LinkHypothesis]:
    """Rank a theory's links and turn the most valuable into hypotheses.

    Raises:
        LookupError: unknown theory.
        LinkTestError: the theory's chain has no link left in the graph.
    """
    theory = (await session.execute(
        select(Theory).where(Theory.id == theory_id, Theory.project_id == project_id)
    )).scalars().first()
    if theory is None:
        raise LookupError(f"Theory {theory_id} not found in project")

    snapshot = await load_effective_snapshot(project_id, session)
    links, destination = chain_links(theory, snapshot)
    if not links or destination is None:
        raise LinkTestError(
            "This theory's causal chain has no link left in the reviewed graph to test."
        )

    ranked = rank_links(snapshot_graph(snapshot), links, destination)[:max_links]
    claims = snapshot.claims_by_id
    numbered = "\n\n".join(
        f"[{i}] {claims[r['source']].text}\n    --({r['mechanism']})-->\n    "
        f"{claims[r['target']].text}"
        for i, r in enumerate(ranked)
    )
    anchor = await project_anchor(session, project_id)
    user = (
        f"{render_anchor(anchor)}\n# Theory\n{theory.title}\n{theory.summary}\n\n"
        f"# Links worth testing, most valuable first\n{numbered}"
        + language_instruction(theory.summary)
    )

    client = llm or get_llm_client(enable_cache=False)
    payload = await client.complete_json(
        system=LINK_HYPOTHESIS_SYSTEM,
        user=user,
        schema=LINK_HYPOTHESIS_SCHEMA,
        max_tokens=2048,
        temperature=0.3,
    )

    # Only open hypotheses are replaced; results already obtained stay.
    await session.execute(
        delete(LinkHypothesis).where(
            LinkHypothesis.project_id == project_id,
            LinkHypothesis.theory_key == theory.theory_key,
            LinkHypothesis.status == "open",
        )
    )
    created: list[LinkHypothesis] = []
    for entry in payload.get("hypotheses") or []:
        if not isinstance(entry, dict):
            continue
        index = entry.get("index")
        if not isinstance(index, int) or not 0 <= index < len(ranked):
            continue
        statement = (entry.get("statement") or "").strip()
        refuted_if = (entry.get("refuted_if") or "").strip()
        if not statement or not refuted_if:
            continue
        link = ranked[index]
        row = LinkHypothesis(
            project_id=project_id,
            theory_key=theory.theory_key,
            theory_id=theory.id,
            edge_id=UUID(link["edge_id"]),
            statement=statement,
            refuted_if=refuted_if,
            cheapest_test=(entry.get("cheapest_test") or "").strip(),
            priority=link["priority"],
            leverage=link["leverage"],
            uncertainty=link["uncertainty"],
        )
        session.add(row)
        created.append(row)
    await session.commit()
    logger.info(
        "Link hypotheses: %d for theory %s (%d link(s) ranked)",
        len(created), theory_id, len(ranked),
    )
    return sorted(created, key=lambda h: h.priority, reverse=True)


async def list_hypotheses(
    session: AsyncSession, project_id: UUID, theory_key: UUID | None = None
) -> list[LinkHypothesis]:
    """Hypotheses for a project, or for one theory, most valuable first."""
    stmt = select(LinkHypothesis).where(LinkHypothesis.project_id == project_id)
    if theory_key is not None:
        stmt = stmt.where(LinkHypothesis.theory_key == theory_key)
    rows = list((await session.execute(stmt)).scalars().all())
    return sorted(rows, key=lambda h: (h.status != "open", -h.priority))


async def record_result(
    session: AsyncSession,
    project_id: UUID,
    hypothesis_id: UUID,
    result: str,
    *,
    likelihood_ratio: float | None = None,
    note: str | None = None,
    event: str | None = None,
) -> LinkHypothesis:
    """Record what testing a link found, as evidence against the theory's conviction.

    Raises:
        LookupError: unknown hypothesis.
        ValueError: unknown result.
    """
    if result not in RESULTS:
        raise ValueError(f"Result must be one of {', '.join(RESULTS)}")
    row = (await session.execute(
        select(LinkHypothesis).where(
            LinkHypothesis.id == hypothesis_id, LinkHypothesis.project_id == project_id
        )
    )).scalars().first()
    if row is None:
        raise LookupError(f"Hypothesis {hypothesis_id} not found in project")

    row.status = result
    row.observed_note = (note or "").strip()[:2000] or None
    row.observed_at = datetime.now(timezone.utc)
    await record_evidence(
        session, project_id, row.theory_key,
        likelihood_ratio if likelihood_ratio is not None
        else result_likelihood(result, row.decisiveness),
        source="link_hypothesis", source_id=row.id,
        note=f"Link {result}: {row.statement}",
        event=event,
        commit=False,
    )
    if result == "refuted":
        # A refuted link breaks the chain, like a fired tripwire: the current
        # version of the theory should be revisited, not left standing.
        current = (await session.execute(
            select(Theory).where(
                Theory.project_id == project_id,
                Theory.theory_key == row.theory_key,
                Theory.is_current.is_(True),
            )
        )).scalars().first()
        if current is not None:
            current.is_stale = True
            current.stale_reason = f"A tested link was refuted: {row.statement}"
    await session.commit()
    await session.refresh(row)
    return row


async def set_decisiveness(
    session: AsyncSession, project_id: UUID, hypothesis_id: UUID, decisiveness: str
) -> LinkHypothesis:
    """State how much a link test would count, before it is run.

    Raises:
        LookupError: unknown hypothesis.
        ValueError: already tested (see adversary.set_tripwire_decisiveness).
    """
    from decision_studio.reasoning.theory_value import DECISIVENESS

    if decisiveness not in DECISIVENESS:
        raise ValueError(f"Decisiveness must be one of {', '.join(DECISIVENESS)}")
    row = (await session.execute(
        select(LinkHypothesis).where(
            LinkHypothesis.id == hypothesis_id, LinkHypothesis.project_id == project_id
        )
    )).scalars().first()
    if row is None:
        raise LookupError(f"Hypothesis {hypothesis_id} not found in project")
    if row.status != "open":
        raise ValueError("Decisiveness is stated before testing, and this link has been tested")
    row.decisiveness = decisiveness
    await session.commit()
    await session.refresh(row)
    return row


async def record_data_result(
    session: AsyncSession,
    project_id: UUID,
    hypothesis_id: UUID,
    table: str,
    *,
    time_ordered: bool = True,
    event: str | None = None,
):
    """Test a link hypothesis against a pasted two-column table, and record the result.

    Returns ``(hypothesis, verdict)``.

    Raises:
        LookupError: unknown hypothesis.
        link_data.TableError: the table cannot be read.
    """
    from decision_studio.db.models import CausalEdge
    from decision_studio.reasoning import link_data

    row = (await session.execute(
        select(LinkHypothesis).where(
            LinkHypothesis.id == hypothesis_id, LinkHypothesis.project_id == project_id
        )
    )).scalars().first()
    if row is None:
        raise LookupError(f"Hypothesis {hypothesis_id} not found in project")
    edge = await session.get(CausalEdge, row.edge_id)
    cause, effect = link_data.parse_table(table)
    verdict = link_data.analyse(
        cause, effect,
        inhibiting=getattr(edge, "causal_type", "direct") == "inhibiting",
        time_ordered=time_ordered,
    )
    updated = await record_result(
        session, project_id, hypothesis_id, verdict.result,
        note=f"From your data: {verdict.summary}", event=event,
    )
    return updated, verdict
