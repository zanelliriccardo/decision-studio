"""Exporting a decision brief.

The reason this exists: an analysis done on Tuesday is presented on Thursday, in
a room, to people who were not there when it was done. If the only way to reach
the objections and the tripwires is by clicking through a web application, what
actually arrives in that room is the title and the recommendation — pasted into
a slide, with every qualification lost.

That is the exact failure the rest of the system is built to prevent, arriving
through the door nobody guarded.

So the brief carries the qualifications *at the same level* as the conclusion:
objections beside the theory rather than in an appendix, the confidence band
rather than a decimal, and the tripwires with their dates, so the reader can see
what would change the author's mind and by when.

Markdown is the base format because it survives being pasted anywhere. HTML is
produced from it for printing to PDF, which is what a board pack actually needs.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from decision_studio.db.models import (
    CausalEdge,
    Claim,
    Evidence,
    Project,
    Theory,
    TheoryObjection,
    TheoryTripwire,
)
from decision_studio.reasoning.calibration import band
from decision_studio.reasoning.debate_service import list_debates
from decision_studio.reasoning.decision_context import decision_objective
from decision_studio.reasoning.recommendation import get_recommendation
from decision_studio.reasoning.outside_view import list_reference_cases
from decision_studio.reasoning.theories import list_current_theories

logger = logging.getLogger(__name__)

BAND_LABELS = {
    "very_low": "very low",
    "low": "low",
    "moderate": "moderate",
    "high": "high",
    "very_high": "very high",
    "unknown": "not computed",
}


async def _gather(session: AsyncSession, project_id: UUID) -> dict[str, Any]:
    """Everything the brief needs, in a handful of queries rather than per-theory."""
    project = await session.get(Project, project_id)
    if project is None:
        raise LookupError(f"Project {project_id} not found")

    theories = await list_current_theories(session, project_id)
    theory_ids = [t.id for t in theories]

    claims = (
        await session.execute(select(Claim).where(Claim.project_id == project_id))
    ).scalars().all()
    edges = (
        await session.execute(
            select(CausalEdge)
            .where(CausalEdge.project_id == project_id)
            .options(selectinload(CausalEdge.evidences))
        )
    ).scalars().all()

    objections: dict[UUID, list[TheoryObjection]] = {}
    tripwires: dict[UUID, list[TheoryTripwire]] = {}
    if theory_ids:
        for row in (
            await session.execute(
                select(TheoryObjection)
                .where(TheoryObjection.theory_id.in_(theory_ids))
                .order_by(TheoryObjection.severity.desc())
            )
        ).scalars().all():
            objections.setdefault(row.theory_id, []).append(row)
        for row in (
            await session.execute(
                select(TheoryTripwire)
                .where(TheoryTripwire.theory_id.in_(theory_ids))
                .order_by(TheoryTripwire.check_by)
            )
        ).scalars().all():
            tripwires.setdefault(row.theory_id, []).append(row)

    objective = await decision_objective(session, project_id)

    return {
        "project": project,
        "objective": objective,
        # The synthesised advice was missing from this document entirely, which
        # meant the export omitted the one thing a reader outside the analysis
        # actually needs: what to do. Per-theory recommendations are not a
        # substitute — several of them disagree by construction.
        "advice": await get_recommendation(session, project_id),
        "theories": theories,
        "claims": {str(c.id): c for c in claims},
        "edges": {str(e.id): e for e in edges},
        "evidence": {
            str(ev.id): ev for e in edges for ev in (e.evidences or [])
        },
        "objections": objections,
        "tripwires": tripwires,
        "reference_cases": await list_reference_cases(session, project_id),
        "debates": await list_debates(session, project_id),
    }


def _chain_lines(theory: Theory, claims: dict[str, Claim]) -> list[str]:
    """The causal chain as an indented walk, so the shape is readable on paper.

    A gap where an edge was dropped is drawn as a gap. Steps that no longer join
    were being rendered as though they did, which is how a chain with invented
    junctions reached a board pack looking verified.
    """
    lines: list[str] = []
    previous_claim: str | None = None

    for step in theory.causal_chain or []:
        if not isinstance(step, dict):
            continue
        if step.get("claim_id"):
            claim = claims.get(str(step["claim_id"]))
            # Two claims in a row means the mechanism between them was dropped.
            if previous_claim is not None:
                lines.append("  - *(no verified link — the step between these "
                             "was cited but does not join them)*")
            lines.append(f"- **{claim.text if claim else step.get('label', '?')}**")
            previous_claim = str(step["claim_id"])
        elif step.get("edge_id"):
            lines.append(f"  - ↓ *{step.get('label', 'unspecified mechanism')}*")
            previous_claim = None
    return lines


def _theory_section(
    theory: Theory, data: dict[str, Any], index: int
) -> list[str]:
    """One theory in full: chain, evidence, objections, tripwires."""
    claims = data["claims"]
    evidence: dict[str, Evidence] = data["evidence"]
    objections = data["objections"].get(theory.id, [])
    tripwires = data["tripwires"].get(theory.id, [])

    live_objections = [o for o in objections if not o.dismissed]
    confidence = BAND_LABELS.get(band(theory.confidence), "not computed")

    lines = [f"## {index}. {theory.title}", ""]

    # The qualifications sit with the conclusion, not in an appendix.
    status = [
        f"**Confidence:** {confidence}",
        f"**Business impact:** {theory.business_impact}",
    ]
    if theory.contested:
        status.append(f"**⚠ Contested** — {len(live_objections)} objection(s)")
    if theory.is_stale:
        status.append("**⚠ Out of date** — the graph changed after this was generated")
    lines += [" · ".join(status), "", theory.summary, ""]

    if theory.recommendation:
        lines += ["**Recommended action.** " + theory.recommendation, ""]

    chain = _chain_lines(theory, claims)
    if chain:
        lines += ["### Causal chain", ""] + chain + [""]

    supporting = [
        evidence[str(link.evidence_id)]
        for link in theory.evidence_links
        if link.role == "supporting" and str(link.evidence_id) in evidence
    ]
    contradicting = [
        evidence[str(link.evidence_id)]
        for link in theory.evidence_links
        if link.role == "contradicting" and str(link.evidence_id) in evidence
    ]
    if supporting or contradicting:
        lines += ["### Evidence", ""]
        for ev in supporting:
            lines.append(f"- **Supports:** {ev.snippet} — *{ev.source_title}*")
        for ev in contradicting:
            lines.append(f"- **Contradicts:** {ev.snippet} — *{ev.source_title}*")
        lines.append("")

    if live_objections:
        lines += ["### Objections", ""]
        for objection in live_objections:
            kind = objection.kind.replace("_", " ")
            lines.append(f"- *[{kind}]* {objection.objection}")
        lines.append("")

    if theory.weak_assumptions:
        lines += ["### Weak assumptions", ""]
        lines += [f"- {a}" for a in theory.weak_assumptions]
        lines.append("")

    if theory.outside_view_note:
        lines += ["### Against comparable cases", "", theory.outside_view_note, ""]

    pending = [t for t in tripwires if t.status == "pending"]
    if pending:
        lines += ["### What would change this conclusion", ""]
        for tripwire in pending:
            due = tripwire.check_by.strftime("%d %B %Y") if tripwire.check_by else "—"
            verb = "would disprove" if tripwire.direction == "falsifies" else "would confirm"
            lines.append(f"- {tripwire.observable} — *{verb}, check by {due}*")
        lines.append("")

    return lines


def build_markdown(data: dict[str, Any]) -> str:
    """The brief, in a format that survives being pasted anywhere."""
    project = data["project"]
    objective = data["objective"]
    theories = data["theories"]

    generated = datetime.now(timezone.utc).strftime("%d %B %Y")
    lines = [f"# Decision brief — {project.title}", "", f"*Generated {generated}*", ""]

    decision = objective
    if decision:
        lines += ["## The decision", "", decision, ""]

    # Leads, because a reader who was not in the analysis wants the conclusion
    # before the reasoning behind it.
    advice = data["advice"]
    if advice is not None:
        lines += ["## What to do", "", f"**{advice.recommendation}**", ""]
        if advice.reasoning:
            lines += [advice.reasoning, ""]
        if advice.depends_on:
            lines += ["**This holds if:**", ""]
            lines += [f"- {item}" for item in advice.depends_on]
            lines.append("")
        if advice.against_it:
            # Beside the advice, not in an appendix: the case for doing
            # otherwise is the part most worth reading before acting.
            lines += ["**The case for doing otherwise.** " + advice.against_it, ""]
        if advice.next_step:
            lines += ["**This week.** " + advice.next_step, ""]
        lines += [f"*Support for this: {advice.confidence}*", ""]


    if data["reference_cases"]:
        lines += ["## Comparable cases", ""]
        for case in data["reference_cases"]:
            lines.append(
                f"- {case.outcome}: {case.cases_with_outcome} of "
                f"{case.cases_total} ({case.base_rate:.0%})"
            )
        lines.append("")

    if not theories:
        lines += [
            "## Theories",
            "",
            "*No theories have been generated for this project yet.*",
            "",
        ]
    else:
        lines += ["## Theories", ""]
        for index, theory in enumerate(theories, start=1):
            lines += _theory_section(theory, data, index)

    competing = [d for d in data["debates"] if d.relation == "competing"]
    if competing:
        lines += ["## Where the explanations disagree", ""]
        for debate in competing:
            if debate.crux:
                lines += [f"- {debate.crux}"]
            if debate.discriminator_feasible and debate.discriminator:
                lines += [f"  - *To tell them apart:* {debate.discriminator}"]
            elif debate.relation == "competing":
                lines += [
                    "  - *Nothing observable separates these before the deadline; "
                    "prefer the option that holds either way.*"
                ]
        lines.append("")

    # Stated plainly rather than in small print: a reader who takes these
    # numbers as measurements has misread the document.
    lines += [
        "---",
        "",
        "## How to read this",
        "",
        "Confidence is shown as a band, not a percentage. Nothing here has been "
        "calibrated against outcomes, so a decimal would imply a precision this "
        "analysis does not have.",
        "",
        "The causal links and their weights were inferred by a language model "
        "from the supplied documents and reviewed by hand. They are an argument "
        "made explicit, not a measurement.",
        "",
        "Objections were generated adversarially and may be wrong. They are "
        "included because an argument nobody has attacked has not been tested.",
        "",
    ]
    return "\n".join(lines)


def build_html(markdown: str, title: str) -> str:
    """Print-ready HTML.

    Deliberately self-contained and CSS-only: a board pack gets emailed, opened
    offline, and printed. A dependency on a CDN is a dependency on the meeting
    room having internet.
    """
    body: list[str] = []
    in_list = False

    for raw in markdown.split("\n"):
        line = raw.rstrip()
        if not line:
            if in_list:
                body.append("</ul>")
                in_list = False
            continue

        if line.startswith("- ") or line.startswith("  - "):
            if not in_list:
                body.append("<ul>")
                in_list = True
            indent = " class='sub'" if line.startswith("  - ") else ""
            body.append(f"<li{indent}>{_inline(line.lstrip(' -'))}</li>")
            continue

        if in_list:
            body.append("</ul>")
            in_list = False

        if line.startswith("### "):
            body.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            body.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            body.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("---"):
            body.append("<hr>")
        else:
            body.append(f"<p>{_inline(line)}</p>")

    if in_list:
        body.append("</ul>")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
  body {{ font: 15px/1.6 Georgia, 'Times New Roman', serif; max-width: 46em;
         margin: 3em auto; padding: 0 1.5em; color: #1a1a1a; }}
  h1 {{ font-size: 1.8em; border-bottom: 2px solid #333; padding-bottom: .3em; }}
  h2 {{ font-size: 1.3em; margin-top: 2em; }}
  h3 {{ font-size: 1.05em; margin-top: 1.4em; color: #444; }}
  ul {{ padding-left: 1.4em; }}
  li.sub {{ list-style: none; color: #555; font-size: .95em; }}
  hr {{ border: 0; border-top: 1px solid #ccc; margin: 2.5em 0; }}
  em {{ color: #555; }}
  /* Keep a theory and its objections on one page: splitting them is how a
     qualification gets lost. */
  h2 {{ page-break-after: avoid; }}
  ul {{ page-break-inside: avoid; }}
  @media print {{ body {{ margin: 0; max-width: none; }} }}
</style>
</head>
<body>
{chr(10).join(body)}
</body>
</html>"""


