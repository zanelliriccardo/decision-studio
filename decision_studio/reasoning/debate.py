"""Structural comparison of two theories — computed, not generated.

This runs *before* any model is called, and in one of the three cases it means
no model is called at all.

The reasoning: overlap between two theories is a fact about the graph. Both
theories carry normalized links to the claims and edges they rest on, so the
shared and divergent sets are set arithmetic. Asking a model to estimate
something the database already knows would introduce error for no benefit, and
would make the result unauditable — the number would be a judgement rather than
a measurement.

The classification into three relations does most of the useful work:

* **same_story** — the two rest on substantially the same causal path. They are
  one theory in two wordings. Comparing them is theatre, so the debate stops
  here and the model is never invoked. (It also flags a problem upstream: the
  generation validator drops duplicates above 0.8 edge overlap, so a surviving
  pair suggests that threshold needs tuning.)
* **orthogonal** — they share almost nothing. They are not alternatives; both
  may hold. This is the case a ranked list actively hides, because presenting
  two theories as first and second implies choosing between them.
* **competing** — genuine disagreement. Only here is it worth asking what
  separates them.

Everything here is pure: no database, no provider, so the classification can be
exercised directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

#: Edge overlap at or above which two theories are one theory.
SAME_STORY_THRESHOLD = 0.70

#: Edge overlap at or below which they are not really in competition.
ORTHOGONAL_THRESHOLD = 0.20

RELATIONS = ("same_story", "competing", "orthogonal")


@dataclass
class StructuralComparison:
    """What set arithmetic alone can establish about two theories."""

    overlap_jaccard: float
    relation: str
    shared_claim_ids: list[str] = field(default_factory=list)
    shared_edge_ids: list[str] = field(default_factory=list)
    divergent_claim_ids: list[str] = field(default_factory=list)
    divergent_edge_ids: list[str] = field(default_factory=list)
    #: Claims both theories reach but by different routes — usually the outcome.
    shared_endpoints: list[str] = field(default_factory=list)

    @property
    def needs_model(self) -> bool:
        """Whether asking a model anything about this pair is worth the call."""
        return self.relation != "same_story"

    @property
    def both_possible(self) -> bool:
        """Orthogonal theories are not alternatives; both may hold at once."""
        return self.relation == "orthogonal"

    def persisted_fields(self) -> dict[str, Any]:
        """Only what TheoryDebate stores.

        ``shared_endpoints`` is derived from the other two sets, so it is
        computed for the caller rather than stored -- a denormalized copy would
        be one more thing that can drift.
        """
        return {
            "overlap_jaccard": round(self.overlap_jaccard, 3),
            "relation": self.relation,
            "shared_claim_ids": self.shared_claim_ids,
            "shared_edge_ids": self.shared_edge_ids,
            "divergent_claim_ids": self.divergent_claim_ids,
            "divergent_edge_ids": self.divergent_edge_ids,
        }

    def as_dict(self) -> dict[str, Any]:
        """The comparison, including the fields not persisted."""
        return {**self.persisted_fields(), "shared_endpoints": self.shared_endpoints}


def jaccard(a: set[str], b: set[str]) -> float:
    """Overlap of two sets, 0-1.

    Two theories that both rest on nothing overlap in nothing: returning 1.0 for
    the empty case would classify every unsupported pair as the same story.
    """
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def classify(overlap: float) -> str:
    """Map edge overlap to a relation."""
    if overlap >= SAME_STORY_THRESHOLD:
        return "same_story"
    if overlap <= ORTHOGONAL_THRESHOLD:
        return "orthogonal"
    return "competing"


def _ids(links: Iterable[Any], attribute: str) -> set[str]:
    """The ids on one side of a link collection, as strings."""
    return {str(getattr(link, attribute)) for link in links or []}


def compare_structure(theory_a: Any, theory_b: Any) -> StructuralComparison:
    """Compare two theories by the graph elements they rest on.

    Overlap is measured on **edges**, not claims. Two theories about the same
    outcome necessarily share its claim, and often share the root cause too, so
    claim overlap would make almost every pair look like the same story. What
    distinguishes a causal explanation is the path, and the path is the edges.

    Args:
        theory_a, theory_b: objects exposing ``claim_links`` and ``edge_links``.

    Returns:
        The comparison, including which relation the pair falls into.
    """
    claims_a = _ids(getattr(theory_a, "claim_links", []), "claim_id")
    claims_b = _ids(getattr(theory_b, "claim_links", []), "claim_id")
    edges_a = _ids(getattr(theory_a, "edge_links", []), "edge_id")
    edges_b = _ids(getattr(theory_b, "edge_links", []), "edge_id")

    overlap = jaccard(edges_a, edges_b)

    shared_claims = claims_a & claims_b
    shared_edges = edges_a & edges_b

    # Claims both theories reach without sharing the route there. Usually the
    # outcome, and worth separating: two explanations converging on the same
    # consequence is exactly the orthogonal case.
    endpoints = shared_claims if not shared_edges else set()

    return StructuralComparison(
        overlap_jaccard=overlap,
        relation=classify(overlap),
        shared_claim_ids=sorted(shared_claims),
        shared_edge_ids=sorted(shared_edges),
        divergent_claim_ids=sorted(claims_a ^ claims_b),
        divergent_edge_ids=sorted(edges_a ^ edges_b),
        shared_endpoints=sorted(endpoints),
    )


def relation_explanation(comparison: StructuralComparison) -> str:
    """A sentence the user can act on, without a model call."""
    percent = f"{comparison.overlap_jaccard:.0%}"
    if comparison.relation == "same_story":
        return (
            f"These rest on the same causal path ({percent} of their links are "
            f"shared). They are one theory stated two ways, not alternatives."
        )
    if comparison.relation == "orthogonal":
        if comparison.shared_endpoints:
            return (
                "These share no causal path but reach the same outcome. They are "
                "not alternatives: both may hold, and if both do the exposure is "
                "greater than either suggests on its own."
            )
        return (
            "These share no causal path and no outcome. They are about different "
            "things and do not compete."
        )
    return (
        f"These agree on part of the chain ({percent} of links shared) and part "
        f"company after that. The disagreement is real."
    )


def select_pairs(
    theories: list[Any], *, max_theories: int = 4
) -> list[tuple[Any, Any]]:
    """Pick which theories to compare.

    Every pair among the top few, ranked by adjusted score. Capped because the
    pair count grows quadratically and the marginal value falls off fast — a
    comparison between the fifth and sixth theory rarely changes a decision.
    """
    ranked = sorted(
        theories,
        key=lambda t: (
            getattr(t, "adjusted_score", None)
            if getattr(t, "adjusted_score", None) is not None
            else getattr(t, "confidence", 0.0)
        ),
        reverse=True,
    )[:max_theories]

    return [
        (ranked[i], ranked[j])
        for i in range(len(ranked))
        for j in range(i + 1, len(ranked))
    ]
