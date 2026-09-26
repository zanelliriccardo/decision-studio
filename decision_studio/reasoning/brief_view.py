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
    robustness: "Robustness | None" = None
    mind_changers: list["MindChangerView"] = field(default_factory=list)
    #: (action, why) for the top information needs.
    information: list[tuple[str, str]] = field(default_factory=list)
    assumptions: list["AssumptionLine"] = field(default_factory=list)
    assumptions_note: str | None = None
    scenarios: "ScenarioView | None" = None
    sub_decisions: list[str] = field(default_factory=list)
    #: (date, title, what it changed), material events, newest first.
    journal: list[tuple[str, str, str]] = field(default_factory=list)


STATUS_NOTES = {
    "modelled": "",
    "only_as_alternative": "modelled only as not choosing the others",
    "no_path": "what it involves does not reach a success criterion on the map",
    "not_modelled": "nothing in the map describes what it involves",
}


IMPORTANCE_LABELS = {
    "critical": "Critical", "high": "High", "medium": "Medium", "low": "Low", "none": "Not a factor",
}


@dataclass
class Forecast:
    """What each option implies, and the same read through the decider's priorities."""

    #: Column headers for the model-implied table: one per success criterion.
    outcomes: list[str]
    #: Model-implied outcomes: (option, cells per criterion, note).
    rows: list[tuple[str, list[str], str]]
    #: The weighted view in one neutral sentence (or why there is none).
    headline: str
    #: "Y1 Ship on date: Critical (67% of the weight); ..."
    priorities_line: str | None = None
    #: Weighted view: (option, contribution cells per criterion, total "60 / 100").
    weighted_rows: list[tuple[str, list[str], str]] = field(default_factory=list)
    caveat: str = (
        "Model-implied outcomes: each option was applied to the reviewed causal map "
        "(its levers switched on, the other options' switched off) and the map "
        "propagated. The range is how far each figure moves when every link strength "
        "is varied within its uncertainty. What the map implies, not a forecast."
    )
    weighted_caveat: str = (
        "Weighted view: each model-implied outcome multiplied by its share of the "
        "weight the decider gave it (Critical 8, High 4, Medium 2, Low 1, Not a "
        "factor 0), then added up. Points out of 100 — not a probability, and not a "
        "recommendation."
    )


@dataclass
class Robustness:
    """Page-two answers: what is robust, what is uncertain, what could flip it."""

    pair: str
    robust: list[str]
    uncertain: list[str]
    flips: list[str]
    method: str = (
        "Robust: the higher option is higher in at least 80% of simulations with link "
        "strengths varied; sensitive: 60–80%; unresolved: below 60%; differences under "
        "2 points count as none. Inputs that could flip the result were found by moving "
        "each link strength and root claim across its plausible range, one at a time. "
        "Sensitivity to the model's uncertainty, not an empirical forecast."
    )


@dataclass
class MindChangerView:
    option: str
    convictions: list[str]
    weaken: list[str]
    strengthen: list[str]


def _points(value: float) -> str:
    return f"{round(value * 100)}"


def build_forecast(data: dict[str, Any] | None) -> Forecast | None:
    """The comparison from reasoning/option_comparison.py, as sentences and cells."""
    if not data or not data.get("options"):
        return None
    if data.get("unavailable"):
        return Forecast(outcomes=[], rows=[], headline=data["unavailable"])
    labels = {o["key"]: o["label"] for o in data["options"]}
    outcomes = data.get("outcomes", [])
    priorities = {p["key"]: p for p in data.get("priorities", [])}

    rows = []
    weighted_rows = []
    for option in data["options"]:
        cells = []
        for outcome in outcomes:
            stats = option["outcomes"].get(outcome["key"])
            cells.append(
                "—" if not stats else
                f"{pct(stats['point'])} ({pct(stats['p10'])}–{pct(stats['p90'])})"
            )
        name = f"{option['key']} {option['label']}"
        rows.append((name, cells, STATUS_NOTES.get(option["status"], "")))
        weighted = option.get("weighted")
        if weighted:
            weighted_rows.append((
                name,
                [_points(weighted["contributions"].get(o["key"], 0.0))
                 if o["key"] in weighted["contributions"] else "—" for o in outcomes],
                f"{_points(weighted['score'])} / 100",
            ))

    priorities_line = "; ".join(
        f"{o['key']} {o['label']}: {IMPORTANCE_LABELS[priorities[o['key']]['importance']]}"
        + (" (not set)" if priorities[o["key"]].get("is_default") else "")
        + f" — {pct(priorities[o['key']]['normalized_weight'])} of the weight"
        for o in outcomes if o["key"] in priorities
    ) or None

    headline = "Every success criterion is set to \"not a factor\": there is no weighted view."
    if weighted_rows:
        pair = _headline_pair(data)
        verdict = (pair or {}).get("weighted")
        if not verdict or verdict["verdict"] == "no_difference" or not verdict.get("higher"):
            headline = ("Based on the priorities entered, the weighted model view shows no "
                        "material difference between the leading options.")
        else:
            wording = {
                "robust": "robustly higher",
                "sensitive": "higher, but sensitive to the assumptions",
                "unresolved": "higher only at the central estimate (unresolved)",
            }[verdict["verdict"]]
            higher = verdict["higher"]
            headline = (f"Based on the priorities entered, the weighted model view is "
                        f"{wording} for {higher} ({labels[higher]}): higher in "
                        f"{pct(verdict['share'])} of simulations. The decision itself "
                        "remains the decider's.")
    return Forecast(
        outcomes=[
            f"{o['key']} {o['label']}"
            + (f" ({IMPORTANCE_LABELS[priorities[o['key']]['importance']]})" if o["key"] in priorities else "")
            for o in outcomes
        ],
        rows=rows, headline=headline, priorities_line=priorities_line,
        weighted_rows=weighted_rows,
    )


