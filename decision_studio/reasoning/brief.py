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
    Experiment,
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
from decision_studio.reasoning.decision_anchor import normalise_anchor
from decision_studio.reasoning.effective_graph import filter_effective
from decision_studio.reasoning.link_tests import list_hypotheses
from decision_studio.reasoning.theory_value import convictions
from decision_studio.tools.anchor_report import compute_report
from decision_studio.reasoning.brief_view import (
    TestItem, TheoryLine, build_view, outside_view_note, pct, quality_lines,
)

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

    # Theory-of-value material: the anchor, the decider's conviction, and the
    # tests that could still change the answer.
    anchor = normalise_anchor(project.decision_anchor)
    theory_keys = [t.theory_key for t in theories]
    field_tests: dict[UUID, list[Experiment]] = {}
    if theory_ids:
        for row in (
            await session.execute(
                select(Experiment).where(
                    Experiment.theory_id.in_(theory_ids), Experiment.kind == "field"
                )
            )
        ).scalars().all():
            field_tests.setdefault(row.theory_id, []).append(row)

    # How solid the analysis itself is, measured on the reviewed graph.
    active_claims, active_edges = filter_effective(list(claims), list(edges))
    graph_metrics = compute_report(
        [
            {"id": str(c.id), "origin": c.origin, "decision_role": c.decision_role,
             "relevance": c.relevance}
            for c in active_claims
        ],
        [
            {"source": str(e.source_claim_id), "target": str(e.target_claim_id)}
            for e in active_edges if not e.is_feedback
        ],
        {str(t.id): {str(link.claim_id) for link in t.claim_links} for t in theories},
        anchor,
    )

    return {
        "project": project,
        "objective": objective,
        "anchor": anchor,
        "convictions": await convictions(session, project_id, theory_keys),
        "hypotheses": await list_hypotheses(session, project_id),
        "field_tests": field_tests,
        "graph_metrics": graph_metrics,
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

    lines = [f"### {index}. {theory.title}", ""]

    # The qualifications sit with the conclusion, not in an appendix.
    status = [
        f"**Confidence:** {confidence}",
        f"**Business impact:** {theory.business_impact}",
    ]
    if theory.contested:
        status.append(f"**⚠ Contested** — {len(live_objections)} objection(s)")
    if theory.is_stale:
        status.append("**⚠ Out of date** — the graph changed after this was generated")
    lines += [" · ".join(status), ""]
    if getattr(theory, "option_key", None):
        effect = {"achieves": "achieves", "threatens": "threatens"}.get(
            theory.predicted_effect or "", "has an unclear effect on")
        reach = "" if theory.reaches_outcome else " — *its chain does not reach a success criterion*"
        lines += [f"*A theory of {theory.option_key}: choosing it {effect} the outcome{reach}.*", ""]
    conviction = data.get("convictions", {}).get(str(theory.theory_key))
    if conviction is not None and conviction.current is not None:
        lines += [f"*Decider's conviction: {pct(conviction.current)}"
                  f" (stated {pct(conviction.prior)}).*", ""]
    lines += [theory.summary, ""]

    if theory.recommendation:
        lines += ["**Recommended action.** " + theory.recommendation, ""]

    chain = _chain_lines(theory, claims)
    if chain:
        lines += ["#### Causal chain", ""] + chain + [""]

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
        lines += ["#### Evidence", ""]
        for ev in supporting:
            lines.append(f"- **Supports:** {ev.snippet} — *{ev.source_title}*")
        for ev in contradicting:
            lines.append(f"- **Contradicts:** {ev.snippet} — *{ev.source_title}*")
        lines.append("")

    if live_objections:
        lines += ["#### Objections", ""]
        for objection in live_objections:
            kind = objection.kind.replace("_", " ")
            lines.append(f"- *[{kind}]* {objection.objection}")
        lines.append("")

    if theory.weak_assumptions:
        lines += ["#### Weak assumptions", ""]
        lines += [f"- {a}" for a in theory.weak_assumptions]
        lines.append("")

    outside = outside_view_note(theory, data)
    if outside:
        lines += ["#### Against comparable cases", "", outside, ""]

    pending = [t for t in tripwires if t.status == "pending"]
    if pending:
        lines += ["#### What would change this conclusion", ""]
        for tripwire in pending:
            due = tripwire.check_by.strftime("%d %B %Y") if tripwire.check_by else "—"
            verb = "would disprove" if tripwire.direction == "falsifies" else "would confirm"
            lines.append(f"- {tripwire.observable} — *{verb}, check by {due}*")
        lines.append("")

    return lines


def _test_line(item: TestItem) -> str:
    """One test, in the words an executive would use to commission it."""
    due = f" — **check by {item.due.strftime('%d %B %Y')}**" if item.due else ""
    kind = {"link": "Test", "tripwire": "Watch for", "field": "Field test"}[item.kind]
    parts = [f"- **{kind}:** {item.what}{due}"]
    if item.wrong_if and item.kind != "tripwire":
        parts.append(f"  - *Wrong if:* {item.wrong_if}")
    if item.how:
        parts.append(f"  - *How:* {item.how}")
    if item.theory_title:
        parts.append(f"  - *Bears on:* {item.theory_title}")
    return "\n".join(parts)


def _option_cell(line: TheoryLine | None) -> str:
    if line is None:
        return "—"
    conviction = f"; your conviction {pct(line.conviction)}" if line.conviction is not None else ""
    return f"{line.title} (support {line.support}{conviction})"


def build_markdown(data: dict[str, Any]) -> str:
    """The executive brief, answer first, in a format that survives pasting."""
    view = build_view(data)
    generated = datetime.now(timezone.utc).strftime("%d %B %Y")
    lines = [f"# Decision brief — {view.title}", "", f"*Generated {generated}*", ""]

    # ── 1. The answer ───────────────────────────────────────────────────────
    lines += ["## Executive summary", ""]
    if view.decision:
        lines += [f"**The decision.** {view.decision}", ""]
    facts = []
    if view.deadline:
        facts.append(f"**Decide by:** {view.deadline}")
    if view.constraints:
        facts.append("**Hard constraints:** " + "; ".join(view.constraints))
    if facts:
        lines += [" · ".join(facts), ""]

    advice = view.advice
    if advice is not None:
        lines += [f"**Recommendation: {advice.recommendation}**", ""]
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
            lines += ["**Next step this week.** " + advice.next_step, ""]
        lines += [f"*Support for this recommendation: {advice.confidence}*", ""]

    lines += [" · ".join(f"**{k}:** {v}" for k, v in view.key_numbers), ""]

    if view.warnings:
        lines += ["**Before relying on this:**", ""]
        lines += [f"- {w}" for w in view.warnings]
        lines.append("")

    # ── 2. The options ──────────────────────────────────────────────────────
    if view.options:
        lines += ["## Options at a glance", "",
                  "| Option | Strongest case for | Strongest case against | Status |",
                  "|---|---|---|---|"]
        for row in view.options:
            lines.append(
                f"| {row.key} {row.label} | {_option_cell(row.case_for)} | "
                f"{_option_cell(row.case_against)} | {row.status} |"
            )
        lines.append("")

    # ── 3. What would change it ─────────────────────────────────────────────
    if view.tests or view.conviction_trail:
        lines += ["## What would change the decision", ""]
    if view.tests:
        lines += ["Run these before committing — they are ranked by how much the "
                  "answer depends on them and how little is known.", ""]
        lines += [_test_line(item) for item in view.tests[:8]]
        lines.append("")
    if view.conviction_trail:
        lines += ["**How the decider's conviction has moved** (stated belief, updated "
                  "only by observations):", ""]
        for line, conviction in view.conviction_trail:
            moved = f" → {pct(conviction.current)}" if conviction.current != conviction.prior else ""
            evidence = len([s for s in conviction.steps if s.applied])
            lines.append(f"- {line.title}: {pct(conviction.prior)}{moved} "
                         f"({evidence} observation(s))")
        lines.append("")

    # ── 4. The reasoning ────────────────────────────────────────────────────
    if not view.theories:
        lines += ["## The theories", "", "*No theories have been generated for this project yet.*", ""]
    for row in view.options:
        bound = [l for l in view.theories if getattr(l.theory, "option_key", None) == row.key]
        if not bound:
            continue
        lines += [f"## The theories on {row.key}: {row.label}", ""]
        for line in bound:
            lines += _theory_section(line.theory, data, line.index)
    if view.situational:
        lines += ["## Conditions that bear on every option" if view.options else "## The theories", ""]
        for line in view.situational:
            lines += _theory_section(line.theory, data, line.index)

    competing = [d for d in data["debates"] if d.relation == "competing"]
    if competing:
        lines += ["## Where the explanations disagree", ""]
        for debate in competing:
            if debate.crux:
                lines += [f"- {debate.crux}"]
            if debate.discriminator_feasible and debate.discriminator:
                lines += [f"  - *To tell them apart:* {debate.discriminator}"]
            else:
                lines += [
                    "  - *Nothing observable separates these before the deadline; "
                    "prefer the option that holds either way.*"
                ]
        lines.append("")

    if data["reference_cases"]:
        lines += ["## Comparable cases", ""]
        for case in data["reference_cases"]:
            lines.append(
                f"- {case.outcome}: {case.cases_with_outcome} of "
                f"{case.cases_total} ({case.base_rate:.0%})"
            )
        lines.append("")

    # ── Appendix: how solid is the analysis ────────────────────────────────
    lines += ["---", "", "## Appendix: quality of the analysis", ""]
    lines += [f"- {text}" for text in quality_lines(view.graph_metrics)]
    lines += [
        "",
        "Support is shown as a band, not a percentage. Nothing here has been "
        "calibrated against outcomes, so a decimal would imply a precision this "
        "analysis does not have. Conviction percentages are the decider's own "
        "stated beliefs, updated by Bayes' rule only from observed test results.",
        "",
        "The causal links were inferred by a language model from the supplied "
        "documents and reviewed by hand. They are an argument made explicit, not "
        "a measurement. Objections were generated adversarially and may be wrong; "
        "they are included because an argument nobody has attacked has not been "
        "tested.",
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
    table: list[list[str]] = []

    def flush_table() -> None:
        # Header row, a |---| separator, then data rows.
        if not table:
            return
        head, *rows = [r for r in table if not all(set(c) <= set("-: ") for c in r)]
        body.append("<table><thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in head)
                    + "</tr></thead><tbody>")
        for row in rows:
            body.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>")
        body.append("</tbody></table>")
        table.clear()

    for raw in markdown.split("\n"):
        line = raw.rstrip()
        if line.startswith("|") and line.endswith("|"):
            table.append([c.strip() for c in line.strip("|").split("|")])
            continue
        flush_table()
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

        if line.startswith("#### "):
            body.append(f"<h4>{_inline(line[5:])}</h4>")
        elif line.startswith("### "):
            body.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            body.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            body.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("---"):
            body.append("<hr>")
        else:
            body.append(f"<p>{_inline(line)}</p>")

    flush_table()
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
  h3 {{ font-size: 1.1em; margin-top: 1.6em; color: #0d5c73; }}
  h4 {{ font-size: .95em; margin-top: 1.1em; color: #444; text-transform: uppercase;
        letter-spacing: .03em; }}
  ul {{ padding-left: 1.4em; }}
  li.sub {{ list-style: none; color: #555; font-size: .95em; }}
  hr {{ border: 0; border-top: 1px solid #ccc; margin: 2.5em 0; }}
  em {{ color: #555; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .9em; margin: 1em 0; }}
  th, td {{ border-bottom: 1px solid #ddd; padding: .4em .5em; text-align: left;
            vertical-align: top; }}
  th {{ background: #f4f6f7; color: #444; }}
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
