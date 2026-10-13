"""Validation and repair of structured LLM output.

Everything the model returns is treated as untrusted. A theory or question is
only allowed into the database once every reference it cites resolves to a real,
active element of the graph snapshot it was generated from. Dangling references
are dropped rather than stored, because a theory that cites a claim which no
longer exists is worse than no theory at all.

All functions here are pure: they take a :class:`ReferenceMap`, a
:class:`GraphSnapshot` and a raw payload, and return validated dataclasses plus
a report of what was repaired. That keeps them testable without a database or a
live provider.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from decision_studio.reasoning.context_builder import ReferenceMap
from decision_studio.reasoning.effective_graph import GraphSnapshot

logger = logging.getLogger(__name__)

THEORY_STATUSES: tuple[str, ...] = (
    "hypothesis",
    "supported",
    "contested",
    "insufficient_evidence",
    "superseded",
)
GENERATED_THEORY_STATUSES: tuple[str, ...] = THEORY_STATUSES[:-1]
BUSINESS_IMPACTS: tuple[str, ...] = ("low", "medium", "high", "critical")
#: What a theory of value predicts for the outcome under its option.
PREDICTED_EFFECTS: tuple[str, ...] = ("achieves", "threatens", "unclear")
ANSWER_TYPES: tuple[str, ...] = (
    "free_text",
    "single_choice",
    "multi_choice",
    "yes_no",
    "number",
    "date",
)
INFORMATION_GAINS: tuple[str, ...] = ("low", "medium", "high")
QUESTION_PRIORITIES: tuple[str, ...] = ("low", "medium", "high", "critical")
QUESTION_STATUSES: tuple[str, ...] = ("open", "answered", "dismissed", "skipped")

#: Two theories resting on this share of the same edges are the same theory.
DUPLICATE_EDGE_OVERLAP = 0.8
#: Token overlap above which two questions are treated as semantically equal.
DUPLICATE_QUESTION_OVERLAP = 0.7

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "to", "of", "in",
    "on", "for", "and", "or", "it", "this", "that", "we", "you", "your", "our",
    "do", "does", "did", "has", "have", "had", "will", "would", "can", "could",
    "what", "which", "how", "any", "there", "with", "by", "at", "as", "from",
}


@dataclass
class ValidationReport:
    """What had to be dropped or repaired to make the output storable."""

    unknown_refs: list[str] = field(default_factory=list)
    dropped: list[dict[str, Any]] = field(default_factory=list)
    repaired: list[dict[str, Any]] = field(default_factory=list)
    accepted: int = 0

    @property
    def ok(self) -> bool:
        """Whether anything survived validation."""
        return self.accepted > 0

    def as_dict(self) -> dict[str, Any]:
        """The report, for the API and the log."""
        return {
            "accepted": self.accepted,
            "dropped": self.dropped,
            "repaired": self.repaired,
            "unknown_refs": sorted(set(self.unknown_refs)),
        }


@dataclass
class ValidatedTheory:
    """A theory whose every reference resolves to a live graph element."""

    title: str
    summary: str
    status: str
    confidence: float
    business_impact: str
    recommendation: str
    weak_assumptions: list[str]
    supporting_claim_ids: list[str]
    supporting_edge_ids: list[str]
    supporting_evidence_ids: list[str]
    contradicting_evidence_ids: list[str]
    causal_chain: list[dict[str, Any]]
    #: Edges in the chain whose endpoints match their neighbours, over edges
    #: cited. Exposed rather than folded into the score: weighting integrity
    #: inside `adjusted_score` would be another uncalibrated constant, and the
    #: reader can see "1 of 3 links verified" and judge for themselves.
    connected_links: int = 0
    cited_links: int = 0
    previous_theory_key: str | None = None
    change_explanation: str | None = None
    # --- Theory of value ---
    option_key: str | None = None
    predicted_effect: str = "unclear"
    outcome_keys: list[str] = field(default_factory=list)
    #: Computed from the chain, never taken from the model.
    reaches_outcome: bool = False


@dataclass
class ValidatedQuestion:
    """A clarification question with resolved links and a dedup fingerprint."""

    question: str
    reason: str
    expected_information_gain: str
    priority: str
    answer_type: str
    options: list[str]
    linked_theory_keys: list[str]
    linked_claim_ids: list[str]
    linked_edge_ids: list[str]
    fingerprint: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def clamp_confidence(value: Any) -> float:
    """Coerce a model-supplied confidence into [0, 1]."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.5
    if numeric != numeric:  # NaN
        return 0.5
    return max(0.0, min(1.0, numeric))


