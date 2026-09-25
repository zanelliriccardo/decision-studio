"""Derivation of an edge's operative weight from its two components.

A causal link carries two independent quantities that a single number cannot
hold:

* **effect** — how much gets through *if* the link is real
* **link_confidence** — how certain we are the link exists at all

A weak-but-certain link (effect 0.20, confidence 0.95) and a strong-but-
speculative one (effect 0.90, confidence 0.20) are opposite situations. Asked
for one blended "strength", a model averages them and both land near 0.5, at
which point they are indistinguishable — even though the first is something you
build on and the second is something you go and investigate.

Propagation still needs one number, so this module owns the collapse. Keeping it
in one place means the pipeline, the API and the graph maths can never disagree
about what `strength` means.
"""

from __future__ import annotations

from typing import Any

#: Floor on the derived weight. An edge worth storing is worth propagating a
#: little; a hard zero would silently delete it from every downstream belief.
MIN_STRENGTH = 0.10

#: Ceiling. Nothing inferred by a language model earns certainty.
MAX_STRENGTH = 0.95


def edge_strength(effect: float, link_confidence: float) -> float:
    """Collapse the two components into the operative propagation weight.

    Args:
        effect: size of the effect if the link is real, 0-1.
        link_confidence: certainty the link exists at all, 0-1.

    Returns:
        The product, clamped to ``[MIN_STRENGTH, MAX_STRENGTH]``.
    """
    product = _clamp01(effect) * _clamp01(link_confidence)
    return max(MIN_STRENGTH, min(MAX_STRENGTH, product))


def _clamp01(value: Any) -> float:
    """A float in [0, 1], or the fallback when the value is not a number."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.5
    if numeric != numeric:  # NaN
        return 0.5
    return max(0.0, min(1.0, numeric))


def split_legacy_strength(strength: float) -> tuple[float, float]:
    """Back-fill the two components for an edge that predates the split.

    Attributing the whole of a legacy ``strength`` to ``effect`` and leaving
    confidence at 1.0 reproduces the old number exactly, so migrating changes no
    existing output. It is deliberately not a guess at what the two values
    "really" were — we do not know, and inventing a split would be worse than
    admitting the edge has never been asked the second question.
    """
    return _clamp01(strength), 1.0


def inflation(
    author_effect: float | None,
    author_confidence: float | None,
    effect: float,
    link_confidence: float,
) -> float | None:
    """How much higher the proposing call scored this edge than a blind rater.

    Positive means the author over-scored its own edge. Returns None when the
    edge was never blind-scored, so callers can distinguish "no inflation" from
    "not measured".
    """
    if author_effect is None or author_confidence is None:
        return None
    return edge_strength(author_effect, author_confidence) - edge_strength(
        effect, link_confidence
    )
