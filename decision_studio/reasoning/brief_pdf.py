"""Rendering the decision brief as a PDF.

The brief already existed as Markdown and HTML. Neither survives the journey to
a meeting: Markdown is not a document anyone circulates, and an HTML file
emailed to a board member opens differently on every machine and prints badly.

A PDF is what actually gets attached to a calendar invite, so this is the format
that determines whether the qualifications reach the room or get left behind
with the tooling.

**Page one stands alone.** It carries the decision, the recommendation, what it
depends on, the case against, the next step, and a one-line-per-theory summary
of what was found — everything needed to act. The pages after it are supporting
detail for whoever wants to check the reasoning.

That split is the point. A brief that requires reading four pages before the
conclusion appears gets skimmed to the conclusion anyway, which loses the
qualifications on the way. Putting the conclusion *and* its caveats on the same
page means the reader who reads only one page still gets both.

Two further choices carry the intent of the whole system:

* **The case against sits beside the recommendation**, on page one, not in an
  appendix. Anything that can be flipped past will be, and the qualifications
  are the part most worth reading.
* **Objections stay inside their theory's block** on the detail pages, so a
  page break cannot separate a conclusion from what undermines it.

Rendered from the same data as the Markdown export rather than from the Markdown
text: parsing our own output back in would mean a formatting change silently
becoming a content change.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from decision_studio.reasoning.brief_view import (
    BriefView, build_view, outside_view_note, pct, quality_lines,
)
from decision_studio.reasoning.calibration import band

logger = logging.getLogger(__name__)

INK = colors.HexColor("#1a1a1a")
MUTED = colors.HexColor("#5a5a5a")
ACCENT = colors.HexColor("#0d5c73")
RULE = colors.HexColor("#d4d4d4")
PANEL = colors.HexColor("#f4f6f7")
CAUTION_BG = colors.HexColor("#fdf6e8")
CAUTION_EDGE = colors.HexColor("#e0c890")

BAND_LABELS = {
    "very_low": "very low",
    "low": "low",
    "moderate": "moderate",
    "high": "high",
    "very_high": "very high",
    "unknown": "not computed",
}


def _styles() -> dict[str, ParagraphStyle]:
    """The paragraph styles for the brief, built once per render."""
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "t", parent=base["Title"], fontName="Times-Bold", fontSize=22,
            leading=26, textColor=INK, alignment=TA_LEFT, spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "st", parent=base["Normal"], fontName="Times-Italic", fontSize=11,
            leading=15, textColor=MUTED, spaceAfter=14,
        ),
        "h1": ParagraphStyle(
            "h1", parent=base["Heading1"], fontName="Times-Bold", fontSize=15,
            leading=19, textColor=INK, spaceBefore=17, spaceAfter=6,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontName="Times-Bold", fontSize=11.5,
            leading=15, textColor=ACCENT, spaceBefore=11, spaceAfter=3,
        ),
        "h3": ParagraphStyle(
            "h3", parent=base["Normal"], fontName="Times-Bold", fontSize=8.5,
            leading=11, textColor=MUTED, spaceBefore=7, spaceAfter=3,
        ),
        "body": ParagraphStyle(
            "b", parent=base["Normal"], fontName="Times-Roman", fontSize=10,
            leading=14.5, textColor=INK, spaceAfter=6,
        ),
        "lead": ParagraphStyle(
            "l", parent=base["Normal"], fontName="Times-Bold", fontSize=11.5,
            leading=16, textColor=INK, spaceAfter=7,
        ),
        "meta": ParagraphStyle(
            "m", parent=base["Normal"], fontName="Times-Italic", fontSize=8.5,
            leading=12, textColor=MUTED, spaceAfter=6,
        ),
        "chain": ParagraphStyle(
            "ch", parent=base["Normal"], fontName="Times-Roman", fontSize=9.5,
            leading=13.5, textColor=INK, leftIndent=10, spaceAfter=1,
        ),
        "cell": ParagraphStyle(
            "ce", parent=base["Normal"], fontName="Times-Roman", fontSize=9,
            leading=12, textColor=INK,
        ),
        "cellh": ParagraphStyle(
            "ceh", parent=base["Normal"], fontName="Times-Bold", fontSize=8.5,
            leading=11, textColor=MUTED,
        ),
        "tile": ParagraphStyle(
            "ti", parent=base["Normal"], fontName="Times-Bold", fontSize=15,
            leading=18, textColor=ACCENT, alignment=1,
        ),
        "tilel": ParagraphStyle(
            "tl", parent=base["Normal"], fontName="Times-Roman", fontSize=7,
            leading=9, textColor=MUTED, alignment=1,
        ),
        "mech": ParagraphStyle(
            "me", parent=base["Normal"], fontName="Times-Italic", fontSize=9,
            leading=13, textColor=MUTED, leftIndent=22, spaceAfter=1,
        ),
    }


def _escape(text: Any) -> str:
    """Escape for reportlab's mini-markup.

    Claim text comes from uploaded documents and routinely contains ampersands
    and angle brackets; unescaped, one of them silently truncates a paragraph.
    """
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _panel(flowables: list, tint=PANEL, edge=RULE) -> Table:
    """A tinted block. Used for the recommendation and the caveats, which are
    the two things that must not read as body text.
    """
    t = Table([[flowables]], colWidths=[16.0 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), tint),
        ("BOX", (0, 0), (-1, -1), 0.5, edge),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _bullets(items: list[str], style: ParagraphStyle) -> ListFlowable:
    """A bulleted list in the given style."""
    return ListFlowable(
        [ListItem(Paragraph(_escape(i), style), leftIndent=13) for i in items],
        bulletType="bullet", bulletFontSize=8, bulletOffsetY=-1,
        leftIndent=13, spaceAfter=6,
    )


def _theory_block(theory, data: dict[str, Any], index: int, S) -> list:
    """One theory, whole. Kept together so its qualifications cannot be
    separated from its conclusion by a page break."""
    claims = data["claims"]
    objections = [o for o in data["objections"].get(theory.id, []) if not o.dismissed]
    tripwires = [
        t for t in data["tripwires"].get(theory.id, []) if t.status == "pending"
    ]

    out: list = [Paragraph(f"{index}. {_escape(theory.title)}", S["h2"])]

    meta = [
        f"Confidence: {BAND_LABELS.get(band(theory.confidence), 'not computed')}",
        f"Impact: {_escape(theory.business_impact)}",
    ]
    if theory.contested:
        meta.append(f"<b>Contested</b> — {len(objections)} objection(s)")
    if theory.is_stale:
        meta.append("<b>Out of date</b> — the graph changed after this was written")
    out.append(Paragraph(" · ".join(meta), S["meta"]))
    if getattr(theory, "option_key", None):
        effect = {"achieves": "achieves", "threatens": "threatens"}.get(
            theory.predicted_effect or "", "has an unclear effect on")
        reach = "" if theory.reaches_outcome else " — its chain does not reach a success criterion"
        out.append(Paragraph(
            f"<b>A theory of {_escape(theory.option_key)}:</b> choosing it {effect} the outcome{reach}.",
            S["meta"],
        ))
    conviction = data.get("convictions", {}).get(str(theory.theory_key))
    if conviction is not None and conviction.current is not None:
        out.append(Paragraph(
            f"<b>Decider's conviction:</b> {pct(conviction.current)} (stated {pct(conviction.prior)})",
            S["meta"],
        ))
    out.append(Paragraph(_escape(theory.summary), S["body"]))

    chain = theory.causal_chain or []
    if chain:
        out.append(Paragraph("HOW IT WORKS", S["h3"]))
        for step in chain:
            if not isinstance(step, dict):
                continue
            if step.get("claim_id"):
                claim = claims.get(str(step["claim_id"]))
                out.append(Paragraph(
                    _escape(claim.text if claim else step.get("label", "?")),
                    S["chain"],
                ))
            elif step.get("edge_id"):
                out.append(Paragraph(
                    "↓ " + _escape(step.get("label", "unspecified mechanism")),
                    S["mech"],
                ))

    if theory.recommendation:
        out.append(Paragraph("WHAT THIS IMPLIES", S["h3"]))
        out.append(Paragraph(_escape(theory.recommendation), S["body"]))

    if objections:
        out.append(Paragraph("WHAT ARGUES AGAINST IT", S["h3"]))
        out.append(_bullets(
            [f"[{o.kind.replace('_', ' ')}] {o.objection}" for o in objections],
            S["body"],
        ))

    if theory.weak_assumptions:
        out.append(Paragraph("WEAK ASSUMPTIONS", S["h3"]))
        out.append(_bullets(list(theory.weak_assumptions), S["body"]))

    outside = outside_view_note(theory, data)
    if outside:
        out.append(Paragraph("AGAINST COMPARABLE CASES", S["h3"]))
        out.append(Paragraph(_escape(outside), S["body"]))

    if tripwires:
        out.append(Paragraph("WHAT WOULD PROVE THIS WRONG", S["h3"]))
        out.append(_bullets(
            [
                f"{t.observable}"
                + (f" — check by {t.check_by.strftime('%d %B %Y')}" if t.check_by else "")
                for t in tripwires
            ],
            S["body"],
        ))

    out.append(Spacer(1, 0.2 * cm))
    return out


def _key_numbers(view: BriefView, S) -> Table:
    """Four tiles: what a reader scans before reading anything."""
    cells = [[
        [Paragraph(_escape(value), S["tile"]), Paragraph(_escape(label.upper()), S["tilel"])]
        for label, value in view.key_numbers
    ]]
    t = Table(cells, colWidths=[4.0 * cm] * 4)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("BOX", (0, 0), (-1, -1), 0.5, RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _option_cell(line, S) -> Paragraph:
    if line is None:
        return Paragraph("—", S["cell"])
    extra = f"<br/><i>support {line.support}"
    if line.conviction is not None:
        extra += f"; your conviction {pct(line.conviction)}"
    extra += "</i>"
    return Paragraph(_escape(line.title) + extra, S["cell"])


def _options_table(view: BriefView, S) -> Table:
    """One row per option: the strongest case each way, and whether it was examined."""
    status_colour = {"Not examined": "#8a5a00", "Contested": "#0d5c73"}
    rows = [[Paragraph(h, S["cellh"]) for h in
             ("Option", "Strongest case for", "Strongest case against", "Status")]]
    for row in view.options:
        colour = status_colour.get(row.status, "#1a1a1a")
        rows.append([
            Paragraph(f"<b>{_escape(row.key)}</b> {_escape(row.label)}", S["cell"]),
            _option_cell(row.case_for, S),
            _option_cell(row.case_against, S),
            Paragraph(f'<font color="{colour}"><b>{_escape(row.status)}</b></font>', S["cell"]),
        ])
    t = Table(rows, colWidths=[3.2 * cm, 5.2 * cm, 5.2 * cm, 2.4 * cm], repeatRows=1)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND", (0, 0), (-1, 0), PANEL),
        ("LINEBELOW", (0, 0), (-1, 0), 0.7, MUTED),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, RULE),
    ]))
    return t


def _executive_summary(view: BriefView, S) -> list:
    """Page one: everything needed to act, and nothing that needs a page turn.

    Deliberately dense. A reader who reads only this page must come away with
    the recommendation, what it rests on, the strongest reason not to follow it,
    how each option fared, and what could still change the answer.
    """
    out: list = []
    if view.decision:
        out += [Paragraph("THE DECISION", S["h3"]), Paragraph(_escape(view.decision), S["lead"])]
    facts = []
    if view.deadline:
        facts.append(f"<b>Decide by:</b> {_escape(view.deadline)}")
    if view.constraints:
        facts.append("<b>Hard constraints:</b> " + _escape("; ".join(view.constraints)))
    if facts:
        out.append(Paragraph(" · ".join(facts), S["body"]))
    out.append(Spacer(1, 0.1 * cm))

    advice = view.advice
    if advice is not None:
        panel_items = [
            Paragraph("RECOMMENDATION", S["h3"]),
            Paragraph(_escape(advice.recommendation), S["lead"]),
        ]
        if advice.reasoning:
            panel_items.append(Paragraph(_escape(advice.reasoning), S["body"]))
        if advice.depends_on:
            panel_items.append(Paragraph("THIS HOLDS IF", S["h3"]))
            panel_items.append(_bullets(list(advice.depends_on)[:4], S["body"]))
        if advice.against_it:
            panel_items.append(Paragraph("THE CASE FOR DOING OTHERWISE", S["h3"]))
            panel_items.append(Paragraph(_escape(advice.against_it), S["body"]))
        if advice.next_step:
            panel_items.append(Paragraph(
                "<b>Next step this week.</b> " + _escape(advice.next_step), S["body"]
            ))
        panel_items.append(Paragraph(
            f"Support for this recommendation: <b>{_escape(advice.confidence)}</b>", S["meta"]
        ))
        out += [_panel(panel_items), Spacer(1, 0.25 * cm)]
    elif view.theories:
        out += [
            _panel([
                Paragraph("NO RECOMMENDATION WAS SYNTHESISED", S["h3"]),
                Paragraph(
                    "The theories below were found but not weighed against each "
                    "other. Read them individually.", S["body"],
                ),
            ], tint=CAUTION_BG, edge=CAUTION_EDGE),
            Spacer(1, 0.25 * cm),
        ]

    out += [_key_numbers(view, S), Spacer(1, 0.3 * cm)]

    if view.options:
        out += [Paragraph("OPTIONS AT A GLANCE", S["h3"]), _options_table(view, S),
                Spacer(1, 0.2 * cm)]

    if view.warnings:
        out += [_panel(
            [Paragraph("BEFORE RELYING ON THIS", S["h3"]), _bullets(view.warnings, S["body"])],
            tint=CAUTION_BG, edge=CAUTION_EDGE,
        )]
    return out


def _tests_section(view: BriefView, S) -> list:
    """What could still change the answer, as a list someone can commission."""
    out: list = [Paragraph("What would change the decision", S["h1"])]
    if view.tests:
        out.append(Paragraph(
            "Run these before committing. Tests on links are ranked by how much the "
            "outcome depends on the link and how little is known about it; tripwires "
            "are the observations agreed in advance, with the date to check.",
            S["meta"],
        ))
        kinds = {"link": "TEST", "tripwire": "WATCH FOR", "field": "FIELD TEST"}
        for item in view.tests[:8]:
            block = [Paragraph(
                f"<b>{kinds[item.kind]}</b> · " + _escape(item.what)
                + (f" — <b>check by {item.due.strftime('%d %B %Y')}</b>" if item.due else ""),
                S["body"],
            )]
            if item.wrong_if and item.kind != "tripwire":
                block.append(Paragraph("<i>Wrong if:</i> " + _escape(item.wrong_if), S["chain"]))
            if item.how:
                block.append(Paragraph("<i>How:</i> " + _escape(item.how), S["chain"]))
            if item.theory_title:
                block.append(Paragraph("<i>Bears on:</i> " + _escape(item.theory_title), S["mech"]))
            block.append(Spacer(1, 0.15 * cm))
            out.append(KeepTogether(block))
    else:
        out.append(Paragraph(
            "No test or tripwire is recorded. Without one, nothing observed before the "
            "deadline can change this analysis — the decision rests on judgement alone.",
            S["body"],
        ))

    if view.conviction_trail:
        out.append(Paragraph("HOW THE DECIDER'S CONVICTION HAS MOVED", S["h3"]))
        out.append(Paragraph(
            "Conviction is the decider's own stated belief in a theory, kept apart from "
            "the model's confidence and updated only by observed results.", S["meta"],
        ))
        rows = [[Paragraph(h, S["cellh"]) for h in ("Theory", "Stated", "Now", "Observations")]]
        for line, conviction in view.conviction_trail:
            rows.append([
                Paragraph(_escape(line.title), S["cell"]),
                Paragraph(pct(conviction.prior), S["cell"]),
                Paragraph(f"<b>{pct(conviction.current)}</b>", S["cell"]),
                Paragraph(str(len([s for s in conviction.steps if s.applied])), S["cell"]),
            ])
        t = Table(rows, colWidths=[9.2 * cm, 1.8 * cm, 1.8 * cm, 3.2 * cm])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (-1, 0), PANEL),
            ("LINEBELOW", (0, 0), (-1, 0), 0.7, MUTED),
            ("LINEBELOW", (0, 1), (-1, -2), 0.3, RULE),
        ]))
        out.append(t)
    return out


def build_pdf(data: dict[str, Any]) -> bytes:
    """Render the brief: executive summary, what would change it, then the reasoning."""
    S = _styles()
    view = build_view(data)
    project = data["project"]
    theories = data["theories"]

    story: list = [
        Paragraph(_escape(project.title), S["title"]),
        Paragraph(
            "Decision brief · generated "
            + datetime.now(timezone.utc).strftime("%d %B %Y"),
            S["subtitle"],
        ),
        HRFlowable(width="100%", thickness=0.5, color=RULE, spaceAfter=10),
    ]
    story += _executive_summary(view, S)

    # ── What could still change it ──────────────────────────────────────────
    story.append(PageBreak())
    story += _tests_section(view, S)

    # ── The reasoning, grouped by option ────────────────────────────────────
    if theories:
        story.append(PageBreak())
        story.append(Paragraph("The theories in full", S["h1"]))
        story.append(Paragraph(
            "Grouped by the option each argues about: the causal chain step by step, "
            "what argues against it, and what would prove it wrong.",
            S["meta"],
        ))
        for row in view.options:
            bound = [l for l in view.theories if getattr(l.theory, "option_key", None) == row.key]
            if not bound:
                continue
            story.append(Paragraph(f"Option {_escape(row.key)}: {_escape(row.label)}", S["h1"]))
            for line in bound:
                story.append(KeepTogether(_theory_block(line.theory, data, line.index, S)))
        if view.situational:
            if view.options:
                story.append(Paragraph("Conditions that bear on every option", S["h1"]))
            for line in view.situational:
                story.append(KeepTogether(_theory_block(line.theory, data, line.index, S)))

    competing = [d for d in data.get("debates", []) if d.relation == "competing"]
    if competing:
        story.append(Paragraph("Where the explanations disagree", S["h1"]))
        for debate in competing:
            if debate.crux:
                story.append(Paragraph(_escape(debate.crux), S["body"]))
            if debate.discriminator_feasible and debate.discriminator:
                story.append(Paragraph(
                    "<i>To tell them apart:</i> " + _escape(debate.discriminator),
                    S["chain"],
                ))
            else:
                story.append(Paragraph(
                    "<i>Nothing observable separates these before the deadline; "
                    "prefer the option that holds either way.</i>",
                    S["chain"],
                ))

    if data.get("reference_cases"):
        story.append(Paragraph("Comparable cases", S["h1"]))
        story.append(_bullets(
            [
                f"{c.outcome}: {c.cases_with_outcome} of {c.cases_total} "
                f"({c.base_rate:.0%})"
                for c in data["reference_cases"]
            ],
            S["body"],
        ))

    # ── Appendix ────────────────────────────────────────────────────────────
    story.append(Paragraph("Appendix: quality of the analysis", S["h1"]))
    story.append(_bullets(quality_lines(view.graph_metrics), S["body"]))
    story.append(_panel([
        Paragraph("HOW TO READ THIS", S["h3"]),
        Paragraph(
            "Support is a band, not a percentage — nothing here has been calibrated "
            "against outcomes. Conviction percentages are the decider's own stated "
            "beliefs, updated by Bayes' rule only from observed results. The causal "
            "links were inferred by a language model from the supplied documents and "
            "reviewed by hand: this is an argument made explicit, not a measurement. "
            "Objections were generated adversarially and may themselves be wrong; they "
            "are included because an argument nobody has attacked has not been tested.",
            S["body"],
        ),
    ], tint=CAUTION_BG, edge=CAUTION_EDGE))

    def footer(canvas, doc):
        """Project title on the left, page number on the right."""
        canvas.saveState()
        canvas.setFont("Times-Roman", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(2.2 * cm, 1.2 * cm, _escape(project.title)[:70])
        canvas.drawRightString(A4[0] - 2.2 * cm, 1.2 * cm, str(doc.page))
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.4)
        canvas.line(2.2 * cm, 1.6 * cm, A4[0] - 2.2 * cm, 1.6 * cm)
        canvas.restoreState()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=2.2 * cm, rightMargin=2.2 * cm,
        topMargin=2.0 * cm, bottomMargin=2.0 * cm,
        title=f"{project.title} — decision brief",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)

    logger.info(
        "Rendered PDF brief for project %s (%d theories)", project.id, len(theories)
    )
    return buffer.getvalue()