def normalize_enum(value: Any, allowed: tuple[str, ...], default: str) -> tuple[str, bool]:
    """Return ``(value, was_repaired)`` for an enum-valued field."""
    if isinstance(value, str) and value.strip().lower() in allowed:
        return value.strip().lower(), False
    return default, True


def _resolve(refs: list[Any], mapping: dict[str, str], report: ValidationReport) -> list[str]:
    """Map reference tokens to UUIDs, recording any that do not exist."""
    resolved: list[str] = []
    for raw in refs or []:
        if not isinstance(raw, str):
            report.unknown_refs.append(str(raw))
            continue
        token = raw.strip().upper()
        target = mapping.get(token)
        if target is None:
            report.unknown_refs.append(raw)
            continue
        if target not in resolved:
            resolved.append(target)
    return resolved


def question_fingerprint(text: str) -> str:
    """Stable hash of a question's content words, for duplicate suppression."""
    return hashlib.sha256(" ".join(sorted(question_tokens(text))).encode()).hexdigest()[:32]


def question_tokens(text: str) -> set[str]:
    """Content words of a question, lowercased and stripped of stopwords.

    Numbers are kept whatever their length: "is the delay 3 weeks or 6 weeks?"
    differs from "is the delay 12 weeks?" precisely in the digits, and dropping
    them would collapse two genuinely different questions into one.
    """
    words = re.findall(r"\w+", (text or "").lower(), flags=re.UNICODE)
    tokens = {
        w for w in words if (w.isdigit() or len(w) > 2) and w not in _STOPWORDS
    }
    if not tokens:
        # CJK and other scripts do not tokenize on word boundaries; fall back to
        # character shingles so dedup still does something useful.
        stripped = re.sub(r"\s+", "", text or "")
        tokens = {stripped[i : i + 2] for i in range(max(len(stripped) - 1, 0))}
    return tokens


def is_duplicate_question(text: str, existing_texts: list[str]) -> bool:
    """True when *text* substantially repeats one of *existing_texts*."""
    tokens = question_tokens(text)
    if not tokens:
        return False
    for other in existing_texts:
        other_tokens = question_tokens(other)
        if not other_tokens:
            continue
        overlap = len(tokens & other_tokens) / len(tokens | other_tokens)
        if overlap >= DUPLICATE_QUESTION_OVERLAP:
            return True
    return False


# ---------------------------------------------------------------------------
# Theories
# ---------------------------------------------------------------------------


