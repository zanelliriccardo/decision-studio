"""Collapse the same fact stated in several places into one claim.

The problem this solves: three retrospective reports describe the same delay in
three vocabularies —

    "Vendor onboarding took eleven weeks against a four-week plan."
    "Supplier ramp-up ran nearly three months longer than scheduled."
    "We underestimated vendor onboarding duration by roughly 7 weeks."

— and the pipeline treats them as three independent facts, each shifting the
same belief. One observation ends up looking like overwhelming evidence. It is
the "a corpus is supplied, not sampled" caveat existing as an actual bug.

Lexical dedup cannot catch this: the three sentences above share no content
words at all (*vendor*/*supplier*, *onboarding*/*ramp-up*,
*eleven weeks*/*three months*/*7 weeks*), so token-overlap scores 0.00. Cosine
similarity on embeddings scores ~0.85. Decision Studio already computes claim
embeddings, so the better method is also the cheaper one here.

Independent corroboration is genuine evidence, so merged claims receive a
*bounded* bonus — three reports should outweigh one, but nowhere near threefold.

This runs after extraction and before evidence grounding, so grounding is not
spent three times retrieving sources for the same fact.
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

#: Cosine similarity above which two claims are treated as the same fact.
#: Deliberately higher than the extractor's own chunk-level threshold: merging
#: two genuinely different claims loses information that cannot be recovered,
#: while failing to merge merely leaves the pre-existing behaviour in place.
DEDUP_THRESHOLD = 0.86

#: Prior added per *additional* independent source, before the cap.
CORROBORATION_BONUS = 0.06

#: Ceiling on total corroboration lift. Without this, a repetitive corpus
#: reintroduces exactly the over-counting the module exists to prevent.
MAX_CORROBORATION_LIFT = 0.15


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    """Cosine similarity, returning 0.0 when either vector is missing."""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def corroboration_lift(source_count: int) -> float:
    """Prior bonus for a fact independently attested *source_count* times."""
    if source_count <= 1:
        return 0.0
    return min(MAX_CORROBORATION_LIFT, CORROBORATION_BONUS * (source_count - 1))


def _sources(claim: dict[str, Any]) -> set[str]:
    """Distinct source sentences backing a claim."""
    found = {
        s for s in [claim.get("source_sentence")] + list(claim.get("corroborated_by") or [])
        if s
    }
    return found


def dedup_claims(
    claims: list[dict[str, Any]],
    *,
    threshold: float = DEDUP_THRESHOLD,
    renumber: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Merge near-identical claims, keeping the best-supported one of each group.

    Claims are processed strongest-prior-first, so the surviving representative
    of a group is the one the extractor was most confident is true, rather than
    whichever happened to be extracted first.

    Claims without embeddings are never merged — a missing vector means "we do
    not know", and guessing would silently discard a distinct fact.

    Args:
        claims: extracted claim dicts. Each may carry an ``embedding``.
        threshold: cosine similarity above which two claims are the same fact.
        renumber: renumber ``order_index`` densely. Leave False when the caller
            maps claims back to already-persisted rows by their original index —
            which the orchestrator does.

    Returns:
        ``(kept_claims, report)``. Kept claims gain ``corroborated_by`` and
        ``duplicate_count``, and have their ``prior`` lifted for independent
        corroboration. ``order_index`` is renumbered so downstream index-based
        edge references stay valid.
    """
    if not claims:
        return [], {"input": 0, "kept": 0, "merged": 0, "groups": []}

    ordered = sorted(
        claims,
        key=lambda c: (c.get("prior", c.get("confidence", 0.5)), c.get("confidence", 0.5)),
        reverse=True,
    )

    groups: list[dict[str, Any]] = []
    for claim in ordered:
        embedding = claim.get("embedding")
        placed = False

        if embedding:
            for group in groups:
                similarity = cosine(embedding, group["lead"].get("embedding"))
                if similarity >= threshold:
                    group["members"].append(claim)
                    group["similarities"].append(round(similarity, 3))
                    placed = True
                    break

        if not placed:
            groups.append({"lead": claim, "members": [], "similarities": []})

    kept: list[dict[str, Any]] = []
    report_groups: list[dict[str, Any]] = []

    for group in groups:
        lead = dict(group["lead"])
        members = group["members"]

        if members:
            sources: set[str] = set()
            for member in [group["lead"], *members]:
                sources |= _sources(member)
            # The lead's own sentence stays in source_sentence; the rest are
            # recorded as corroboration so provenance survives the merge.
            others = sorted(sources - {lead.get("source_sentence")})

            lead["corroborated_by"] = others or None
            lead["duplicate_count"] = len(members)

            base_prior = lead.get("prior", lead.get("confidence", 0.5))
            lift = corroboration_lift(len(sources))
            lead["prior"] = min(0.99, base_prior + lift)

            report_groups.append({
                "kept": lead["text"],
                "merged": [m["text"] for m in members],
                "similarities": group["similarities"],
                "prior_before": round(base_prior, 3),
                "prior_after": round(lead["prior"], 3),
            })

        kept.append(lead)

    # Restore the original narrative ordering. order_index is left alone by
    # default: the orchestrator uses it to find the already-saved DB row, and
    # renumbering here would point every claim at the wrong one.
    kept.sort(key=lambda c: c.get("order_index", 0))
    if renumber:
        for index, claim in enumerate(kept):
            claim["order_index"] = index

    merged_count = len(claims) - len(kept)
    if merged_count:
        logger.info(
            "Claim dedup: %d claims -> %d (%d merged as restatements)",
            len(claims), len(kept), merged_count,
        )

    kept_indices = {c.get("order_index") for c in kept}
    return kept, {
        "input": len(claims),
        "kept": len(kept),
        "merged": merged_count,
        "groups": report_groups,
        "removed_order_indices": sorted(
            c.get("order_index") for c in claims
            if c.get("order_index") not in kept_indices
        ),
    }
