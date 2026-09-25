"""The decision anchor: the decision, stated so the pipeline can steer by it.

## Why this exists

The graph used to be built without the decision. Extraction was told to extract
every claim; causal inference asked each root cause what it caused; the stated
objective was first read by theory generation, after the graph was finished.
The result was a faithful map of the documents, most of it unrelated to the
choice being made, which the theories then had to bridge.

Aristotle (Bocconi's theory-based decision tool) works the other way round: a
Problem Agent first fixes *what success looks like, by when, under which
constraints*, and theories are causal maps from attributes to that success. The
anchor is that problem statement, in the smallest form that changes the graph:

* **options** give claims something to bear on — a claim can be a property of
  one option and irrelevant to another;
* **outcomes** become nodes in the graph, so causal inference has a destination
  and "how close is this to the decision" becomes a graph distance rather than a
  keyword overlap.

## What it deliberately is not

Not a questionnaire. Three question systems were built here and removed because
they stood between someone who had uploaded documents and the analysis they
wanted (HANDOVER §4.9). The anchor is drafted by the model from the one-line
objective and the material; the user may correct it, and need not.

Never invented from nothing. Without a stated objective there is no anchor and
the pipeline runs exactly as before: a model asked to guess the decision from
the documents would produce a plausible one, and every downstream score would
then measure relevance to a decision nobody is making.

Options are not graph nodes. A choice has no probability, and putting mutually
exclusive options into noisy-OR propagation would assert a belief about which
one the user will pick. They are referenced by ``bears_on`` instead.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from decision_studio.llm.client import LLMClient
from decision_studio.llm.prompts.decision_anchor import (
    ANCHOR_DRAFT_SCHEMA,
    ANCHOR_DRAFT_SYSTEM,
    RELEVANCE_SCHEMA,
    RELEVANCE_SYSTEM,
    ROLE_ENUM,
)

logger = logging.getLogger(__name__)

#: Caps. An anchor with ten options is a brainstorm, not a decision, and every
#: item here is rendered into every extraction chunk.
MAX_OPTIONS = 4
MAX_OUTCOMES = 3
MAX_CONSTRAINTS = 5
MAX_LABEL_CHARS = 200
MAX_DECISION_CHARS = 2000

STATUS_DRAFT = "draft"
STATUS_CONFIRMED = "confirmed"

#: Marks the graph nodes created from anchor outcomes.
ORIGIN_FRAME = "frame"
ROLE_OUTCOME = "outcome"
VALID_ROLES = tuple(ROLE_ENUM)

#: Claims per relevance-scoring call. Large enough that re-scoring a 476-claim
#: project is about a dozen calls; small enough that the answer fits the output
#: budget with a sentence of reasoning per claim.
RELEVANCE_BATCH = 40
_RELEVANCE_CONCURRENCY = 4

#: Material shown to the drafting call. The anchor needs the gist, not every
#: page, and this call sits in front of the user.
MAX_DRAFT_MATERIAL_CHARS = 12000

_KEY_PATTERN = {"options": re.compile(r"^O\d+$"), "outcomes": re.compile(r"^Y\d+$")}


def _text(value: Any, limit: int = MAX_LABEL_CHARS) -> str:
    """A trimmed, bounded string, or empty."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _keyed(
    items: Any,
    prefix: str,
    kind: str,
    limit: int,
    with_measure: bool,
    reserved: set[str] = frozenset(),
) -> list[dict[str, str]]:
    """Clean a list of options or outcomes, keeping valid keys and filling gaps.

    Keys are preserved when they are valid and unique, because claims refer to
    them in ``bears_on``: renumbering after the user deletes O2 would silently
    re-point every claim that bore on O3.
    """
    if not isinstance(items, list):
        return []
    cleaned: list[dict[str, str]] = []
    used: set[str] = set()
    for item in items:
        if isinstance(item, str):
            item = {"label": item}
        if not isinstance(item, dict):
            continue
        label = _text(item.get("label"))
        if not label:
            continue
        key = item.get("key") if isinstance(item.get("key"), str) else ""
        entry = {"key": key if _KEY_PATTERN[kind].match(key or "") and key not in used else "",
                 "label": label}
        if with_measure:
            entry["measure"] = _text(item.get("measure"))
        if entry["key"]:
            used.add(entry["key"])
        cleaned.append(entry)
        if len(cleaned) >= limit:
            break

    # New keys continue past the highest key ever used rather than filling
    # gaps: a gap is a deleted item, and reusing its key would hand the new item
    # every claim that bore on the old one — and, for an outcome, its graph node
    # and every link into it. ``reserved`` carries keys used before this edit,
    # which the submitted anchor no longer shows.
    known = used | {k for k in reserved if _KEY_PATTERN[kind].match(k)}
    counter = max((int(k[1:]) for k in known), default=0) + 1
    for entry in cleaned:
        if entry["key"]:
            continue
        entry["key"] = f"{prefix}{counter}"
        used.add(entry["key"])
        counter += 1
    return cleaned