def validate_theories(
    payload: dict[str, Any],
    refs: ReferenceMap,
    snapshot: GraphSnapshot,
    *,
    known_theory_keys: set[str] | None = None,
    anchor: dict[str, Any] | None = None,
) -> tuple[list[ValidatedTheory], ValidationReport]:
    """Validate a raw theory-generation payload against the graph snapshot.

    With a decision anchor, each theory's option and outcome keys are checked
    against it, and whether the chain reaches an outcome is computed from the
    validated chain — a model saying its theory reaches the decision is not
    evidence that it does.

    A theory is dropped when it has no title/summary, or when it retains no
    supporting claims *and* no supporting edges after reference resolution —
    at that point it is narrative without provenance. Everything else is
    repaired in place and reported.
    """
    report = ValidationReport()
    raw_theories = payload.get("theories") or []
    if not isinstance(raw_theories, list):
        report.dropped.append({"reason": "theories field was not a list"})
        return [], report

    validated: list[ValidatedTheory] = []
    for index, raw in enumerate(raw_theories):
        if not isinstance(raw, dict):
            report.dropped.append({"index": index, "reason": "not an object"})
            continue

        title = (raw.get("title") or "").strip()
        summary = (raw.get("summary") or "").strip()
        if not title or not summary:
            report.dropped.append({"index": index, "reason": "missing title or summary"})
            continue

        claim_ids = _resolve(raw.get("supporting_claim_refs"), refs.ref_to_claim, report)
        edge_ids = _resolve(raw.get("supporting_edge_refs"), refs.ref_to_edge, report)

        # Keep only elements still present in the snapshot. The snapshot holds
        # exclusively active, non-rejected elements, so this is the active check.
        claim_ids = [cid for cid in claim_ids if cid in snapshot.claims_by_id]
        edge_ids = [eid for eid in edge_ids if eid in snapshot.edges_by_id]

        # An edge implies its endpoints; keep provenance complete.
        for eid in edge_ids:
            edge = snapshot.edges_by_id[eid]
            for endpoint in (str(edge.source_claim_id), str(edge.target_claim_id)):
                if endpoint in snapshot.claims_by_id and endpoint not in claim_ids:
                    claim_ids.append(endpoint)

        if not claim_ids and not edge_ids:
            report.dropped.append(
                {"index": index, "title": title, "reason": "no valid graph references"}
            )
            continue

        supporting_ev = _resolve(
            raw.get("supporting_evidence_refs"), refs.ref_to_evidence, report
        )
        contradicting_ev = _resolve(
            raw.get("contradicting_evidence_refs"), refs.ref_to_evidence, report
        )

        edge_id_set = set(edge_ids)

        def _keep_evidence(evidence_ids: list[str], kind: str) -> list[str]:
            """Evidence ids that resolve to live rows, dropping the rest."""
            kept: list[str] = []
            for ev_id in evidence_ids:
                owner = snapshot.evidence_edge_id(ev_id)
                if owner is None:
                    report.dropped.append(
                        {"index": index, "reason": f"{kind} evidence not in snapshot"}
                    )
                    continue
                if owner not in edge_id_set:
                    # Evidence belongs to an edge the theory does not rest on:
                    # citing it would imply support the graph does not encode.
                    report.dropped.append(
                        {
                            "index": index,
                            "reason": f"{kind} evidence belongs to an uncited edge",
                        }
                    )
                    continue
                kept.append(ev_id)
            return kept

        supporting_ev = _keep_evidence(supporting_ev, "supporting")
        contradicting_ev = _keep_evidence(contradicting_ev, "contradicting")

        status, status_repaired = normalize_enum(
            raw.get("status"), GENERATED_THEORY_STATUSES, "hypothesis"
        )
        impact, impact_repaired = normalize_enum(
            raw.get("business_impact"), BUSINESS_IMPACTS, "medium"
        )
        confidence = clamp_confidence(raw.get("confidence"))
        if confidence != raw.get("confidence"):
            report.repaired.append(
                {"index": index, "field": "confidence", "value": confidence}
            )
        if status_repaired:
            report.repaired.append({"index": index, "field": "status", "value": status})
        if impact_repaired:
            report.repaired.append(
                {"index": index, "field": "business_impact", "value": impact}
            )

        # A theory with contradicting evidence and no supporting evidence is
        # contested, whatever the model called it.
        if contradicting_ev and not supporting_ev and status == "supported":
            status = "contested"
            report.repaired.append(
                {"index": index, "field": "status", "value": "contested"}
            )
        # "supported" requires at least one piece of real evidence.
        if status == "supported" and not supporting_ev:
            status = "hypothesis"
            report.repaired.append(
                {"index": index, "field": "status", "value": "hypothesis"}
            )

        chain, connected_links, cited_links = _build_chain(
            raw.get("causal_chain"), refs, snapshot, claim_ids, edge_ids,
            report, index,
        )

        # A theory whose every junction was invented is not a low-confidence
        # theory — it is a list of claims with prose between them. Lowering its
        # confidence would leave it in the ranking beside real ones.
        #
        # The threshold is one connected edge, not a fraction. A chain keeping
        # even one verified junction has a piece of real reasoning worth showing
        # broken where it is broken; a chain keeping none has nothing. On short
        # chains a fraction does not discriminate anyway — with two edges "over
        # half" and "all" coincide — so it would add a hand-picked constant
        # without adding a distinction.
        if cited_links > 0 and connected_links == 0:
            report.dropped.append({
                "index": index,
                "reason": "no_connected_chain",
                "detail": (
                    f"none of the {cited_links} cited link(s) join the claims "
                    f"they were placed between"
                ),
                "title": (raw.get("title") or "")[:120],
            })
            continue

        previous_key = (raw.get("previous_theory_key") or "").strip() or None
        if previous_key and known_theory_keys is not None:
            if previous_key not in known_theory_keys:
                report.repaired.append(
                    {"index": index, "field": "previous_theory_key", "value": None}
                )
                previous_key = None

        weak = [
            str(item).strip()
            for item in (raw.get("weak_assumptions") or [])
            if str(item).strip()
        ]

        option_key, effect, outcome_keys, reaches = _theory_of_value(
            raw, chain, snapshot, anchor, report, index
        )

        validated.append(
            ValidatedTheory(
                title=title[:500],
                summary=summary,
                status=status,
                confidence=confidence,
                business_impact=impact,
                recommendation=(raw.get("recommendation") or "").strip(),
                weak_assumptions=weak,
                supporting_claim_ids=claim_ids,
                supporting_edge_ids=edge_ids,
                supporting_evidence_ids=supporting_ev,
                contradicting_evidence_ids=contradicting_ev,
                causal_chain=chain,
                connected_links=connected_links,
                cited_links=cited_links,
                previous_theory_key=previous_key,
                change_explanation=(raw.get("change_explanation") or "").strip() or None,
                option_key=option_key,
                predicted_effect=effect,
                outcome_keys=outcome_keys,
                reaches_outcome=reaches,
            )
        )

    deduped = _drop_duplicate_theories(validated, report)
    report.accepted = len(deduped)
    return deduped, report


