"""What the executive brief says, derived once for every format.

The brief is read by managers and executives who were not in the analysis and
will give it a few minutes. So it is ordered the way they decide, not the way
the analysis ran:

1. **The answer**: the decision, the recommendation, how well supported it is,
   what it depends on, the case against, and the next step.
2. **The options**: for each option on the table, the strongest case for it and
   against it, and whether it was examined at all.
3. **What would change it**: the tests worth running first, the tripwires with
   their dates, and how the decider's own conviction has moved.
4. **The reasoning**: theories grouped by option, then how solid the analysis
   itself is.

Every derived judgement here is a count or a selection: nothing is scored that
the analysis did not score. The Markdown and PDF renderers both read this view,
so the two formats cannot disagree about what the brief says.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from decision_studio.reasoning.calibration import band
from decision_studio.reasoning.outside_view import current_comparison

BAND_LABELS = {
    "very_low": "very low",
    "low": "low",
    "moderate": "moderate",
    "high": "high",
    "very_high": "very high",
    "unknown": "not computed",
}


def band_label(value: float | None) -> str:
    return BAND_LABELS.get(band(value), "not computed")


def pct(value: float | None) -> str:
    return "—" if value is None else f"{round(value * 100)}%"


def outside_view_note(theory: Any, data: dict[str, Any]) -> str | None:
    """The comparable-cases note, against the decider's conviction as it is now."""
    conviction = data.get("convictions", {}).get(str(theory.theory_key))
    return current_comparison(theory, conviction.current if conviction else None)[1]


@dataclass
class TheoryLine:
    """One theory, as the summary tables show it."""

    index: int
    theory: Any
    support: str
    conviction: float | None
    conviction_prior: float | None
    live_objections: int
    reaches_outcome: bool

    @property
    def title(self) -> str:
        return self.theory.title


@dataclass
class OptionRow:
    """An option on the table and what the analysis found about it."""

    key: str
    label: str
    case_for: TheoryLine | None
    case_against: TheoryLine | None
    theories_for: int
    theories_against: int

    @property
    def status(self) -> str:
        if not (self.theories_for or self.theories_against):
            return "Not examined"
        if self.theories_for and self.theories_against:
            return "Contested"
        return "Only a case for" if self.theories_for else "Only a case against"


@dataclass
class TestItem:
    """Something that could be observed before deciding, and what it would do."""

    kind: str  # link, tripwire, field
    what: str
    wrong_if: str | None
    how: str | None
    due: datetime | None
    theory_title: str


@dataclass
class BriefView:
    title: str
    decision: str | None
    deadline: str | None
    constraints: list[str]
    advice: Any
    theories: list[TheoryLine]
    options: list[OptionRow]
    situational: list[TheoryLine]
    tests: list[TestItem]
    conviction_trail: list[tuple[TheoryLine, Any]]
    warnings: list[str]
    key_numbers: list[tuple[str, str]]
    graph_metrics: dict[str, Any] = field(default_factory=dict)
    forecast: "Forecast | None" = None


STATUS_NOTES = {
    "modelled": "",
    "only_as_alternative": "modelled only as not choosing the others",
    "no_path": "what it involves does not reach a success criterion on the map",
    "not_modelled": "nothing in the map describes what it involves",
}


@dataclass
class Forecast:
    """What the causal map predicts for each option, ready to print."""

    #: Column headers: one per success criterion.
    outcomes: list[str]
    #: (option, cells per outcome, best-in share, note)
    rows: list[tuple[str, list[str], str, str]]
    headline: str
    caveat: str = (
        "Each option was applied to the reviewed causal map (its levers switched "
        "on, the other options' switched off) and the map propagated. Figures are "
        "the map's belief in each success criterion, with the range when every "
        "link strength is varied within its uncertainty; \"best in\" is the share "
        "of those variations in which the option came out ahead. It is what the "
        "map implies, not a forecast of the world."
    )


