"""How robust a comparison between two options is to the map's uncertainty.

The option comparison (graph/stability.compare_options) re-runs the causal map
with every link strength varied within its uncertainty. For two options A and B
and one success criterion, the share of those runs in which A comes out higher
than B is the raw material here. It says how often the *relative* comparison
survives parameter uncertainty — not how likely the world is to go either way.

## Thresholds (explicit, applied in this order)

1. ``|P(Y|A) - P(Y|B)| < NEGLIGIBLE_DIFFERENCE`` (2 points) → **no material
   difference**: the options imply the same for this criterion.
2. The higher option is higher in at least ``ROBUST_SHARE`` (80%) of runs →
   **robustly higher**.
3. At least ``LEANING_SHARE`` (60%) → **higher, but sensitive**: the direction
   holds more often than not, and plausible changes to the inputs reverse it.
4. Otherwise → **unresolved**: the map cannot say which is higher.

Across criteria, a pair is **mixed** when each option is (robustly or
sensitively) higher on at least one criterion: a trade-off the decider's
priorities have to settle.

The vocabulary is deliberately neutral. "Robustly higher on Y1" is a statement
about the model; "the right choice" is not something this module can say.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

NEGLIGIBLE_DIFFERENCE = 0.02
ROBUST_SHARE = 0.80
LEANING_SHARE = 0.60

ROBUST = "robust"
SENSITIVE = "sensitive"
UNRESOLVED = "unresolved"
NO_DIFFERENCE = "no_difference"

#: Pair-level summaries.
PAIR_CONSISTENT = "consistent"  # one option higher on every criterion that differs
PAIR_MIXED = "mixed"            # each option higher on at least one criterion
PAIR_UNRESOLVED = "unresolved"  # no criterion with a direction
PAIR_NO_DIFFERENCE = "no_difference"


@dataclass(frozen=True)
class Verdict:
    """One criterion, one pair of options."""

    verdict: str
    #: The option that is higher at the point estimate, or None when no difference.
    higher: str | None
    #: Share of runs in which ``higher`` came out higher (ties count half).
    share: float
    difference: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict, "higher": self.higher,
            "share": round(self.share, 3), "difference": round(self.difference, 4),
        }


def classify(a: str, b: str, value_a: float, value_b: float, share_a_higher: float) -> Verdict:
    """Classify A vs B on one criterion.

    Args:
        share_a_higher: share of simulation runs in which A was higher than B.
    """
    difference = value_a - value_b
    if abs(difference) < NEGLIGIBLE_DIFFERENCE:
        return Verdict(NO_DIFFERENCE, None, max(share_a_higher, 1 - share_a_higher), difference)
    higher, share = (a, share_a_higher) if difference > 0 else (b, 1.0 - share_a_higher)
    if share >= ROBUST_SHARE:
        verdict = ROBUST
    elif share >= LEANING_SHARE:
        verdict = SENSITIVE
    else:
        verdict = UNRESOLVED
    return Verdict(verdict, higher, share, difference)


def summarise_pair(a: str, b: str, verdicts: list[Verdict]) -> str:
    """One word for the pair across criteria."""
    directed = [v for v in verdicts if v.verdict in (ROBUST, SENSITIVE)]
    if not directed:
        if all(v.verdict == NO_DIFFERENCE for v in verdicts):
            return PAIR_NO_DIFFERENCE
        return PAIR_UNRESOLVED
    if {v.higher for v in directed} == {a, b}:
        return PAIR_MIXED
    return PAIR_CONSISTENT


def describe(verdict: Verdict, outcome_label: str, labels: dict[str, str]) -> str:
    """A sentence in neutral terms."""
    if verdict.verdict == NO_DIFFERENCE:
        return f"No material difference on {outcome_label}."
    name = labels.get(verdict.higher or "", verdict.higher or "")
    share = f"{round(verdict.share * 100)}%"
    if verdict.verdict == ROBUST:
        return (f"{name} is robustly higher on {outcome_label}: higher in {share} of "
                "simulations.")
    if verdict.verdict == SENSITIVE:
        return (f"{name} is higher on {outcome_label} in {share} of simulations — "
                "sensitive to the assumptions.")
    return (f"Unresolved on {outcome_label}: {name} is higher at the central estimate "
            f"but only in {share} of simulations.")