def _outcome_key(claim: Any) -> str | None:
    """The anchor key of an outcome node, or None for any other claim."""
    if getattr(claim, "origin", None) != "frame" or getattr(claim, "decision_role", None) != "outcome":
        return None
    return (getattr(claim, "metadata_", None) or {}).get("anchor_key") or ""


def _theory_of_value(
    raw: dict[str, Any],
    chain: list[dict[str, Any]],
    snapshot: GraphSnapshot,
    anchor: dict[str, Any] | None,
    report: ValidationReport,
    index: int,
) -> tuple[str | None, str, list[str], bool]:
    """The option a theory is about, its predicted effect, and whether it arrives.

    Returns ``(option_key, predicted_effect, outcome_keys, reaches_outcome)``.

    * An option key the anchor does not have is dropped — a theory of O5 on a
      three-option decision is a theory of an option nobody is considering.
    * Outcome keys are the model's, filtered to the anchor, plus every outcome
      the chain actually reaches: arriving at an outcome node is the strongest
      statement of what the theory is about.
    * ``reaches_outcome`` looks only at the validated chain. The supporting
      claims are not enough; a theory can cite an outcome without any link
      leading to it.
    """
    option_keys = {o["key"] for o in (anchor or {}).get("options", [])}
    anchor_outcomes = {o["key"] for o in (anchor or {}).get("outcomes", [])}

    option_key = (raw.get("option_key") or "").strip().upper() or None
    if option_key and option_key not in option_keys:
        report.repaired.append({"index": index, "field": "option_key", "value": None})
        option_key = None

    effect, repaired = normalize_enum(raw.get("predicted_effect"), PREDICTED_EFFECTS, "unclear")
    if repaired:
        report.repaired.append({"index": index, "field": "predicted_effect", "value": effect})

    chain_claims: list[str] = []
    for step in chain:
        for key in ("claim_id", "source_claim_id", "target_claim_id"):
            if step.get(key):
                chain_claims.append(step[key])
    reached = [
        key for key in (
            _outcome_key(snapshot.claims_by_id.get(cid)) for cid in chain_claims
        ) if key is not None
    ]

    stated = [
        str(k).strip().upper() for k in (raw.get("outcome_keys") or [])
        if str(k).strip().upper() in anchor_outcomes
    ]
    outcome_keys = sorted({*stated, *(k for k in reached if k)})
    return option_key, effect, outcome_keys, bool(reached)