@dataclass
class AssumptionLine:
    text: str
    belief: str
    flags: list[str]
    evidence: str


def build_assumptions(register: dict[str, Any] | None, limit: int = 5) -> tuple[list[AssumptionLine], str | None]:
    """The assumptions most at stake, one line each."""
    if not register:
        return [], None
    lines = []
    for row in register.get("assumptions", [])[:limit]:
        flags = []
        if row.get("driver_rank"):
            flags.append(f"sensitivity driver #{row['driver_rank']}")
        if row.get("can_alter"):
            flags.append("could change the comparison")
        elif row.get("affects") == "all_options":
            flags.append("affects all options similarly")
        if row.get("stale"):
            flags.append("cited by an out-of-date theory")
        if row.get("needs_evidence"):
            flags.append("needs evidence")
        if row.get("outcomes"):
            flags.append("reaches " + ", ".join(row["outcomes"]))
        evidence = " · ".join(label["text"] for label in row.get("evidence", {}).get("labels", []))
        lines.append(AssumptionLine(row["text"], pct(row.get("belief")), flags, evidence))
    note = None
    if register.get("influence_basis") == "relevance":
        note = "No option comparison could be made, so influence is the model's relevance score."
    elif register.get("total", 0) > len(lines):
        note = f"{register['total'] - len(lines)} further assumption(s) in the map, with less at stake."
    return lines, note


@dataclass
class ScenarioView:
    cases: list[str]
    #: (option, cell per case) — weighted view, or the first criterion when there is none.
    rows: list[tuple[str, list[str]]]
    measure: str
    #: (case label, "automatic"/"the decider's", ["input: base → value"])
    changes: list[tuple[str, str, list[str]]]
    caveat: str = ("Scenario assumptions, not forecasts: each case reruns the option comparison on "
                   "the same causal map with only the inputs listed changed.")


def build_scenarios(data: dict[str, Any] | None) -> ScenarioView | None:
    if not data or data.get("unavailable") or not data.get("cases"):
        return None
    cases = data["cases"]
    first_outcome = (data.get("outcomes") or [{}])[0].get("key")
    use_weighted = any(o.get("weighted") is not None for o in cases[0]["options"])
    rows = []
    for option in cases[0]["options"]:
        cells = []
        for case in cases:
            row = next((o for o in case["options"] if o["key"] == option["key"]), None)
            if row is None:
                cells.append("—")
            elif use_weighted:
                cells.append("—" if row["weighted"] is None else f"{round(row['weighted'] * 100)} / 100")
            else:
                cells.append(pct((row["outcomes"].get(first_outcome) or {}).get("point")))
        rows.append((f"{option['key']} {option['label']}", cells))
    changes = [
        (case["label"], "the decider's" if case["source"] == "user" else "automatic",
         [f"{a['label']}: {pct(a['base'])} → {pct(a['value'])}" for a in case["assumptions"]])
        for case in cases[1:]
    ]
    return ScenarioView(
        cases=[c["label"] for c in cases], rows=rows,
        measure="weighted view" if use_weighted else f"{first_outcome} (model-implied)",
        changes=changes,
    )


def build_sub_decisions(items: list[dict[str, Any]] | None) -> list[str]:
    out = []
    for sd in items or []:
        head = f"{sd['parent']} {sd.get('parent_label', '')} → {sd['label']}: "
        out.append(head + (sd.get("unavailable") or sd.get("sentence") or "no weighted view"))
    return out


def build_journal(timeline: dict[str, Any] | None, limit: int = 8) -> list[tuple[str, str, str]]:
    if not timeline:
        return []
    material = [e for e in timeline.get("events", []) if e.get("material")]
    return [
        (e["at"][:10], e["title"], e.get("belief_change") or e.get("detail") or "")
        for e in reversed(material[-limit:])
    ]


