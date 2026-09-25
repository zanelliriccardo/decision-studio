"""Inspect what claim deduplication merged, and at what similarity.

Written to answer a specific worry: on a set of contract documents, dedup
removed 710 of 1186 claims. Two contractual clauses can be worded almost
identically and mean different things — a carve-out that applies "except where
the delay is attributable to the Company" reads at very high cosine similarity
to the same clause without the carve-out, and merging them silently loses the
exception.

The threshold (0.86) was chosen by hand and never checked against real material.
This tool is how you check it.

Run it against a project that has already been analysed::

    python -m decision_studio.tools.inspect_dedup <project-id>
    python -m decision_studio.tools.inspect_dedup <project-id> --band 0.86 0.92
    python -m decision_studio.tools.inspect_dedup <project-id> --csv merges.csv

It re-runs dedup over the claims as they are stored, so it reports what *would*
be merged now rather than what was merged then — which is what you want when
deciding where the threshold belongs. It writes nothing to the database.

What to look for, in the band just above the threshold:

* **Negation.** "The contractor is liable" and "The contractor is not liable"
  embed close together. If these merge, the threshold is far too low.
* **Qualifiers and carve-outs.** "except", "unless", "save where", "provided
  that". A merged pair where one member has a qualifier and the other does not
  is a lost exception.
* **Different subjects, same structure.** "Party A shall notify Party B" versus
  "Party B shall notify Party A". The checks below do **not** catch these — who
  owes the obligation is a semantic difference no keyword can see, so this one
  needs reading. On a contract set it is worth scanning the unflagged merges for
  it specifically.
* **Numbers.** Two clauses differing only in a figure — 30 days versus 60 days —
  are near-identical to an embedding model and materially different to a lawyer.

A pair that differs only in wording is a correct merge and needs no attention.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
from typing import Any
from uuid import UUID

from sqlalchemy import select

from decision_studio.db.models import Claim
from decision_studio.db.session import async_session
from decision_studio.pipeline.claim_dedup import DEDUP_THRESHOLD, dedup_claims

#: Words whose presence in one member of a merged pair and absence in the other
#: means the merge probably lost something. Not exhaustive, and deliberately
#: biased towards contract language.
RISK_PATTERNS = {
    "negation": r"\b(not|no|never|neither|nor|without|fail(s|ed)? to|shall not)\b",
    "exception": r"\b(except|unless|save (where|for)|provided that|other than|"
                 r"excluding|notwithstanding)\b",
    "obligation": r"\b(shall|must|may|is entitled|is required|is liable)\b",
    "conditional": r"\b(if|where|when|in the event|subject to|contingent)\b",
}


def _risks(text: str) -> set[str]:
    """Contract-language markers present in the text: negation, exception, and so on."""
    lowered = text.lower()
    return {
        name for name, pattern in RISK_PATTERNS.items()
        if re.search(pattern, lowered)
    }


def _numbers(text: str) -> set[str]:
    """Figures that carry meaning: days, percentages, amounts, years."""
    return set(re.findall(r"\b\d[\d,.]*\s*(?:%|days?|months?|years?|weeks?)?\b", text))


def assess(lead: str, member: str) -> list[str]:
    """Why this merge might be wrong. Empty means nothing obviously at risk."""
    flags: list[str] = []

    lead_risks, member_risks = _risks(lead), _risks(member)
    for kind in sorted(lead_risks ^ member_risks):
        # Symmetric difference: present in one and not the other. A qualifier
        # in both is fine; a qualifier in one is a lost distinction.
        flags.append(f"{kind} in only one")

    lead_nums, member_nums = _numbers(lead), _numbers(member)
    if lead_nums != member_nums:
        differing = sorted(lead_nums ^ member_nums)
        if differing:
            flags.append(f"figures differ: {', '.join(differing[:4])}")

    return flags


async def load_claims(project_id: UUID) -> list[dict[str, Any]]:
    """A project's claims, in order, with their embeddings."""
    async with async_session() as session:
        rows = (
            await session.execute(
                select(Claim)
                .where(Claim.project_id == project_id)
                .order_by(Claim.order_index)
            )
        ).scalars().all()

    return [
        {
            "text": row.text,
            "type": row.claim_type,
            "confidence": row.confidence,
            "prior": row.prior,
            "order_index": row.order_index,
            "embedding": list(row.embedding) if row.embedding is not None else None,
            "source_sentence": row.source_sentence,
        }
        for row in rows
    ]