def _build_chain(
    raw_chain: Any,
    refs: ReferenceMap,
    snapshot: GraphSnapshot,
    claim_ids: list[str],
    edge_ids: list[str],
    report: ValidationReport | None = None,
    index: int = 0,
) -> tuple[list[dict[str, Any]], int, int]:
    """Turn a ref token walk into a chain, keeping only edges that actually fit.

    Returns ``(chain, connected_edges, cited_edges)``.

    **The check this performs is the point of the function.** Reference
    validation elsewhere confirms that each token *resolves* to a live graph
    element; it does not confirm that an edge *joins* the claim before it to the
    claim after it. Without that, a model on a large fragmented graph picks
    plausible-looking tokens and produces a chain like:

        The contract does not specify the equalisation window.
          ↓ Poor internet disrupted data exchange onboard vessel C1.
        Repeated price-reduction requests consumed time.

    Every token resolves. Nothing is missing. The chain is still fiction, and it
    was being rendered with the same authority as a real one — which is the one
    thing this product claims to do that others do not.

    Three outcomes rather than two:

    * **connected** — the edge joins its neighbours, in that direction.
    * **reversed** — it joins them the other way round. Recorded separately and
      still dropped: in a causal graph the direction *is* the assertion, so a
      model that reversed it got the theory wrong rather than the transcription.
      Silently flipping it would repair the sentence and keep the error.
    * **disconnected** — it touches neither neighbour.

    Head and tail edges are held to a **single** constraint, because they have
    only one neighbour. Requiring both would discard legitimate steps while
    looking more rigorous than the version that does not.
    """
    chain: list[dict[str, Any]] = []
    rejected_edge_ids: set[str] = set()
    connected = 0
    cited = 0

    # Resolve first, check second: the neighbours of a step are only knowable
    # once the whole walk has been read.
    steps: list[dict[str, Any]] = []
    for token in raw_chain or []:
        if not isinstance(token, str):
            continue
        key = token.strip().upper()
        claim_id = refs.ref_to_claim.get(key)
        if claim_id and claim_id in snapshot.claims_by_id:
            steps.append(
                {"claim_id": claim_id, "label": snapshot.claims_by_id[claim_id].text}
            )
            continue
        edge_id = refs.ref_to_edge.get(key)
        if edge_id and edge_id in snapshot.edges_by_id:
            edge = snapshot.edges_by_id[edge_id]
            steps.append(
                {
                    "edge_id": edge_id,
                    "source_claim_id": str(edge.source_claim_id),
                    "target_claim_id": str(edge.target_claim_id),
                    "label": edge.mechanism,
                }
            )

    for position, step in enumerate(steps):
        if "edge_id" not in step:
            chain.append(step)
            continue

        cited += 1
        before = _neighbour_claim(steps, position, -1)
        after = _neighbour_claim(steps, position, +1)
        verdict = _edge_fits(step, before, after)

        if verdict == "connected":
            connected += 1
            chain.append(step)
            continue

        rejected_edge_ids.add(step["edge_id"])
        if report is not None:
            report.repaired.append({
                "index": index,
                "field": "causal_chain",
                "edge_id": step["edge_id"],
                "reason": verdict,
                "detail": (
                    "cited in the wrong direction"
                    if verdict == "reversed"
                    else "does not join the surrounding claims"
                ),
            })

    if chain and connected:
        return chain, connected, cited

    # Nothing usable was supplied. Reconstruct a minimal chain so the UI has
    # something to highlight — but **excluding the edges just rejected**.
    # Without that exclusion the fallback reads from `edge_ids`, which contains
    # exactly the edges whose connectivity failed, and re-admits them through
    # the back door with the shape of a verified chain.
    fallback: list[dict[str, Any]] = []
    for edge_id in edge_ids:
        if edge_id in rejected_edge_ids:
            continue
        edge = snapshot.edges_by_id[edge_id]
        fallback.append(
            {
                "edge_id": edge_id,
                "source_claim_id": str(edge.source_claim_id),
                "target_claim_id": str(edge.target_claim_id),
                "label": edge.mechanism,
            }
        )
    if fallback:
        return fallback, 0, cited

    for claim_id in claim_ids:
        fallback.append(
            {"claim_id": claim_id, "label": snapshot.claims_by_id[claim_id].text}
        )
    return fallback, 0, cited