def build_forecast(data: dict[str, Any] | None) -> Forecast | None:
    """The comparison from reasoning/option_comparison.py, as sentences and cells."""
    if not data or not data.get("options"):
        return None
    labels = {o["key"]: o["label"] for o in data["options"]}
    if data.get("unavailable"):
        return Forecast(outcomes=[], rows=[], headline=data["unavailable"])
    outcomes = data.get("outcomes", [])
    rows = []
    for option in data["options"]:
        cells = []
        for outcome in outcomes:
            stats = option["outcomes"].get(outcome["key"])
            cells.append(
                "—" if not stats else
                f"{pct(stats['point'])} ({pct(stats['p10'])}–{pct(stats['p90'])})"
            )
        rows.append((
            f"{option['key']} {option['label']}", cells,
            pct(option.get("p_best")), STATUS_NOTES.get(option["status"], ""),
        ))
    ranked = sorted(data["options"], key=lambda o: o.get("p_best") or 0.0, reverse=True)
    leader = ranked[0]
    if data.get("decisive"):
        headline = (f"On the causal map, {leader['key']} ({labels[leader['key']]}) comes "
                    f"out ahead in {pct(leader['p_best'])} of simulations.")
    else:
        headline = (f"The causal map does not separate the options reliably: the "
                    f"leader, {leader['key']}, is ahead in only {pct(leader['p_best'])} "
                    "of simulations.")
    return Forecast(outcomes=[o["label"] for o in outcomes], rows=rows, headline=headline)


def _rank_key(line: TheoryLine) -> tuple:
    """Strongest first: the decider's conviction when stated, else the model's
    objection-discounted score. Conviction leads because it is the only number
    here that observations have moved."""
    score = line.theory.adjusted_score
    if score is None:
        score = line.theory.confidence or 0.0
    return (line.conviction is not None, line.conviction or 0.0, score)