def collect_merges(
    claims: list[dict[str, Any]], threshold: float
) -> list[dict[str, Any]]:
    """Every pair the dedup would merge, with its similarity and any flags."""
    _, report = dedup_claims(claims, threshold=threshold)

    merges: list[dict[str, Any]] = []
    for group in report.get("groups", []):
        lead_text = group.get("kept", "")
        for member, similarity in zip(
            group.get("merged") or [], group.get("similarities") or []
        ):
            merges.append({
                "similarity": similarity,
                "lead": lead_text,
                "member": member,
                "flags": assess(lead_text, member),
                "prior_before": group.get("prior_before"),
                "prior_after": group.get("prior_after"),
            })

    merges.sort(key=lambda m: m["similarity"])
    return merges


def _wrap(text: str, width: int = 96, indent: str = "      ") -> str:
    """Wrap text to a width, indenting continuation lines."""
    words, lines, line = text.split(), [], ""
    for word in words:
        if len(line) + len(word) + 1 > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        lines.append(line)
    return f"\n{indent}".join(lines)


async def main() -> int:
    """Report what dedup would merge now, and flag the merges worth reading."""
    parser = argparse.ArgumentParser(
        description="Inspect what claim deduplication merges, and decide "
                    "whether the threshold is right for your material.",
    )
    parser.add_argument("project_id")
    parser.add_argument(
        "--threshold", type=float, default=DEDUP_THRESHOLD,
        help=f"Similarity at which claims merge (default: {DEDUP_THRESHOLD})",
    )
    parser.add_argument(
        "--band", type=float, nargs=2, metavar=("LOW", "HIGH"),
        help="Only show merges whose similarity falls in this range. The band "
             "just above the threshold is where questionable merges live.",
    )
    parser.add_argument(
        "--flagged-only", action="store_true",
        help="Only merges where a negation, exception or figure differs.",
    )
    parser.add_argument("--csv", metavar="PATH", help="Also write results to CSV.")
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args()

    claims = await load_claims(UUID(args.project_id))
    if not claims:
        print("No claims found for that project.", file=sys.stderr)
        return 1

    without_embeddings = sum(1 for c in claims if not c.get("embedding"))
    if without_embeddings:
        # Said rather than silently skipped: these cannot be compared at all,
        # so any conclusion about the threshold is drawn from a subset.
        print(
            f"note: {without_embeddings} of {len(claims)} claims have no "
            f"embedding and were not compared\n",
            file=sys.stderr,
        )

    merges = collect_merges(claims, args.threshold)

    shown = merges
    if args.band:
        low, high = args.band
        shown = [m for m in shown if low <= m["similarity"] <= high]
    if args.flagged_only:
        shown = [m for m in shown if m["flags"]]

    flagged = sum(1 for m in merges if m["flags"])
    print(f"Claims:     {len(claims)}")
    print(f"Merged:     {len(merges)}  ({100 * len(merges) / len(claims):.0f}%)")
    print(f"Flagged:    {flagged}  (a negation, exception or figure differs)")
    print(f"Threshold:  {args.threshold}")

    # The distribution matters more than any single pair: merges clustered just
    # above the threshold are the ones the threshold is deciding.
    if merges:
        print("\nBy similarity:")
        edges = [(args.threshold, 0.90), (0.90, 0.94), (0.94, 0.97), (0.97, 1.01)]
        for low, high in edges:
            band = [m for m in merges if low <= m["similarity"] < high]
            if not band:
                continue
            band_flagged = sum(1 for m in band if m["flags"])
            bar = "█" * max(1, round(30 * len(band) / len(merges)))
            print(
                f"  {low:.2f}–{high:.2f}  {len(band):>4}  {bar}"
                + (f"   {band_flagged} flagged" if band_flagged else "")
            )

    print(f"\n{'─' * 100}")
    if not shown:
        print("Nothing to show for those filters.")
    for merge in shown[: args.limit]:
        marker = "⚠ " if merge["flags"] else "  "
        print(f"\n{marker}{merge['similarity']:.3f}")
        print(f"      kept:  {_wrap(merge['lead'])}")
        print(f"      lost:  {_wrap(merge['member'])}")
        if merge["flags"]:
            print(f"      → {'; '.join(merge['flags'])}")

    if len(shown) > args.limit:
        print(f"\n… and {len(shown) - args.limit} more. Use --limit or --csv.")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["similarity", "kept", "merged_away", "flags"])
            for merge in merges:
                writer.writerow([
                    merge["similarity"], merge["lead"], merge["member"],
                    "; ".join(merge["flags"]),
                ])
        print(f"\nWrote {len(merges)} rows to {args.csv}")

    print(
        "\nA pair differing only in wording is a correct merge. A pair where one "
        "\nmember carries a qualifier, a negation or a different figure is a lost "
        "\ndistinction — and if those cluster near the threshold, raise it."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