def _inline(text: str) -> str:
    """Escape first, then apply the small subset of inline markup we emit."""
    escaped = html.escape(text)
    for marker, tag in (("**", "strong"), ("*", "em")):
        parts = escaped.split(marker)
        if len(parts) > 2:
            rebuilt = parts[0]
            for index, part in enumerate(parts[1:], start=1):
                rebuilt += f"<{tag}>{part}</{tag}>" if index % 2 else part
            escaped = rebuilt
    return escaped


async def export_brief(
    session: AsyncSession, project_id: UUID, fmt: str = "markdown"
) -> tuple[str | bytes, str, str]:
    """Build the brief.

    Returns ``(content, media_type, filename)``.

    Raises:
        LookupError: unknown project.
        ValueError: unsupported format.
    """
    if fmt not in ("markdown", "html", "pdf"):
        raise ValueError(f"Unsupported format '{fmt}'. Use markdown, html or pdf.")

    data = await _gather(session, project_id)
    markdown = build_markdown(data)
    slug = "".join(
        c if c.isalnum() or c in "-_" else "-" for c in data["project"].title.lower()
    )[:60].strip("-") or "decision"

    logger.info(
        "Exported %s brief for project %s (%d theories)",
        fmt, project_id, len(data["theories"]),
    )

    if fmt == "markdown":
        return markdown, "text/markdown; charset=utf-8", f"{slug}-brief.md"
    if fmt == "html":
        return (
            build_html(markdown, data["project"].title),
            "text/html; charset=utf-8",
            f"{slug}-brief.html",
        )

    # Rendered from the gathered data, not from the Markdown above: parsing our
    # own output back in would make a formatting change silently become a
    # content change.
    from decision_studio.reasoning.brief_pdf import build_pdf

    return build_pdf(data), "application/pdf", f"{slug}-brief.pdf"
