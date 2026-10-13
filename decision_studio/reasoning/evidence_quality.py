"""Evidence quality: descriptive labels instead of one opaque score.

Two kinds of evidence exist, and both get labels from what is already stored:

* **Documents** retrieved for a causal link (``Evidence``): published date,
  supporting or contradicting, source, relevance, and the author's interest.
* **Observations** that moved a theory's conviction (``TheoryBelief`` evidence
  rows): when, which way, which event, and the decisiveness stated in advance
  for the tripwire or link test they came from.

Each label is a small fact with a tone (good / neutral / caution) so a reader
can see *why* evidence is strong or weak. Nothing is combined into a new score;
the existing ``evidence_score`` and likelihood ratios are unchanged.

Thresholds (conventions, not calibrated):

* document **recent** under ``RECENT_DOCUMENT_DAYS`` (1 year), **dated** under
  ``OLD_DOCUMENT_DAYS`` (3 years), else **old**; no date → **undated**;
* observation **recent** under ``RECENT_OBSERVATION_DAYS`` (90 days);
* **direct** when the document's relevance to the link is at least
  ``DIRECT_RELEVANCE`` (0.7), else indirect;
* an observation **supports** when its likelihood ratio is above 1.05,
  **contradicts** below 0.95, else it is **inconclusive**.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlparse

RECENT_DOCUMENT_DAYS = 365
OLD_DOCUMENT_DAYS = 3 * 365
RECENT_OBSERVATION_DAYS = 90
DIRECT_RELEVANCE = 0.7
SUPPORT_LR = 1.05
CONTRADICT_LR = 0.95

GOOD, NEUTRAL, CAUTION = "good", "neutral", "caution"


def label(key: str, text: str, tone: str = NEUTRAL) -> dict[str, str]:
    return {"key": key, "text": text, "tone": tone}


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _age_days(moment: datetime | None, now: datetime) -> int | None:
    moment = _aware(moment)
    return None if moment is None else max(0, (now - moment).days)


def source_key(evidence: Any) -> str:
    """What counts as "the same source": the site, or the title for internal documents."""
    url = getattr(evidence, "source_url", "") or ""
    host = urlparse(url).netloc.lower().removeprefix("www.") if url else ""
    return host or (getattr(evidence, "source_title", "") or "").strip().lower()


def document_labels(evidence: Any, siblings: Iterable[Any], now: datetime | None = None) -> list[dict[str, str]]:
    """Labels for one retrieved document, judged beside the others on the same link."""
    now = now or datetime.now(timezone.utc)
    out = []
    age = _age_days(getattr(evidence, "published_date", None), now)
    if age is None:
        out.append(label("undated", "Undated", CAUTION))
    elif age < RECENT_DOCUMENT_DAYS:
        out.append(label("recent", "Recent", GOOD))
    elif age < OLD_DOCUMENT_DAYS:
        out.append(label("dated", f"{age // 365} year(s) old"))
    else:
        out.append(label("old", f"{age // 365} years old", CAUTION))

    if getattr(evidence, "evidence_type", "") == "contradicting":
        out.append(label("contradicts", "Contradicts", CAUTION))
    else:
        out.append(label("supports", "Supports", GOOD))

    key = source_key(evidence)
    same = [s for s in siblings if s is not evidence and key and source_key(s) == key]
    if same:
        out.append(label("same_source", f"Same source as {len(same)} other(s)", CAUTION))
    else:
        out.append(label("independent", "Independent", GOOD))

    relevance = getattr(evidence, "relevance_score", None) or 0.0
    out.append(label("direct", "Direct", GOOD) if relevance >= DIRECT_RELEVANCE
               else label("indirect", "Indirect"))

    interest = getattr(evidence, "author_interest", None)
    if interest == "interested":
        out.append(label("interested", "Interested source", CAUTION))
    elif interest == "against_interest":
        out.append(label("against_interest", "Against the author's interest", GOOD))
    return out


def observation_labels(
    step: Any, *, decisiveness: str | None = None, now: datetime | None = None,
) -> list[dict[str, str]]:
    """Labels for one observation in a theory's conviction history (theory_value.ConvictionStep)."""
    now = now or datetime.now(timezone.utc)
    out = []
    kinds = {"tripwire": "Tripwire", "link_hypothesis": "Link test", "field_experiment": "Field test"}
    out.append(label("kind", kinds.get(step.source, step.source)))

    age = _age_days(step.created_at, now)
    if age is not None:
        out.append(label("recent", "Recent", GOOD) if age < RECENT_OBSERVATION_DAYS
                   else label("dated", f"{age // 30} month(s) ago"))

    lr = step.likelihood_ratio
    if lr > SUPPORT_LR:
        out.append(label("supports", "Supports", GOOD))
    elif lr < CONTRADICT_LR:
        out.append(label("contradicts", "Contradicts", CAUTION))
    else:
        out.append(label("inconclusive", "Inconclusive", CAUTION))

    if step.duplicate_of:
        out.append(label("same_event", "Same event as another observation", CAUTION))
    elif step.event:
        out.append(label("independent", "Independent", GOOD))
    else:
        out.append(label("event_unnamed", "Event not named"))

    if decisiveness:
        tone = GOOD if decisiveness == "decisive" else (CAUTION if decisiveness == "weak" else NEUTRAL)
        out.append(label(decisiveness, decisiveness.capitalize(), tone))

    if not step.applied and not step.duplicate_of:
        out.append(label("in_prior", "Already in the stated conviction"))
    return out


def summarise_documents(evidences: list[Any], now: datetime | None = None) -> dict[str, Any]:
    """What the documents behind a claim's links add up to, as counts and labels."""
    now = now or datetime.now(timezone.utc)
    if not evidences:
        return {"count": 0, "supporting": 0, "contradicting": 0, "sources": 0,
                "newest": None, "labels": [label("none", "No evidence found", CAUTION)]}
    supporting = sum(1 for e in evidences if getattr(e, "evidence_type", "") != "contradicting")
    contradicting = len(evidences) - supporting
    sources = len({source_key(e) for e in evidences if source_key(e)})
    dates = [_aware(getattr(e, "published_date", None)) for e in evidences]
    dated = [d for d in dates if d is not None]
    newest = max(dated) if dated else None
    labels = [label("supporting", f"{supporting} supporting", GOOD if supporting else NEUTRAL)]
    if contradicting:
        labels.append(label("contradicting", f"{contradicting} contradicting", CAUTION))
    labels.append(label("sources", f"{sources} independent source(s)",
                        GOOD if sources >= 2 else NEUTRAL))
    age = _age_days(newest, now)
    if age is None:
        labels.append(label("undated", "Undated", CAUTION))
    elif age < RECENT_DOCUMENT_DAYS:
        labels.append(label("recent", "Recent", GOOD))
    else:
        labels.append(label("dated", f"Newest is {age // 365} year(s) old", CAUTION))
    return {"count": len(evidences), "supporting": supporting, "contradicting": contradicting,
            "sources": sources, "newest": newest.isoformat() if newest else None, "labels": labels}