def _headline_pair(data: dict[str, Any]) -> dict[str, Any] | None:
    pair_keys = set(data.get("headline_pair") or [])
    return next((p for p in data.get("robustness", []) if {p["a"], p["b"]} == pair_keys), None)


def build_robustness(data: dict[str, Any] | None) -> Robustness | None:
    """The headline comparison's robustness and the inputs that could flip it."""
    if not data or data.get("unavailable") or not data.get("robustness"):
        return None
    pair = _headline_pair(data) or data["robustness"][0]
    labels = {o["key"]: o["label"] for o in data["options"]}
    rows = list(pair["outcomes"]) + ([pair["weighted"]] if pair.get("weighted") else [])
    robust = [r["sentence"] for r in rows if r["verdict"] == "robust"]
    uncertain = [r["sentence"] for r in rows if r["verdict"] in ("sensitive", "unresolved")]
    drivers = data.get("drivers", [])
    flips = [f"{d['label']}. {d['explanation']}" for d in drivers if d["flip"] in ("flips", "erases")]
    if not flips and drivers:
        top = drivers[0]
        flips = [f"No single input reverses the comparison within its plausible range. The "
                 f"largest mover is {top['label']} (the weighted gap moves by "
                 f"{round(top['impact'] * 100)} point{'' if round(top['impact'] * 100) == 1 else 's'} "
                 "across its range)."]
    return Robustness(
        pair=f"{pair['a']} {labels[pair['a']]} vs {pair['b']} {labels[pair['b']]}",
        robust=robust, uncertain=uncertain, flips=flips,
    )


STATUS_WORDS = {
    "pending": "not observed yet", "overdue": "overdue", "happened": "happened",
    "did_not_happen": "did not happen", "expired": "expired", "not_tested": "not tested",
    "held": "held", "refuted": "refuted", "inconclusive": "inconclusive", "not_run": "not run",
    "supports": "supported", "refutes": "refuted", "abandoned": "abandoned",
}


def build_mind_changers(options: list[dict[str, Any]] | None, per_direction: int = 2) -> list[MindChangerView]:
    """Per option: convictions, and the strongest signals each way."""
    out = []
    for option in options or []:
        if not option.get("theories"):
            continue

        def line(signal: dict[str, Any]) -> str:
            return (f"{signal['text']} ({signal['condition']}; "
                    f"{signal['decisiveness']}; {STATUS_WORDS.get(signal['status'], signal['status'])})")

        out.append(MindChangerView(
            option=f"{option['key']} {option['label']}",
            convictions=[
                f"{t['title']}: conviction {pct(t['conviction'])}" if t.get("conviction") is not None
                else f"{t['title']}: conviction not stated"
                for t in option["theories"]
            ],
            weaken=[line(s) for s in option.get("weaken", [])[:per_direction]],
            strengthen=[line(s) for s in option.get("strengthen", [])[:per_direction]],
        ))
    return out


def _rank_key(line: TheoryLine) -> tuple:
    """Strongest first, as everywhere else (theories.rank_key), reversed for
    ``sorted(..., reverse=True)``."""
    from decision_studio.reasoning.theories import rank_key

    reaches, stale, neg_support = rank_key(line.theory, line.conviction)
    return (not reaches, not stale, -neg_support)


def build_view(data: dict[str, Any]) -> BriefView:
    """Derive the brief from the data gathered in ``brief._gather``."""
    anchor = data.get("anchor") or {}
    convictions = data.get("convictions", {})
    from decision_studio.reasoning.theories import rank_key

    def _conviction_of(theory: Any) -> float | None:
        held = convictions.get(str(theory.theory_key))
        return held.current if held else None

    theories = sorted(data["theories"], key=lambda t: rank_key(t, _conviction_of(t)))

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
        ("Weighted view", _weighted_lead(forecast_data)),
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
        robustness=build_robustness(forecast_data),
        mind_changers=build_mind_changers(data.get("mind_changers")),
        information=[(i["action"], i["why"]) for i in forecast_data.get("information_priority", [])[:3]],
        assumptions=build_assumptions(data.get("assumptions"))[0],
        assumptions_note=build_assumptions(data.get("assumptions"))[1],
        scenarios=build_scenarios(data.get("scenarios")),
        sub_decisions=build_sub_decisions(data.get("sub_decisions")),
        journal=build_journal(data.get("timeline")),
    )


def _weighted_lead(data: dict[str, Any]) -> str:
    """The weighted view's headline comparison in two words, for a key-number tile."""
    if not data or data.get("unavailable") or not data.get("options"):
        return "—"
    verdict = (_headline_pair(data) or {}).get("weighted")
    if not verdict:
        return "—"
    if verdict["verdict"] == "no_difference" or not verdict.get("higher"):
        return "No difference"
    word = {"robust": "robust", "sensitive": "sensitive", "unresolved": "unresolved"}[verdict["verdict"]]
    return f"{verdict['higher']} higher · {word}"


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
