"""Builds the compact generation context handed to the LLM.

Two problems are solved here.

**Token budget.** A Decision Studio project can hold hundreds of claims and edges;
sending all of them costs a fortune and buries the signal. ``select_subgraph``
scores elements by decision relevance (critical path, roots, terminals,
centrality, evidence quality, human priority, overlap with the stated decision
objective) and keeps the top slice.

**Reference integrity.** Raw UUIDs are ~37 characters each and models mangle
them. Instead every selected element gets a short reference token — ``C1`` for
claims, ``E1`` for edges, ``V1`` for evidence — and the model is asked to cite
those. :class:`ReferenceMap` translates back to real UUIDs afterwards, and any
token the model invents simply fails to resolve, which is exactly the
validation behaviour we want.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from decision_studio.db.models import CausalEdge, Claim, Evidence, Theory
from decision_studio.reasoning.effective_graph import GraphSnapshot, effective_strength

logger = logging.getLogger(__name__)

DEFAULT_MAX_CLAIMS = 60
DEFAULT_MAX_EDGES = 120
DEFAULT_MAX_EVIDENCE_PER_EDGE = 2
SNIPPET_LEN = 180


@dataclass
class ReferenceMap:
    """Bidirectional map between short reference tokens and database UUIDs."""

    claim_to_ref: dict[str, str] = field(default_factory=dict)
    edge_to_ref: dict[str, str] = field(default_factory=dict)
    evidence_to_ref: dict[str, str] = field(default_factory=dict)
    ref_to_claim: dict[str, str] = field(default_factory=dict)
    ref_to_edge: dict[str, str] = field(default_factory=dict)
    ref_to_evidence: dict[str, str] = field(default_factory=dict)

    def add_claim(self, claim_id: str) -> str:
        """A short reference token for a claim, stable within one generation.

        Tokens rather than UUIDs: a model asked to reproduce a UUID produces
        something UUID-shaped that does not exist, and a fabricated citation that
        parses is worse than one that fails.
        """
        if claim_id in self.claim_to_ref:
            return self.claim_to_ref[claim_id]
        ref = f"C{len(self.claim_to_ref) + 1}"
        self.claim_to_ref[claim_id] = ref
        self.ref_to_claim[ref] = claim_id
        return ref

    def add_edge(self, edge_id: str) -> str:
        """A short reference token for an edge. See `add_claim`."""
        if edge_id in self.edge_to_ref:
            return self.edge_to_ref[edge_id]
        ref = f"E{len(self.edge_to_ref) + 1}"
        self.edge_to_ref[edge_id] = ref
        self.ref_to_edge[ref] = edge_id
        return ref

    def add_evidence(self, evidence_id: str) -> str:
        """A short reference token for an evidence item. See `add_claim`."""
        if evidence_id in self.evidence_to_ref:
            return self.evidence_to_ref[evidence_id]
        ref = f"V{len(self.evidence_to_ref) + 1}"
        self.evidence_to_ref[evidence_id] = ref
        self.ref_to_evidence[ref] = evidence_id
        return ref


@dataclass
class GenerationContext:
    """Everything one LLM call needs, plus the metadata to audit it later."""

    user_prompt: str
    refs: ReferenceMap
    snapshot: GraphSnapshot
    selected_claim_ids: list[str]
    selected_edge_ids: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)
    #: Sample of project text used for language detection.
    language_sample: str = ""


# ---------------------------------------------------------------------------
# Subgraph selection
# ---------------------------------------------------------------------------


def build_nx(claims: list[Claim], edges: list[CausalEdge]) -> nx.DiGraph:
    """Build a DiGraph of the effective graph, honouring strength overrides."""
    g = nx.DiGraph()
    for claim in claims:
        g.add_node(str(claim.id), text=claim.text, claim_type=claim.claim_type)
    for edge in edges:
        src, tgt = str(edge.source_claim_id), str(edge.target_claim_id)
        if src in g and tgt in g:
            g.add_edge(
                src,
                tgt,
                edge_id=str(edge.id),
                strength=effective_strength(edge),
                evidence_score=edge.evidence_score,
            )
    return g


def _objective_keywords(objective: str | None) -> set[str]:
    """Content words from the stated decision, for ranking what to include."""
    if not objective:
        return set()
    return {
        token.lower().strip(".,;:!?()[]\"'")
        for token in objective.split()
        if len(token) > 3
    }


def score_claims(
    claims: list[Claim],
    edges: list[CausalEdge],
    graph: nx.DiGraph,
    *,
    decision_objective: str | None = None,
) -> dict[str, float]:
    """Score every claim by how much it matters to the decision.

    The weights are deliberately simple and additive — this is a *selection*
    heuristic for what to show the model, not a statistical claim about the
    graph. Human signals dominate: an element the user flagged as
    business-critical always outranks a merely well-connected one.
    """
    scores: dict[str, float] = {}
    keywords = _objective_keywords(decision_objective)

    try:
        critical_path = _critical_path(graph)
    except Exception:  # pragma: no cover - defensive
        critical_path = []
    critical_set = set(critical_path)

    # Evidence quality per claim, aggregated from incident edges.
    incident_evidence: dict[str, list[float]] = {}
    for edge in edges:
        for node_id in (str(edge.source_claim_id), str(edge.target_claim_id)):
            incident_evidence.setdefault(node_id, []).append(edge.evidence_score or 0.0)

    for claim in claims:
        cid = str(claim.id)
        score = 0.0

        if cid in critical_set:
            score += 3.0
        if graph.has_node(cid):
            if graph.in_degree(cid) == 0:
                score += 1.0  # root cause
            if graph.out_degree(cid) == 0:
                score += 1.5  # terminal outcome — where decisions land
            degree = graph.in_degree(cid) + graph.out_degree(cid)
            score += min(degree, 6) * 0.35
            if graph.in_degree(cid) > 1:
                score += 0.5  # convergence point

        status = getattr(claim, "review_status", "accepted") or "accepted"
        if status == "business_critical":
            score += 4.0
        elif status in ("uncertain", "needs_evidence"):
            score += 1.5
        if getattr(claim, "user_note", None):
            score += 1.5

        ev_scores = incident_evidence.get(cid, [])
        if ev_scores:
            score += max(ev_scores) * 1.0

        score += (claim.confidence or 0.0) * 0.5

        if keywords:
            text_tokens = {w.lower().strip(".,;:!?") for w in (claim.text or "").split()}
            overlap = len(keywords & text_tokens)
            score += min(overlap, 4) * 0.75

        scores[cid] = score

    return scores


def _critical_path(graph: nx.DiGraph) -> list[str]:
    """Longest strength×evidence weighted path, reusing Decision Studio's algorithm."""
    from decision_studio.graph.critical_path import find_critical_path

    if graph.number_of_edges() == 0:
        return []
    working = graph
    if not nx.is_directed_acyclic_graph(graph):
        working = graph.copy()
        # Drop the weakest edge of each cycle, same policy as the graph reader.
        for _ in range(working.number_of_edges()):
            if nx.is_directed_acyclic_graph(working):
                break
            try:
                cycle = nx.find_cycle(working)
            except nx.NetworkXError:
                break
            weakest = min(
                ((u, v) for u, v, *_ in cycle),
                key=lambda uv: working.edges[uv].get("strength", 0.5)
                * working.edges[uv].get("evidence_score", 0.5),
            )
            working.remove_edge(*weakest)
    return find_critical_path(working)


