"""Re-score proposed causal links with a rater that cannot see who proposed them.

The pool is built from every edge in the graph, shuffled, and stripped of
identifiers before it reaches the model. The rater sees only claim pairs and
mechanisms, in an order that carries no signal, so it cannot reward an edge for
belonging to a well-argued chain.

The author's original scores are preserved on the edge rather than discarded.
The gap between them is a useful signal in its own right: a stage whose own
scores run consistently above blind is over-claiming, and that is worth
surfacing even though nothing currently acts on it.

Temperature is held very low. Scoring wants reproducibility, not range — the
opposite of generation.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from decision_studio.graph.edge_weight import edge_strength
from decision_studio.llm.client import LLMClient
from decision_studio.llm.prompts.blind_scoring import BLIND_SCORING_SCHEMA, BLIND_SCORING_SYSTEM

logger = logging.getLogger(__name__)

#: Edges rated per call. Large enough to amortise the system prompt, small
#: enough that a malformed response costs little.
BATCH_SIZE = 8

#: Scoring should be as reproducible as we can make it.
TEMPERATURE = 0.1

#: Fixed seed: the shuffle must not be a source of run-to-run variation, or
#: re-running the pipeline on unchanged input would produce different graphs.
SHUFFLE_SEED = 20260725

#: Mechanism text longer than this is truncated. A rater should not be able to
#: infer importance from sheer length.
MAX_MECHANISM_CHARS = 400


class BlindRescorer:
    """Second-pass scorer for causal edges."""

    def __init__(self, llm: LLMClient, concurrency: int = 3) -> None:
        """Hold the model client, and cap how many batches run at once."""
        self._llm = llm
        self._semaphore = asyncio.Semaphore(concurrency)

    async def rescore(
        self,
        edges: list[dict[str, Any]],
        claims: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Re-score every edge, preserving the author's original numbers.

        Args:
            edges: edge dicts carrying ``source_idx``, ``target_idx``,
                ``mechanism`` and the author's ``effect`` / ``link_confidence``.
            claims: claim dicts, indexed by the edge ``*_idx`` fields.

        Returns:
            ``(edges, report)``. Edges are mutated in place and also returned.
            The report carries the inflation measurement.
        """
        if not edges:
            return edges, {"rescored": 0, "mean_inflation": None}

        # Record what the proposing call thought before anything overwrites it.
        for edge in edges:
            edge.setdefault("author_effect", edge.get("effect", edge.get("strength", 0.5)))
            edge.setdefault("author_confidence", edge.get("link_confidence", 1.0))

        pool = list(enumerate(edges))
        random.Random(SHUFFLE_SEED).shuffle(pool)

        batches = [pool[i : i + BATCH_SIZE] for i in range(0, len(pool), BATCH_SIZE)]
        results = await asyncio.gather(
            *(self._rate_batch(batch, claims) for batch in batches),
            return_exceptions=True,
        )

        rescored = 0
        for batch, outcome in zip(batches, results):
            if isinstance(outcome, Exception):
                # A failed batch keeps its author scores. Degrading to the old
                # behaviour is safer than dropping edges or zeroing them.
                logger.warning("Blind scoring batch failed, keeping author scores: %s", outcome)
                continue
            for position, rating in outcome.items():
                if position >= len(batch):
                    continue
                _, edge = batch[position]
                edge["effect"] = _clamp(rating["effect"])
                edge["link_confidence"] = _clamp(rating["confidence"])
                edge["strength"] = edge_strength(edge["effect"], edge["link_confidence"])
                if rating.get("note"):
                    edge["blind_note"] = rating["note"]
                edge["blind_scored"] = True
                rescored += 1

        report = self._inflation_report(edges)
        logger.info(
            "Blind rescoring: %d/%d edges rescored, mean inflation %s",
            rescored, len(edges), report["mean_inflation"],
        )
        return edges, report

    async def _rate_batch(
        self,
        batch: list[tuple[int, dict[str, Any]]],
        claims: list[dict[str, Any]],
    ) -> dict[int, dict[str, Any]]:
        """Rate one batch. Returns {position_in_batch: rating}."""
        lines: list[str] = []
        for position, (_, edge) in enumerate(batch):
            source = _claim_text(claims, edge.get("source_idx"))
            target = _claim_text(claims, edge.get("target_idx"))
            mechanism = (edge.get("mechanism") or "")[:MAX_MECHANISM_CHARS]
            lines.append(
                f"ITEM {position}\n"
                f"CAUSE: {source}\n"
                f"EFFECT: {target}\n"
                f"PROPOSED MECHANISM: {mechanism}"
            )

        async with self._semaphore:
            payload = await self._llm.complete_json(
                system=BLIND_SCORING_SYSTEM,
                user="\n\n".join(lines),
                schema=BLIND_SCORING_SCHEMA,
                max_tokens=2048,
                temperature=TEMPERATURE,
            )

        ratings: dict[int, dict[str, Any]] = {}
        for entry in payload.get("ratings") or []:
            if not isinstance(entry, dict):
                continue
            try:
                index = int(entry["index"])
            except (KeyError, TypeError, ValueError):
                continue
            if 0 <= index < len(batch):
                ratings[index] = entry
        return ratings

    @staticmethod
    def _inflation_report(edges: list[dict[str, Any]]) -> dict[str, Any]:
        """How much higher authors scored their own edges than the blind pass."""
        deltas = [
            edge_strength(edge["author_effect"], edge["author_confidence"])
            - edge_strength(edge["effect"], edge["link_confidence"])
            for edge in edges
            if edge.get("blind_scored") and edge.get("author_effect") is not None
        ]
        if not deltas:
            return {"rescored": 0, "mean_inflation": None, "max_inflation": None}
        return {
            "rescored": len(deltas),
            "mean_inflation": round(sum(deltas) / len(deltas), 3),
            "max_inflation": round(max(deltas), 3),
            "inflated_edge_count": sum(1 for d in deltas if d > 0.1),
        }


def _claim_text(claims: list[dict[str, Any]], index: Any) -> str:
    """A claim's text by index, or an empty string when the index is bad."""
    try:
        return claims[int(index)]["text"]
    except (TypeError, ValueError, IndexError, KeyError):
        return "(unknown claim)"


def _clamp(value: Any) -> float:
    """A float in [0, 1], or the fallback when the value is not a number."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, numeric))
