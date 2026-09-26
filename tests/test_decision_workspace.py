"""Assumptions, evidence quality, timeline, scenarios and sub-decisions. Pure, no database."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from decision_studio.reasoning import evidence_quality as eq
from decision_studio.reasoning.assumptions import build_register
from decision_studio.reasoning.decision_scenarios import (
    Assumption,
    apply_assumptions,
    automatic_assumptions,
    build_scenarios,
)
from decision_studio.reasoning.decision_timeline import describe_change
from decision_studio.reasoning.option_comparison import build_comparison, outcome_node_map
from decision_studio.reasoning.sub_decisions import evaluate, normalise
from tests.test_decision_analysis import ANCHOR, trade_off_graph

NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)
LABELS = lambda items: [i["key"] for i in items]  # noqa: E731


# ── Evidence quality ────────────────────────────────────────────────────────


def _doc(**kw):
    base = dict(evidence_type="supporting", source_url="https://example.com/a", source_title="A",
                relevance_score=0.8, published_date=NOW - timedelta(days=30), author_interest=None)
    return SimpleNamespace(**{**base, **kw})


class TestDocumentLabels:
    @pytest.mark.parametrize("days, key", [(30, "recent"), (500, "dated"), (2000, "old"), (None, "undated")])
    def test_freshness(self, days, key):
        doc = _doc(published_date=None if days is None else NOW - timedelta(days=days))
        assert key in LABELS(eq.document_labels(doc, [doc], NOW))

    def test_direction_directness_and_interest(self):
        doc = _doc(evidence_type="contradicting", relevance_score=0.3, author_interest="interested")
        keys = LABELS(eq.document_labels(doc, [doc], NOW))
        assert {"contradicts", "indirect", "interested"} <= set(keys)

    def test_same_source_is_not_independent(self):
        a, b = _doc(source_url="https://www.vendor.com/1"), _doc(source_url="https://vendor.com/2")
        c = _doc(source_url="https://press.org/x")
        assert "same_source" in LABELS(eq.document_labels(a, [a, b, c], NOW))
        assert "independent" in LABELS(eq.document_labels(c, [a, b, c], NOW))

    def test_summary(self):
        assert eq.summarise_documents([], NOW)["labels"][0]["key"] == "none"
        summary = eq.summarise_documents(
            [_doc(), _doc(evidence_type="contradicting", source_url="https://b.org")], NOW)
        assert (summary["supporting"], summary["contradicting"], summary["sources"]) == (1, 1, 2)
        assert "recent" in LABELS(summary["labels"])


def _step(**kw):
    base = dict(source="tripwire", created_at=NOW - timedelta(days=3), likelihood_ratio=0.25,
                duplicate_of=None, event="Vendor missed 1 August", applied=True)
    return SimpleNamespace(**{**base, **kw})


class TestObservationLabels:
    @pytest.mark.parametrize("lr, key", [(4.0, "supports"), (0.25, "contradicts"), (1.0, "inconclusive")])
    def test_direction(self, lr, key):
        assert key in LABELS(eq.observation_labels(_step(likelihood_ratio=lr), now=NOW))

    def test_independence_and_decisiveness(self):
        assert "independent" in LABELS(eq.observation_labels(_step(), decisiveness="decisive", now=NOW))
        assert "decisive" in LABELS(eq.observation_labels(_step(), decisiveness="decisive", now=NOW))
        assert "same_event" in LABELS(eq.observation_labels(_step(duplicate_of="x", applied=False), now=NOW))
        assert "event_unnamed" in LABELS(eq.observation_labels(_step(event=None), now=NOW))

    def test_age_and_already_counted(self):
        old = eq.observation_labels(_step(created_at=NOW - timedelta(days=200), applied=False), now=NOW)
        assert "dated" in LABELS(old) and "in_prior" in LABELS(old)


# ── Assumption register ─────────────────────────────────────────────────────


def _theory(claim_ids, *, stale=False, option="O1"):
    return SimpleNamespace(title="t", option_key=option, is_stale=stale,
                           claim_links=[SimpleNamespace(claim_id=c) for c in claim_ids])


class TestAssumptionRegister:
    def _register(self, **kw):
        g, claims = trade_off_graph(bonus_confidence=0.2)
        comparison = build_comparison(g, claims, ANCHOR, runs=30)
        return build_register(g, claims, ANCHOR, comparison, kw.get("theories", []),
                              kw.get("evidence", {})), claims

    def test_derived_from_the_graph_only(self):
        register, claims = self._register()
        ids = [a["claim_id"] for a in register["assumptions"]]
        assert set(ids) <= {c.id for c in claims}
        # Levers are choices, success criteria are the outcome: neither is an assumption.
        assert not set(ids) & {"bonus", "slack", "y1", "y2"}
        assert {"vendor", "morale"} <= set(ids)

    def test_fields(self):
        register, _ = self._register(
            theories=[_theory(["vendor"], stale=True, option="O2")],
            evidence={"e-vendor": [_doc()]},
        )
        vendor = next(a for a in register["assumptions"] if a["claim_id"] == "vendor")
        assert vendor["belief"] == pytest.approx(0.6)
        assert vendor["outcomes"] == ["Y1"] and "O2" in vendor["options"]
        assert vendor["stale"] and vendor["evidence"]["count"] == 1
        assert vendor["affects"] in ("comparison", "all_options")
        assert register["influence_basis"] == "comparison"

    def test_uncertain_and_influential_first(self):
        register, _ = self._register()
        priorities = [a["priority"] for a in register["assumptions"]]
        assert priorities == sorted(priorities, reverse=True)
        assert all(p > 0 for p in priorities)

    def test_relevance_stands_in_without_a_comparison(self):
        g, claims = trade_off_graph()
        for c in claims:
            c.relevance = 0.8
        single = {**ANCHOR, "options": ANCHOR["options"][:1]}
        comparison = build_comparison(g, claims, single, runs=10)
        register = build_register(g, claims, single, comparison, [], {})
        assert register["influence_basis"] == "relevance"
        assert all(a["influence_basis"] == "relevance" and not a["can_alter"] for a in register["assumptions"])


# ── Timeline: comparison snapshots ──────────────────────────────────────────


def _print(y1_q3=0.35, headline=("O2", "robust")):
    return {"outcomes": {"O1": {"Y1": y1_q3}, "O2": {"Y1": 0.72}}, "labels": {"O1": "Q3", "O2": "Q4"},
            "outcome_labels": {"Y1": "Ship"},
            "headline": {"higher": headline[0], "verdict": headline[1]} if headline else None}


class TestComparisonJournal:
    def test_first_snapshot(self):
        assert describe_change(None, _print()) == ["First comparison of the options on the causal map."]

    def test_no_material_change_is_no_entry(self):
        assert describe_change(_print(0.35), _print(0.37)) == []

    def test_outcome_and_verdict_changes(self):
        changes = describe_change(_print(0.35), _print(0.15, ("O2", "sensitive")))
        assert changes[0] == "Y1 under O1 Q3: 35% → 15%"
        assert changes[1] == "Weighted view: O2 robust → O2 sensitive"


# ── Scenarios ───────────────────────────────────────────────────────────────


class TestScenarios:
    def _setup(self):
        g, claims = trade_off_graph(bonus_confidence=0.2)
        base = build_comparison(g, claims, ANCHOR, runs=30)
        return g, claims, base

    def test_automatic_cases_move_the_same_inputs_to_opposite_ends(self):
        g, claims, base = self._setup()
        text = {c.id: c.text for c in claims}
        cases = automatic_assumptions(base, g, text, outcome_node_map(claims, ANCHOR, g))
        up, down = cases["upside"], cases["downside"]
        assert [a.id for a in up] == [a.id for a in down] and 0 < len(up) <= 5
        for u, d in zip(up, down):
            assert u.base == d.base and u.value != d.value
            assert min(u.value, d.value) <= u.base <= max(u.value, d.value)

    def test_applying_assumptions_leaves_the_graph_alone(self):
        g, _, _ = self._setup()
        varied = apply_assumptions(g, [Assumption("link", "e-vendor", "v", 0.5, 0.1),
                                       Assumption("claim", "morale", "m", 0.2, 0.9)])
        assert varied.edges["vendor", "y1"]["strength"] == 0.1 and varied.nodes["morale"]["prior"] == 0.9
        assert g.edges["vendor", "y1"]["strength"] == 0.5 and g.nodes["morale"]["prior"] == 0.2

    def test_downside_below_base_below_upside_on_average(self):
        g, claims, base = self._setup()
        result = build_scenarios(g, claims, ANCHOR, base, {}, runs=20)
        means = {
            c["key"]: sum(o["weighted"] for o in c["options"]) / len(c["options"]) for c in result["cases"]
        }
        assert means["downside"] < means["base"] < means["upside"]
        assert [c["source"] for c in result["cases"]] == ["base", "automatic", "automatic"]
        assert result["cases"][0]["assumptions"] == []

    def test_the_deciders_assumptions_replace_the_automatic_ones(self):
        g, claims, base = self._setup()
        row = SimpleNamespace(edge_overrides={"e-vendor": 0.1, "gone": 0.5}, claim_overrides={"morale": 0.0})
        result = build_scenarios(g, claims, ANCHOR, base, {"downside": row}, runs=20)
        downside = result["cases"][2]
        assert downside["source"] == "user"
        assert {(a["kind"], a["id"], a["value"]) for a in downside["assumptions"]} == {
            ("link", "e-vendor", 0.1), ("claim", "morale", 0.0)}  # "gone" is not in the graph


# ── Sub-decisions ───────────────────────────────────────────────────────────

OPTIONS = {"O1", "O2"}
USABLE = {"vendor", "morale", "bonus", "slack"}


class TestSubDecisionInput:
    def _one(self, **kw):
        base = {"parent": "O2", "label": "Staffing",
                "choices": [{"label": "Vendor-led", "claim_ids": ["vendor"]},
                            {"label": "Team-led", "claim_ids": ["morale"]}]}
        return {**base, **kw}

    def test_keys_are_assigned(self):
        (sd,) = normalise([self._one()], OPTIONS, USABLE, strict=True)
        assert sd["key"] == "S1" and [c["key"] for c in sd["choices"]] == ["S1a", "S1b"]

    @pytest.mark.parametrize("change, message", [
        ({"parent": "O9"}, "Unknown parent"),
        ({"choices": [{"label": "Only one", "claim_ids": ["vendor"]}]}, "2 to 4 choices"),
        ({"choices": [{"label": "A", "claim_ids": ["nope"]}, {"label": "B", "claim_ids": ["vendor"]}]},
         "not in the reviewed graph"),
    ])
    def test_invalid_input_is_refused(self, change, message):
        with pytest.raises(ValueError, match=message):
            normalise([self._one(**change)], OPTIONS, USABLE, strict=True)

    def test_stored_data_that_no_longer_fits_is_dropped_not_fatal(self):
        assert normalise([self._one(parent="O9")], OPTIONS, USABLE) == []


class TestSubDecisionEvaluation:
    def test_choices_are_interventions_under_the_parent_option(self):
        g, claims = trade_off_graph()
        (sd,) = normalise([{
            "parent": "O2", "label": "Staffing",
            "choices": [{"label": "Vendor-led", "claim_ids": ["vendor"]},
                        {"label": "Team-led", "claim_ids": ["morale"]}],
        }], OPTIONS, USABLE, strict=True)
        (result,) = evaluate(g, claims, ANCHOR, [sd], runs=30)
        vendor_led, team_led = result["choices"]
        # Q4 (slack on) with the vendor on and morale off, and the reverse.
        assert vendor_led["outcomes"]["Y1"]["point"] == pytest.approx(1 - (1 - 0.8) * (1 - 0.5))
        assert vendor_led["outcomes"]["Y2"]["point"] == pytest.approx(0.0)
        assert team_led["outcomes"]["Y2"]["point"] == pytest.approx(1.0)
        assert result["spread"] > 0 and result["verdict"]["verdict"] in ("robust", "sensitive", "unresolved")
        assert result["sentence"].startswith("Under O2 Q4, the staffing choice moves the weighted view")
        for word in ("best", "recommend", "should"):
            assert word not in result["sentence"].lower()

    def test_choices_that_reach_no_outcome_are_said_so(self):
        g, claims = trade_off_graph()
        g.add_node("canteen", prior=0.5)
        g.add_node("rebrand", prior=0.5)
        claims += [SimpleNamespace(id=c, text=c, decision_role="background", bears_on=[], origin="ai")
                   for c in ("canteen", "rebrand")]
        (sd,) = normalise([{"parent": "O1", "label": "Office",
                            "choices": [{"label": "A", "claim_ids": ["canteen"]},
                                        {"label": "B", "claim_ids": ["rebrand"]}]}],
                          OPTIONS, USABLE | {"canteen", "rebrand"}, strict=True)
        (result,) = evaluate(g, claims, ANCHOR, [sd], runs=10)
        assert "no causal path" in result["unavailable"] or "cannot tell them apart" in result["unavailable"]


# ── The report ──────────────────────────────────────────────────────────────

from decision_studio.reasoning.brief_view import (  # noqa: E402
    build_assumptions,
    build_journal,
    build_scenarios as view_scenarios,
    build_sub_decisions,
)


class TestReportSections:
    def test_assumptions_are_one_line_each_with_their_flags(self):
        g, claims = trade_off_graph(bonus_confidence=0.2)
        comparison = build_comparison(g, claims, ANCHOR, runs=30)
        register = build_register(g, claims, ANCHOR, comparison, [_theory(["vendor"], stale=True)],
                                  {"e-vendor": [_doc()]})
        lines, _ = build_assumptions(register, limit=5)
        vendor = next(line for line in lines if line.text == "vendor")
        assert vendor.belief == "60%"
        assert "cited by an out-of-date theory" in vendor.flags and "reaches Y1" in vendor.flags
        assert "1 supporting" in vendor.evidence

    def test_scenarios_list_what_each_case_changed(self):
        g, claims = trade_off_graph(bonus_confidence=0.2)
        base = build_comparison(g, claims, ANCHOR, runs=20)
        view = view_scenarios(build_scenarios(g, claims, ANCHOR, base, {}, runs=10))
        assert view.cases == ["Base case", "Upside", "Downside"]
        assert all(cell.endswith("/ 100") for _, cells in view.rows for cell in cells)
        assert view.changes[0][1] == "automatic" and "→" in view.changes[0][2][0]
        assert "not forecasts" in view.caveat

    def test_sub_decisions_and_journal(self):
        assert build_sub_decisions([{"parent": "O1", "parent_label": "Q3", "label": "Staffing",
                                     "sentence": "Under O1 Q3 ...", "unavailable": None}]) == [
            "O1 Q3 → Staffing: Under O1 Q3 ..."]
        journal = build_journal({"events": [
            {"at": "2026-09-01T00:00:00+00:00", "title": "Analysis created", "material": True},
            {"at": "2026-09-02T00:00:00+00:00", "title": "Claim added", "material": False},
            {"at": "2026-09-03T00:00:00+00:00", "title": "Tripwire happened", "material": True,
             "belief_change": "conviction 60% → 13%"},
        ]})
        assert journal == [("2026-09-03", "Tripwire happened", "conviction 60% → 13%"),
                           ("2026-09-01", "Analysis created", "")]