def select_subgraph(
    snapshot: GraphSnapshot,
    *,
    max_claims: int = DEFAULT_MAX_CLAIMS,
    max_edges: int = DEFAULT_MAX_EDGES,
) -> tuple[list[Claim], list[CausalEdge], dict[str, Any]]:
    """Pick the slice of the effective graph worth sending to the model.

    Returns ``(claims, edges, metrics)``. Small graphs are returned whole.
    """
    graph = build_nx(snapshot.claims, snapshot.edges)
    metrics: dict[str, Any] = {
        "total_claims": len(snapshot.claims),
        "total_edges": len(snapshot.edges),
        "roots": sum(1 for n in graph.nodes if graph.in_degree(n) == 0),
        "terminals": sum(1 for n in graph.nodes if graph.out_degree(n) == 0),
        "convergence_points": sum(1 for n in graph.nodes if graph.in_degree(n) > 1),
        "is_dag": nx.is_directed_acyclic_graph(graph) if graph.number_of_nodes() else True,
        "truncated": False,
    }
    critical_path = _critical_path(graph)
    metrics["critical_path_length"] = len(critical_path)

    if len(snapshot.claims) <= max_claims and len(snapshot.edges) <= max_edges:
        metrics["selected_claims"] = len(snapshot.claims)
        metrics["selected_edges"] = len(snapshot.edges)
        return snapshot.claims, snapshot.edges, metrics

    scores = score_claims(
        snapshot.claims,
        snapshot.edges,
        graph,
        decision_objective=getattr(snapshot.project, "decision_objective", None),
    )
    ranked = sorted(snapshot.claims, key=lambda c: scores.get(str(c.id), 0.0), reverse=True)
    keep_ids = {str(c.id) for c in ranked[:max_claims]}
    # Always keep the critical path intact, even if it costs a few slots.
    keep_ids.update(critical_path[: max_claims // 2])

    claims = [c for c in snapshot.claims if str(c.id) in keep_ids]
    edges = [
        e
        for e in snapshot.edges
        if str(e.source_claim_id) in keep_ids and str(e.target_claim_id) in keep_ids
    ]
    if len(edges) > max_edges:
        edges.sort(
            key=lambda e: effective_strength(e) * (e.evidence_score or 0.0), reverse=True
        )
        edges = edges[:max_edges]
        kept_edge_nodes = {str(e.source_claim_id) for e in edges} | {
            str(e.target_claim_id) for e in edges
        }
        claims = [c for c in claims if str(c.id) in kept_edge_nodes or True]

    metrics["truncated"] = True
    metrics["selected_claims"] = len(claims)
    metrics["selected_edges"] = len(edges)
    logger.info(
        "Graph selection: %d/%d claims, %d/%d edges kept for generation",
        len(claims), len(snapshot.claims), len(edges), len(snapshot.edges),
    )
    return claims, edges, metrics


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _format_evidence(
    evidences: list[Evidence], refs: ReferenceMap, max_per_type: int
) -> list[str]:
    """Supporting evidence first, then contradicting, each with its source."""
    lines: list[str] = []
    supporting = sorted(
        (e for e in evidences if e.evidence_type == "supporting"),
        key=lambda e: (e.credibility_score or 0) * (e.relevance_score or 0),
        reverse=True,
    )
    contradicting = sorted(
        (e for e in evidences if e.evidence_type == "contradicting"),
        key=lambda e: (e.credibility_score or 0) * (e.relevance_score or 0),
        reverse=True,
    )
    for group, label in ((supporting, "supports"), (contradicting, "contradicts")):
        for ev in group[:max_per_type]:
            ref = refs.add_evidence(str(ev.id))
            snippet = (ev.snippet or "")[:SNIPPET_LEN]
            if len(ev.snippet or "") > SNIPPET_LEN:
                snippet += "…"
            lines.append(
                f"      [{ref}] {label}: \"{snippet}\" — {ev.source_title} "
                f"(credibility={ev.credibility_score:.2f})"
            )
    return lines


def build_generation_context(
    snapshot: GraphSnapshot,
    *,
    previous_theories: list[Theory] | None = None,
    max_claims: int = DEFAULT_MAX_CLAIMS,
    max_edges: int = DEFAULT_MAX_EDGES,
    max_evidence_per_edge: int = DEFAULT_MAX_EVIDENCE_PER_EDGE,
    purpose: str = "theories",
) -> GenerationContext:
    """Render the effective graph plus human input into one prompt payload.

    Args:
        snapshot: the reviewed graph. Nothing outside it is ever rendered.
        clarification_answers: accepted answers to fold into the reasoning.
        previous_theories: current theories, so regeneration can explain deltas.
        open_questions: unanswered questions, so the model does not re-ask them.
        purpose: ``"theories"`` or ``"clarifications"``; only changes framing.
    """
    refs = ReferenceMap()
    claims, edges, metrics = select_subgraph(
        snapshot, max_claims=max_claims, max_edges=max_edges
    )

    for claim in claims:
        refs.add_claim(str(claim.id))

    project = snapshot.project
    lines: list[str] = []

    lines.append("# Decision context")
    lines.append(f"Project: {project.title}")
    if getattr(project, "decision_objective", None):
        lines.append(f"Decision objective: {project.decision_objective}")
    else:
        lines.append(
            "Decision objective: (not stated — treat the missing objective as a "
            "gap worth flagging)"
        )
    lines.append(f"Graph revision: {snapshot.graph_revision}")
    lines.append("")

    lines.append("# Graph metrics")
    lines.append(
        f"{metrics['selected_claims']} claims and {metrics['selected_edges']} edges "
        f"in scope (of {metrics['total_claims']} / {metrics['total_edges']} reviewed); "
        f"{metrics['roots']} root causes, {metrics['terminals']} terminal outcomes, "
        f"{metrics['convergence_points']} convergence points."
    )
    if metrics["truncated"]:
        lines.append(
            "Only the most decision-relevant part of the graph is shown. Do not "
            "assume the omitted part contradicts it."
        )
    lines.append("")

    lines.append("# Claims (cite by reference)")
    for claim in claims:
        ref = refs.claim_to_ref[str(claim.id)]
        flags: list[str] = []
        status = getattr(claim, "review_status", "accepted") or "accepted"
        if status != "accepted":
            flags.append(f"user_review={status}")
        if getattr(claim, "user_note", None):
            flags.append(f'user_note="{claim.user_note}"')
        flag_str = f" [{'; '.join(flags)}]" if flags else ""
        lines.append(
            f"- [{ref}] ({claim.claim_type}, confidence={claim.confidence:.2f}) "
            f"{claim.text}{flag_str}"
        )
    lines.append("")

    lines.append("# Causal edges (cite by reference)")
    if not edges:
        lines.append("(none — the reviewed graph has no causal links)")
    for edge in edges:
        src_ref = refs.claim_to_ref.get(str(edge.source_claim_id))
        tgt_ref = refs.claim_to_ref.get(str(edge.target_claim_id))
        if src_ref is None or tgt_ref is None:
            continue
        eref = refs.add_edge(str(edge.id))
        strength = effective_strength(edge)
        overridden = getattr(edge, "strength_override", None) is not None
        parts = [
            f"- [{eref}] {src_ref} -> {tgt_ref}: \"{edge.mechanism}\"",
            f"strength={strength:.2f}{' (HUMAN OVERRIDE)' if overridden else ''}",
            f"evidence={edge.evidence_score:.2f}",
            f"type={getattr(edge, 'causal_type', 'direct')}",
        ]
        status = getattr(edge, "review_status", "accepted") or "accepted"
        if status != "accepted":
            parts.append(f"user_review={status}")
        if getattr(edge, "user_note", None):
            parts.append(f'user_note="{edge.user_note}"')
        if getattr(edge, "statistical_validation", None):
            parts.append(f"statistical={edge.statistical_validation}")
        bias = getattr(edge, "bias_warnings", None)
        if bias:
            labels = [
                b.get("type", "?") if isinstance(b, dict) else str(b) for b in bias
            ]
            parts.append(f"bias={','.join(labels)}")
        lines.append(", ".join(parts))
        lines.extend(
            _format_evidence(
                snapshot.evidence_by_edge.get(str(edge.id), []), refs, max_evidence_per_edge
            )
        )
    lines.append("")

    reviewed = [
        c
        for c in claims
        if (getattr(c, "review_status", "accepted") or "accepted") != "accepted"
        or getattr(c, "user_note", None)
    ]
    reviewed_edges = [
        e
        for e in edges
        if (getattr(e, "review_status", "accepted") or "accepted") != "accepted"
        or getattr(e, "user_note", None)
        or getattr(e, "strength_override", None) is not None
    ]
    if reviewed or reviewed_edges:
        lines.append("# Human review (authoritative — overrides AI inference)")
        for claim in reviewed:
            ref = refs.claim_to_ref[str(claim.id)]
            note = f' note="{claim.user_note}"' if claim.user_note else ""
            lines.append(f"- {ref}: status={claim.review_status}{note}")
        for edge in reviewed_edges:
            ref = refs.edge_to_ref.get(str(edge.id))
            if ref is None:
                continue
            bits = [f"status={edge.review_status}"]
            if getattr(edge, "strength_override", None) is not None:
                bits.append(f"strength overridden to {edge.strength_override:.2f}")
            if edge.user_note:
                bits.append(f'note="{edge.user_note}"')
            lines.append(f"- {ref}: {', '.join(bits)}")
        lines.append(
            "Elements the user rejected have already been removed from this "
            "context and must not be reconstructed."
        )
        lines.append("")

    if previous_theories:
        lines.append("# Previous theories (for comparison)")
        for theory in previous_theories:
            key = str(theory.theory_key)
            edge_refs = [
                refs.edge_to_ref[str(link.edge_id)]
                for link in theory.edge_links
                if str(link.edge_id) in refs.edge_to_ref
            ]
            lines.append(
                f"- key={key} v{theory.version} status={theory.status} "
                f"confidence={theory.confidence:.2f} impact={theory.business_impact}"
            )
            lines.append(f"  title: {theory.title}")
            if edge_refs:
                lines.append(f"  built on edges: {', '.join(edge_refs)}")
        lines.append(
            "When a new theory continues one of these, set previous_theory_key to "
            "its key and explain in change_explanation what changed and why."
        )
        lines.append("")

    if purpose == "clarifications":
        lines.append(
            "# Task\nIdentify only the questions whose answers could materially "
            "change a theory's confidence, impact, causal chain or recommendation."
        )
    else:
        lines.append(
            "# Task\nGenerate the distinct, decision-relevant theories this graph "
            "supports. Cite only the references listed above."
        )

    language_sample = " ".join((c.text or "") for c in claims[:5]) or project.input_text[:500]

    metadata = {
        "graph_revision": snapshot.graph_revision,
        "graph_metrics": metrics,
        "claim_refs": len(refs.claim_to_ref),
        "edge_refs": len(refs.edge_to_ref),
        "evidence_refs": len(refs.evidence_to_ref),
        "previous_theory_keys": [str(t.theory_key) for t in (previous_theories or [])],
    }

    return GenerationContext(
        user_prompt="\n".join(lines),
        refs=refs,
        snapshot=snapshot,
        selected_claim_ids=[str(c.id) for c in claims],
        selected_edge_ids=[str(e.id) for e in edges],
        metadata=metadata,
        language_sample=language_sample,
    )