def _neighbour_claim(
    steps: list[dict[str, Any]], position: int, direction: int
) -> str | None:
    """The claim id adjacent to a step, or None when the step is at an end.

    Only the immediate neighbour counts. Two edges in a row means the model
    omitted the claim between them, and treating the claim beyond as adjacent
    would accept a chain with a hole in it as connected.
    """
    neighbour = position + direction
    if 0 <= neighbour < len(steps):
        return steps[neighbour].get("claim_id")
    return None


def _edge_fits(
    step: dict[str, Any], before: str | None, after: str | None
) -> str:
    """``connected``, ``reversed`` or ``disconnected``.

    An edge with no claim on either side cannot be checked, and is accepted:
    refusing what cannot be verified would drop a lone edge that may be right,
    which is a different failure from the one being fixed here.
    """
    source, target = step["source_claim_id"], step["target_claim_id"]
    if before is None and after is None:
        return "connected"

    forward = (before is None or source == before) and (after is None or target == after)
    if forward:
        return "connected"

    backward = (before is None or target == before) and (after is None or source == after)
    return "reversed" if backward else "disconnected"


def _drop_duplicate_theories(
    theories: list[ValidatedTheory], report: ValidationReport
) -> list[ValidatedTheory]:
    """Remove theories that rest on substantially the same causal path."""
    kept: list[ValidatedTheory] = []
    for theory in theories:
        edges = set(theory.supporting_edge_ids)
        duplicate_of = None
        for existing in kept:
            other = set(existing.supporting_edge_ids)
            if not edges and not other:
                continue
            union = edges | other
            if not union:
                continue
            overlap = len(edges & other) / len(union)
            if overlap >= DUPLICATE_EDGE_OVERLAP:
                duplicate_of = existing
                break
        if duplicate_of is not None:
            report.dropped.append(
                {
                    "title": theory.title,
                    "reason": "duplicate causal path",
                    "duplicate_of": duplicate_of.title,
                }
            )
            continue
        kept.append(theory)
    return kept


# ---------------------------------------------------------------------------
# Clarification questions
# ---------------------------------------------------------------------------