def build_view(data: dict[str, Any]) -> BriefView:
    """Derive the brief from the data gathered in ``brief._gather``."""
    anchor = data.get("anchor") or {}
    convictions = data.get("convictions", {})
    theories = data["theories"]

    lines: list[TheoryLine] = []
    for index, theory in enumerate(theories, start=1):
        conviction = convictions.get(str(theory.theory_key))
        live = [o for o in data["objections"].get(theory.id, []) if not o.dismissed]
        lines.append(TheoryLine(
            index=index,
            theory=theory,
            support=band_label(theory.adjusted_score if theory.adjusted_score is not None else theory.confidence),
            conviction=conviction.current if conviction else None,
            conviction_prior=conviction.prior if conviction else None,
            live_objections=len(live),
            reaches_outcome=bool(getattr(theory, "reaches_outcome", False)),
        ))

    options: list[OptionRow] = []
    for option in anchor.get("options", []):
        bound = [line for line in lines if getattr(line.theory, "option_key", None) == option["key"]]
        pro = sorted((l for l in bound if l.theory.predicted_effect == "achieves"), key=_rank_key, reverse=True)
        con = sorted((l for l in bound if l.theory.predicted_effect == "threatens"), key=_rank_key, reverse=True)
        options.append(OptionRow(
            key=option["key"], label=option["label"],
            case_for=pro[0] if pro else None, case_against=con[0] if con else None,
            theories_for=len(pro), theories_against=len(con),
        ))
    option_keys = {o["key"] for o in anchor.get("options", [])}
    situational = [
        line for line in lines if getattr(line.theory, "option_key", None) not in option_keys
    ]

    tests: list[TestItem] = []
    by_key = {str(line.theory.theory_key): line for line in lines}
    for hypothesis in data.get("hypotheses", []):
        if hypothesis.status != "open":
            continue
        owner = by_key.get(str(hypothesis.theory_key))
        tests.append(TestItem(
            kind="link", what=hypothesis.statement, wrong_if=hypothesis.refuted_if,
            how=hypothesis.cheapest_test or None, due=None,
            theory_title=owner.title if owner else "",
        ))
    for line in lines:
        for tripwire in data["tripwires"].get(line.theory.id, []):
            if tripwire.status != "pending":
                continue
            tests.append(TestItem(
                kind="tripwire", what=tripwire.observable,
                wrong_if=None if tripwire.direction == "confirms" else tripwire.observable,
                how=None, due=tripwire.check_by, theory_title=line.title,
            ))
        for experiment in data.get("field_tests", {}).get(line.theory.id, []):
            if experiment.status == "designed" and experiment.design:
                tests.append(TestItem(
                    kind="field", what=experiment.hypothesis, wrong_if=experiment.measure,
                    how=experiment.design, due=None, theory_title=line.title,
                ))

    trail = [
        (line, convictions[str(line.theory.theory_key)])
        for line in lines
        if str(line.theory.theory_key) in convictions
        and convictions[str(line.theory.theory_key)].prior is not None
    ]

    warnings: list[str] = []
    unexamined = [o for o in options if o.status == "Not examined"]
    if unexamined:
        warnings.append(
            "No theory examines " + ", ".join(f"{o.key} ({o.label})" for o in unexamined)
            + ". The analysis says nothing for or against it, so the recommendation "
            "does not compare it."
        )
    if data.get("advice") is None and lines:
        warnings.append("No recommendation has been synthesised; the theories below "
                        "were not weighed against each other.")
    stale = [line for line in lines if line.theory.is_stale]
    if stale:
        warnings.append(f"{len(stale)} theory(ies) are out of date: the graph or a test "
                        "result changed after they were written.")
    if anchor and lines and not any(line.reaches_outcome for line in lines):
        warnings.append("No theory's causal chain reaches a success criterion: the "
                        "theories describe the situation more than they bear on the choice.")
    if not anchor and not data.get("objective"):
        warnings.append("No decision was stated, so the analysis describes the "
                        "situation rather than answering a choice.")

    forecast = build_forecast(data.get("option_forecast"))
    forecast_data = data.get("option_forecast") or {}
    if forecast is not None and forecast_data.get("unavailable") and len(options) > 1:
        warnings.append("The options could not be compared on the causal map: "
                        + forecast_data["unavailable"])

    examined = sum(1 for o in options if o.status != "Not examined")
    contested = sum(1 for line in lines if line.theory.contested)
    next_due = min((t.due for t in tests if t.due), default=None)
    key_numbers = [
        ("Options examined", f"{examined} of {len(options)}" if options else "—"),
        ("Theories", f"{len(lines)}" + (f" ({contested} contested)" if contested else "")),
        ("Open tests", str(len(tests))),
        ("Next check", next_due.strftime("%d %b %Y") if next_due else "—"),
        ("Map favours", _map_favours(forecast_data)),
    ]

    return BriefView(
        title=data["project"].title,
        decision=anchor.get("decision") or data.get("objective"),
        deadline=anchor.get("deadline") or None,
        constraints=list(anchor.get("constraints", [])),
        advice=data.get("advice"),
        theories=lines,
        options=options,
        situational=situational,
        tests=tests,
        conviction_trail=trail,
        warnings=warnings,
        key_numbers=key_numbers,
        graph_metrics=data.get("graph_metrics", {}),
        forecast=forecast,
    )


def _map_favours(data: dict[str, Any]) -> str:
    if not data or data.get("unavailable") or not data.get("options"):
        return "—"
    if not data.get("decisive"):
        return "No clear leader"
    leader = next(o for o in data["options"] if o["key"] == data["leader"])
    return f"{leader['key']} ({pct(leader['p_best'])})"


def quality_lines(metrics: dict[str, Any]) -> list[str]:
    """The analysis's own quality, stated plainly for a reader deciding how far to trust it."""
    if not metrics:
        return ["Graph metrics unavailable."]
    out = [f"{metrics['claims']} claims and {metrics['edges']} causal links after review, "
           f"in {metrics['components']} connected group(s)."]
    if metrics.get("reach_outcome_share") is not None:
        out.append(f"{pct(metrics['reach_outcome_share'])} of claims have a causal path "
                   "to a success criterion.")
    if metrics.get("peripheral"):
        out.append(f"{metrics['peripheral']} claim(s) looked like background but turned "
                   "out to be on a path to the outcome — worth a second look.")
    if metrics.get("isolated"):
        out.append(f"{metrics['isolated']} claim(s) are connected to nothing.")
    if metrics.get("theories_reaching_outcome") is not None:
        out.append(f"{metrics['theories_reaching_outcome']} of {metrics['theories']} "
                   "theories reach a success criterion through a verified chain.")
    return out