def normalise_anchor(
    raw: Any,
    *,
    status: str | None = None,
    reserved: set[str] = frozenset(),
) -> dict[str, Any] | None:
    """Validate and clean an anchor from the model or the user.

    ``reserved`` holds keys already used by this project — its previous anchor
    and its outcome nodes — so a new item never inherits a deleted one's key.

    Returns None when there is no decision: an anchor without one steers towards
    nothing, and storing it would make an empty frame look like a stated one.
    """
    if not isinstance(raw, dict):
        return None
    decision = _text(raw.get("decision"), MAX_DECISION_CHARS)
    if not decision:
        return None

    constraints = [
        c for c in (_text(x) for x in (raw.get("constraints") or []) if isinstance(x, str)) if c
    ][:MAX_CONSTRAINTS]

    chosen_status = status or raw.get("status")
    return {
        "decision": decision,
        "options": _keyed(raw.get("options"), "O", "options", MAX_OPTIONS,
                          with_measure=False, reserved=reserved),
        "outcomes": _keyed(raw.get("outcomes"), "Y", "outcomes", MAX_OUTCOMES,
                           with_measure=True, reserved=reserved),
        "deadline": _text(raw.get("deadline")),
        "constraints": constraints,
        "status": chosen_status if chosen_status in (STATUS_DRAFT, STATUS_CONFIRMED) else STATUS_DRAFT,
    }


def anchor_keys(anchor: dict[str, Any] | None) -> set[str]:
    """Every option and outcome key in the anchor."""
    if not anchor:
        return set()
    return {i["key"] for i in anchor.get("options", [])} | {
        i["key"] for i in anchor.get("outcomes", [])
    }


def render_anchor(anchor: dict[str, Any] | None) -> str:
    """The anchor as a prompt block, or nothing when there is none.

    Empty rather than a placeholder for the same reason as ``render_objective``:
    a prompt that says "the decision is unknown" invites the model to invent one.
    """
    if not anchor:
        return ""
    lines = ["# The decision being made (stated by the user, authoritative)",
             anchor["decision"]]
    if anchor.get("options"):
        lines.append("\nOptions on the table:")
        lines.extend(f"- {o['key']}: {o['label']}" for o in anchor["options"])
    if anchor.get("outcomes"):
        lines.append("\nWhat success looks like (outcomes):")
        for y in anchor["outcomes"]:
            measure = f" — measured by: {y['measure']}" if y.get("measure") else ""
            lines.append(f"- {y['key']}: {y['label']}{measure}")
    if anchor.get("deadline"):
        lines.append(f"\nDecide by: {anchor['deadline']}")
    if anchor.get("constraints"):
        lines.append("\nHard constraints:")
        lines.extend(f"- {c}" for c in anchor["constraints"])
    return "\n".join(lines) + "\n"


def outcome_claim_text(outcome: dict[str, str]) -> str:
    """The text of the graph node standing for an outcome.

    Phrased as a proposition, because every other node is one: belief
    propagation computes how likely it is to hold, and "Y1: delivery date" is
    not something that can hold.
    """
    measure = f" ({outcome['measure']})" if outcome.get("measure") else ""
    return f"Success criterion met: {outcome['label']}{measure}"


