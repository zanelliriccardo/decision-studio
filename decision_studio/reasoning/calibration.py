"""Verbal confidence bands, because the decimals were never earned.

Nothing in Decision Studio has ever been calibrated. Nobody has checked whether claims
scored 0.72 are true about 72% of the time, and for one-off strategic decisions
nobody can — there is no repeated trial to score against.

Rendering ``0.72`` therefore asserts a resolution the pipeline does not possess.
It is the difference between pacing out a room and reporting 4.37 metres. The
number is not wrong so much as *over-specified*, and over-specification is
precisely what makes a reader trust it more than they should.

So the UI shows a band. The underlying float is kept — it still orders things
correctly, and ordering is what it is good for — but the second decimal stops
being presented as if it meant something.

The vocabulary follows the IPCC's calibrated-language convention: fixed phrases
mapped to fixed ranges, so "likely" means the same thing every time it appears.
"""

from __future__ import annotations

from typing import NamedTuple


class Band(NamedTuple):
    """A confidence band: a stable label plus the range it covers."""

    key: str
    low: float
    high: float


#: Ordered low to high. Ranges are contiguous and cover [0, 1].
BANDS: tuple[Band, ...] = (
    Band("very_low", 0.00, 0.20),
    Band("low", 0.20, 0.40),
    Band("moderate", 0.40, 0.60),
    Band("high", 0.60, 0.80),
    Band("very_high", 0.80, 1.01),
)

#: Bands wide enough that a difference between them is not noise.
IMPACT_BANDS: tuple[str, ...] = ("low", "medium", "high", "critical")


def band(value: float | None) -> str:
    """Map a 0-1 score to its band key.

    Returns ``"unknown"`` for a missing value rather than guessing a middle
    band, so "we did not compute this" stays distinguishable from "this is
    moderate".
    """
    if value is None:
        return "unknown"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "unknown"
    numeric = max(0.0, min(1.0, numeric))
    for entry in BANDS:
        if entry.low <= numeric < entry.high:
            return entry.key
    return BANDS[-1].key


# DEAD-CODE-CANDIDATE DC-19: no callers. See docs/DEAD_CODE_REPORT.md
def band_range(value: float | None) -> tuple[float, float] | None:
    """The range a value's band covers, for rendering a bar rather than a point."""
    key = band(value)
    for entry in BANDS:
        if entry.key == key:
            return (entry.low, min(entry.high, 1.0))
    return None


# DEAD-CODE-CANDIDATE DC-19: no callers. See docs/DEAD_CODE_REPORT.md
def round_for_display(value: float | None) -> float | None:
    """One decimal place. Two implies a resolution nothing here has.

    Use this anywhere a number must still be shown numerically -- an interval
    bound, say -- so the false precision is removed consistently rather than
    per-component.
    """
    if value is None:
        return None
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


# DEAD-CODE-CANDIDATE DC-19: no callers. See docs/DEAD_CODE_REPORT.md
def interval_is_informative(low: float | None, high: float | None) -> bool:
    """False when an interval is so wide it says nothing.

    A band spanning more than 0.6 of the range covers most possible answers.
    Showing it as a finding invites the reader to anchor on its midpoint, which
    is exactly what the width is warning against.
    """
    if low is None or high is None:
        return False
    return (high - low) <= 0.6