def validate_questions(
    payload: dict[str, Any],
    refs: ReferenceMap,
    snapshot: GraphSnapshot,
    *,
    existing_questions: list[str] | None = None,
    known_theory_keys: set[str] | None = None,
    max_questions: int = 6,
) -> tuple[list[ValidatedQuestion], ValidationReport]:
    """Validate raw clarification output, dropping duplicates and bad links."""
    report = ValidationReport()
    raw_questions = payload.get("questions") or []
    if not isinstance(raw_questions, list):
        report.dropped.append({"reason": "questions field was not a list"})
        return [], report

    seen_texts = list(existing_questions or [])
    validated: list[ValidatedQuestion] = []

    for index, raw in enumerate(raw_questions):
        if not isinstance(raw, dict):
            report.dropped.append({"index": index, "reason": "not an object"})
            continue
        text = (raw.get("question") or "").strip()
        if not text:
            report.dropped.append({"index": index, "reason": "empty question"})
            continue
        if is_duplicate_question(text, seen_texts):
            report.dropped.append(
                {"index": index, "question": text, "reason": "duplicate question"}
            )
            continue

        answer_type, at_repaired = normalize_enum(
            raw.get("answer_type"), ANSWER_TYPES, "free_text"
        )
        gain, gain_repaired = normalize_enum(
            raw.get("expected_information_gain"), INFORMATION_GAINS, "medium"
        )
        priority, prio_repaired = normalize_enum(
            raw.get("priority"), QUESTION_PRIORITIES, "medium"
        )
        for repaired, field_name, value in (
            (at_repaired, "answer_type", answer_type),
            (gain_repaired, "expected_information_gain", gain),
            (prio_repaired, "priority", priority),
        ):
            if repaired:
                report.repaired.append(
                    {"index": index, "field": field_name, "value": value}
                )

        options = [str(o).strip() for o in (raw.get("options") or []) if str(o).strip()]
        if answer_type in ("single_choice", "multi_choice") and len(options) < 2:
            # A choice question without choices is unanswerable; degrade rather
            # than invent options the model did not supply.
            answer_type = "free_text"
            options = []
            report.repaired.append(
                {"index": index, "field": "answer_type", "value": "free_text"}
            )
        if answer_type == "yes_no":
            options = []
        if answer_type not in ("single_choice", "multi_choice"):
            options = []

        claim_ids = _resolve(raw.get("linked_claim_refs"), refs.ref_to_claim, report)
        edge_ids = _resolve(raw.get("linked_edge_refs"), refs.ref_to_edge, report)
        claim_ids = [c for c in claim_ids if c in snapshot.claims_by_id]
        edge_ids = [e for e in edge_ids if e in snapshot.edges_by_id]

        theory_keys = [
            str(k).strip()
            for k in (raw.get("linked_theory_keys") or [])
            if str(k).strip()
        ]
        if known_theory_keys is not None:
            unknown = [k for k in theory_keys if k not in known_theory_keys]
            if unknown:
                report.unknown_refs.extend(unknown)
            theory_keys = [k for k in theory_keys if k in known_theory_keys]

        validated.append(
            ValidatedQuestion(
                question=text,
                reason=(raw.get("reason") or "").strip(),
                expected_information_gain=gain,
                priority=priority,
                answer_type=answer_type,
                options=options,
                linked_theory_keys=theory_keys,
                linked_claim_ids=claim_ids,
                linked_edge_ids=edge_ids,
                fingerprint=question_fingerprint(text),
            )
        )
        seen_texts.append(text)
        if len(validated) >= max_questions:
            break

    report.accepted = len(validated)
    return validated, report


def validate_answer(answer_type: str, value: Any, options: list[str] | None) -> Any:
    """Validate and coerce a user answer for the question's answer type.

    Raises:
        ValueError: if the value does not fit the declared answer type.
    """
    if answer_type == "yes_no":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in ("yes", "no", "true", "false"):
            return value.strip().lower() in ("yes", "true")
        raise ValueError("Answer must be yes or no")

    if answer_type == "number":
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Answer must be a number") from exc

    if answer_type == "date":
        from datetime import date, datetime

        if isinstance(value, (date, datetime)):
            return value.isoformat()
        try:
            return datetime.fromisoformat(str(value)).date().isoformat()
        except ValueError as exc:
            raise ValueError("Answer must be an ISO-8601 date") from exc

    if answer_type == "single_choice":
        if not isinstance(value, str) or value not in (options or []):
            raise ValueError("Answer must be one of the offered options")
        return value

    if answer_type == "multi_choice":
        if not isinstance(value, list) or not value:
            raise ValueError("Answer must be a non-empty list of options")
        invalid = [v for v in value if v not in (options or [])]
        if invalid:
            raise ValueError(f"Not an offered option: {invalid[0]}")
        return list(value)

    # free_text
    text = str(value).strip()
    if not text:
        raise ValueError("Answer cannot be empty")
    return text
