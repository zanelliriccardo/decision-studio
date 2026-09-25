"""Adjusting a claim's truth prior for who is asserting it.

The extractor is asked for a prior directly, and it does weigh source type. But
leaving the whole judgement inside one free-form estimate makes it invisible and
untestable: nobody can see whether the model actually discounted the vendor's
promise, or say by how much.

So the interest judgement is elicited as a separate categorical field and applied
here, as an explicit, auditable adjustment. The model still supplies the base
estimate; this module records what was done to it and why, which is what makes it
reviewable.

The direction comes from a long-standing evidential principle: a statement
against the speaker's own interest is unusually credible, because there is no
motive to make it. The converse is weaker but real — an assurance from someone
who benefits from being believed carries less than its confident tone suggests.

The magnitudes are deliberately modest. They nudge; they do not decide. A vendor
can be both interested and right.
"""

from __future__ import annotations

import logging
from typing import Any, NamedTuple

logger = logging.getLogger(__name__)

VALID_INTERESTS: tuple[str, ...] = (
    "against_interest",
    "disinterested",
    "interested",
    "unknown",
)

#: Additive adjustments to the truth prior, by who is speaking.
#:
#: Asymmetric on purpose: an admission against interest is strong evidence, while
#: an interested assurance is merely *weak* evidence rather than counter-evidence
#: — people with a stake are often telling the truth.
INTEREST_ADJUSTMENT: dict[str, float] = {
    "against_interest": +0.15,
    "disinterested": 0.0,
    "interested": -0.10,
    "unknown": 0.0,
}

#: Adjustment never pushes a prior past these, so no claim becomes certain or
#: impossible purely because of who said it.
MIN_PRIOR = 0.05
MAX_PRIOR = 0.95


class PriorAdjustment(NamedTuple):
    """The result of adjusting a prior, kept auditable."""

    prior: float
    delta: float
    reason: str | None

    @property
    def was_adjusted(self) -> bool:
        """Whether the author's interest moved this claim's prior."""
        return abs(self.delta) > 1e-9


def normalize_interest(value: Any) -> str:
    """Coerce an interest label, defaulting to the no-adjustment case."""
    if isinstance(value, str) and value.strip().lower() in VALID_INTERESTS:
        return value.strip().lower()
    return "unknown"


def adjust_prior(
    prior: float,
    source_interest: Any,
    source_role: str | None = None,
) -> PriorAdjustment:
    """Nudge a truth prior for the asserting party's stake in it.

    Args:
        prior: the extractor's estimate that the claim is true, 0-1.
        source_interest: one of VALID_INTERESTS.
        source_role: who is asserting it, for the explanation.

    Returns:
        The adjusted prior, the delta actually applied (after clamping), and a
        human-readable reason, or None when nothing was done.
    """
    try:
        base = max(0.0, min(1.0, float(prior)))
    except (TypeError, ValueError):
        base = 0.5

    interest = normalize_interest(source_interest)
    nominal = INTEREST_ADJUSTMENT[interest]
    if nominal == 0.0:
        return PriorAdjustment(base, 0.0, None)

    adjusted = max(MIN_PRIOR, min(MAX_PRIOR, base + nominal))
    applied = adjusted - base
    if abs(applied) < 1e-9:
        return PriorAdjustment(base, 0.0, None)

    who = source_role or "the source"
    if interest == "against_interest":
        reason = (
            f"Raised: {who} is conceding something that costs them, which is "
            f"unusually credible testimony."
        )
    else:
        reason = (
            f"Lowered: {who} benefits from this being believed, so the assurance "
            f"carries less than its tone suggests."
        )
    return PriorAdjustment(adjusted, applied, reason)


def apply_to_claims(claims: list[dict[str, Any]]) -> dict[str, Any]:
    """Adjust every claim's prior in place, and report what changed.

    Pure over the list: no I/O, so the policy can be exercised directly in tests.
    """
    raised = 0
    lowered = 0

    for claim in claims:
        result = adjust_prior(
            claim.get("prior", claim.get("confidence", 0.5)),
            claim.get("source_interest"),
            claim.get("source_role"),
        )
        if not result.was_adjusted:
            continue
        claim["prior"] = result.prior
        claim["prior_adjustment_reason"] = result.reason
        if result.delta > 0:
            raised += 1
        else:
            lowered += 1

    if raised or lowered:
        logger.info(
            "Source interest: %d prior(s) raised (against interest), %d lowered "
            "(interested party)",
            raised, lowered,
        )
    return {"raised": raised, "lowered": lowered, "total": len(claims)}
