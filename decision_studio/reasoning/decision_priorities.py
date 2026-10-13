"""Decision priorities: how much each success criterion matters to the decider.

The causal map says what each option implies for each success criterion. It
cannot say which criterion matters more: shipping on the date or keeping the
team intact is a judgement only the decider can make. This module holds that
judgement and turns it into a *weighted view* — never into a recommendation.

## The mapping (deterministic, and shown to the user)

=============  ======  ==========================================
Importance     Weight  Meaning
=============  ======  ==========================================
critical       8       must not be traded away lightly
high           4       half as important as a critical criterion
medium         2       the default when nothing has been set
low            1       matters, but gives way to the others
none           0       left out of the weighted view entirely
=============  ======  ==========================================

Each step doubles the weight, so "critical" counts as much as two "high"
criteria. Weights are normalised to sum to 1 over the criteria in the view.

## The weighted view

For option ``o``: ``view(o) = Σ_i w_i · P(Y_i | do(o))`` with normalised
weights ``w_i``. Each term is that criterion's *contribution*. The result is on
a 0–1 scale for display as 0–100 points, and it is **not a probability**: it is
the option-implied outcome probabilities averaged with the decider's own
priorities. Two different sets of priorities give two different views of the
same map, which is the point.

Priorities are stored on the project (``project.outcome_priorities``), apart
from the anchor, so changing them never touches the causal graph and never
re-scores a claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

IMPORTANCE_WEIGHTS: dict[str, float] = {
    "critical": 8.0,
    "high": 4.0,
    "medium": 2.0,
    "low": 1.0,
    "none": 0.0,
}
IMPORTANCE_LEVELS = tuple(IMPORTANCE_WEIGHTS)
DEFAULT_IMPORTANCE = "medium"


@dataclass(frozen=True)
class Priority:
    key: str
    label: str
    importance: str
    weight: float
    #: Share of the total weight, 0-1. Zero when the criterion is left out.
    normalized: float
    #: True when the decider has not set it and the default applies.
    is_default: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "label": self.label, "importance": self.importance,
            "weight": self.weight, "normalized_weight": round(self.normalized, 4),
            "is_default": self.is_default,
        }


def clean_priorities(raw: Any, outcome_keys: Iterable[str] | None = None) -> dict[str, str]:
    """Stored priorities, keeping only known levels (and known outcomes, when given)."""
    if not isinstance(raw, Mapping):
        return {}
    keys = set(outcome_keys) if outcome_keys is not None else None
    return {
        str(k): str(v) for k, v in raw.items()
        if str(v) in IMPORTANCE_WEIGHTS and (keys is None or str(k) in keys)
    }


def resolve(outcomes: list[tuple[str, str]], stored: Mapping[str, str] | None) -> list[Priority]:
    """Every success criterion with its importance, weight and normalised share.

    Args:
        outcomes: (key, label) in anchor order.
        stored: what the decider set, by outcome key. Missing means the default.
    """
    stored = clean_priorities(stored or {})
    raw = []
    for key, label in outcomes:
        importance = stored.get(key, DEFAULT_IMPORTANCE)
        raw.append((key, label, importance, IMPORTANCE_WEIGHTS[importance], key not in stored))
    total = sum(weight for *_, weight, _ in raw)
    return [
        Priority(key, label, importance, weight, weight / total if total > 0 else 0.0, is_default)
        for key, label, importance, weight, is_default in raw
    ]


def normalized_weights(priorities: list[Priority]) -> dict[str, float]:
    """Outcome key -> normalised weight, for the criteria that count (weight > 0)."""
    return {p.key: p.normalized for p in priorities if p.normalized > 0}


@dataclass(frozen=True)
class WeightedView:
    #: 0-1; shown as points out of 100. Not a probability.
    score: float
    #: Outcome key -> weight × option-implied probability.
    contributions: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 4),
            "contributions": {k: round(v, 4) for k, v in self.contributions.items()},
        }


def weighted_view(values: Mapping[str, float], weights: Mapping[str, float]) -> WeightedView | None:
    """The weighted view of one option, or None when no criterion carries weight.

    Args:
        values: outcome key -> option-implied probability.
        weights: outcome key -> normalised weight (from ``normalized_weights``).
    """
    usable = {k: w for k, w in weights.items() if w > 0 and k in values}
    total = sum(usable.values())
    if total <= 0:
        return None
    contributions = {k: (w / total) * float(values[k]) for k, w in usable.items()}
    return WeightedView(score=sum(contributions.values()), contributions=contributions)