async def draft_anchor(
    llm: LLMClient,
    objective: str | None,
    material: str,
) -> dict[str, Any] | None:
    """Draft an anchor from the stated objective and the material.

    Never raises, and returns None without an objective. This improves a run
    that can proceed without it, and the decision is the one thing the model
    must not supply on its own.
    """
    objective = (objective or "").strip()
    if not objective:
        return None
    try:
        payload = await llm.complete_json(
            system=ANCHOR_DRAFT_SYSTEM,
            user=(
                f"THE OBJECTIVE, AS THE USER STATED IT:\n{objective}\n\n"
                f"THE MATERIAL:\n\n{(material or '')[:MAX_DRAFT_MATERIAL_CHARS]}"
            ),
            schema=ANCHOR_DRAFT_SCHEMA,
            max_tokens=1500,
            temperature=0.2,
        )
    except Exception as exc:
        logger.warning("Decision anchor draft unavailable, continuing without: %s", exc)
        return None

    anchor = normalise_anchor(payload, status=STATUS_DRAFT)
    if anchor is None:
        # The model returned no decision. Fall back to the user's own words
        # rather than to nothing: an anchor with only a decision still tells
        # extraction what the claims are for.
        anchor = normalise_anchor({"decision": objective}, status=STATUS_DRAFT)
    return anchor


def clean_claim_scores(
    raw: dict[str, Any],
    keys: set[str],
) -> dict[str, Any]:
    """Validate the four anchor fields on one claim.

    Unknown roles become None rather than a guess, relevance is clamped, and
    ``bears_on`` keeps only keys the anchor actually has — a model citing O5 on
    a three-option anchor has invented an option.
    """
    role = raw.get("decision_role")
    relevance = raw.get("relevance")
    try:
        relevance = max(0.0, min(1.0, float(relevance))) if relevance is not None else None
    except (TypeError, ValueError):
        relevance = None
    bears = raw.get("bears_on") or []
    reason = raw.get("relevance_reason", raw.get("reason"))
    return {
        "decision_role": role if role in VALID_ROLES else None,
        "relevance": relevance,
        "relevance_reason": _text(reason, 500) or None,
        "bears_on": sorted({b for b in bears if isinstance(b, str) and b in keys}) or None,
    }


async def score_relevance(
    llm: LLMClient,
    anchor: dict[str, Any],
    texts: list[str],
) -> list[dict[str, Any] | None]:
    """Score claims against the anchor, one batched call per chunk of claims.

    Used where claims exist without scores: discovered claims, and every claim
    after the anchor is edited. Re-scoring is a fraction of re-running the
    pipeline — one call per forty claims, against one call per claim and pair.

    Returns one entry per input text, None where scoring failed. A failed batch
    leaves its claims unscored rather than failing the caller: an unscored claim
    is treated exactly as claims were before the anchor existed.
    """
    if not anchor or not texts:
        return [None] * len(texts)

    keys = anchor_keys(anchor)
    context = render_anchor(anchor)
    results: list[dict[str, Any] | None] = [None] * len(texts)
    semaphore = asyncio.Semaphore(_RELEVANCE_CONCURRENCY)

    async def _batch(start: int) -> None:
        chunk = texts[start:start + RELEVANCE_BATCH]
        numbered = "\n".join(f"[{i}] {t}" for i, t in enumerate(chunk))
        async with semaphore:
            try:
                payload = await llm.complete_json(
                    system=RELEVANCE_SYSTEM,
                    user=f"{context}\n# Claims\n{numbered}",
                    schema=RELEVANCE_SCHEMA,
                    max_tokens=4096,
                    temperature=0.1,
                )
            except Exception as exc:
                logger.warning(
                    "Relevance scoring failed for claims %d-%d: %s",
                    start, start + len(chunk) - 1, exc,
                )
                return
        for entry in payload.get("scores") or []:
            if not isinstance(entry, dict):
                continue
            index = entry.get("index")
            if isinstance(index, int) and 0 <= index < len(chunk):
                results[start + index] = clean_claim_scores(entry, keys)

    await asyncio.gather(*(_batch(s) for s in range(0, len(texts), RELEVANCE_BATCH)))
    scored = sum(1 for r in results if r is not None)
    logger.info("Relevance scored for %d of %d claim(s)", scored, len(texts))
    return results
