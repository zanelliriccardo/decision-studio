"""Decision priorities, robustness, sensitivity, information priority, mind changers.

Pure computation, no database. The trade-off graph: choosing Q3 (O1) funds a
retention bonus that keeps the team (Y2); choosing Q4 (O2) adds schedule slack
that makes the date (Y1). A vendor's reliability bears on the date either way.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import networkx as nx
import pytest

from decision_studio.graph.option_sensitivity import (
    ERASES,
    FLIPS,
    NO_FLIP,
    flip_status,
    perturbation_drivers,
    rank_drivers,
)
from decision_studio.graph.stability import WEIGHTED, compare_options
from decision_studio.reasoning import decision_priorities as dp
from decision_studio.reasoning import decision_robustness as dr
from decision_studio.reasoning.information_priority import band, rank_information
from decision_studio.reasoning.mind_changers import (
    STRENGTHEN,
    WEAKEN,
    consolidate,
    for_option,
    theory_signals,
)
from decision_studio.reasoning.option_comparison import build_comparison, intervene

# ── Decision priorities ─────────────────────────────────────────────────────

OUTCOMES = [("Y1", "Ship on the committed date"), ("Y2", "Keep the team intact")]


class TestPriorities:
    def test_the_mapping_is_fixed_and_doubles_per_level(self):
        assert dp.IMPORTANCE_WEIGHTS == {
            "critical": 8.0, "high": 4.0, "medium": 2.0, "low": 1.0, "none": 0.0}
        assert dp.DEFAULT_IMPORTANCE == "medium"

    def test_normalised_to_one(self):
        resolved = dp.resolve(OUTCOMES, {"Y1": "critical", "Y2": "high"})
        assert [p.normalized for p in resolved] == [pytest.approx(8 / 12), pytest.approx(4 / 12)]
        assert not any(p.is_default for p in resolved)

    def test_missing_weights_take_the_default_and_say_so(self):
        resolved = dp.resolve(OUTCOMES, {"Y1": "critical"})
        assert resolved[1].importance == "medium" and resolved[1].is_default
        assert resolved[1].normalized == pytest.approx(2 / 10)
        # Nothing stored at all: equal weights.
        assert [p.normalized for p in dp.resolve(OUTCOMES, None)] == [0.5, 0.5]

    def test_unknown_levels_and_outcomes_are_dropped(self):
        assert dp.clean_priorities({"Y1": "urgent", "Y2": "low", "Y9": "high"}, ["Y1", "Y2"]) == {"Y2": "low"}
        assert dp.clean_priorities("not a dict") == {}

    def test_one_outcome(self):
        weights = dp.normalized_weights(dp.resolve(OUTCOMES[:1], {"Y1": "low"}))
        view = dp.weighted_view({"Y1": 0.35}, weights)
        assert view.score == pytest.approx(0.35) and view.contributions == {"Y1": pytest.approx(0.35)}

    def test_multiple_outcomes_and_contributions(self):
        weights = dp.normalized_weights(dp.resolve(OUTCOMES, {"Y1": "critical", "Y2": "low"}))
        view = dp.weighted_view({"Y1": 0.72, "Y2": 0.55}, weights)
        assert view.contributions["Y1"] == pytest.approx(8 / 9 * 0.72)
        assert view.contributions["Y2"] == pytest.approx(1 / 9 * 0.55)
        assert view.score == pytest.approx(sum(view.contributions.values()))

    def test_zero_weight_leaves_a_criterion_out(self):
        weights = dp.normalized_weights(dp.resolve(OUTCOMES, {"Y1": "high", "Y2": "none"}))
        assert weights == {"Y1": 1.0}
        assert dp.weighted_view({"Y1": 0.4, "Y2": 0.9}, weights).score == pytest.approx(0.4)

    def test_very_low_weight_still_counts_a_little(self):
        weights = dp.normalized_weights(dp.resolve(OUTCOMES, {"Y1": "critical", "Y2": "low"}))
        assert 0 < weights["Y2"] < 0.12

    def test_no_weight_at_all_is_no_view(self):
        weights = dp.normalized_weights(dp.resolve(OUTCOMES, {"Y1": "none", "Y2": "none"}))
        assert weights == {} and dp.weighted_view({"Y1": 0.4}, weights) is None

    def test_deterministic(self):
        runs = {
            dp.weighted_view({"Y1": 0.3, "Y2": 0.84},
                             dp.normalized_weights(dp.resolve(OUTCOMES, {"Y1": "high"}))).score
            for _ in range(5)
        }
        assert len(runs) == 1


# ── Robustness thresholds ───────────────────────────────────────────────────


class TestRobustness:
    @pytest.mark.parametrize("share, verdict", [
        (0.80, dr.ROBUST), (0.79, dr.SENSITIVE), (0.60, dr.SENSITIVE), (0.59, dr.UNRESOLVED),
    ])
    def test_thresholds(self, share, verdict):
        v = dr.classify("O2", "O1", 0.72, 0.35, share)
        assert v.verdict == verdict and v.higher == "O2"

    def test_share_is_read_for_whichever_option_is_higher(self):
        v = dr.classify("O1", "O2", 0.35, 0.72, 0.13)
        assert v.higher == "O2" and v.share == pytest.approx(0.87) and v.verdict == dr.ROBUST

    def test_a_negligible_gap_is_no_difference(self):
        assert dr.classify("O1", "O2", 0.500, 0.515, 1.0).verdict == dr.NO_DIFFERENCE

    def test_pair_summaries(self):
        robust_a = dr.classify("A", "B", 0.8, 0.2, 0.9)
        robust_b = dr.classify("A", "B", 0.2, 0.8, 0.1)
        unresolved = dr.classify("A", "B", 0.6, 0.5, 0.55)
        none = dr.classify("A", "B", 0.5, 0.5, 0.5)
        assert dr.summarise_pair("A", "B", [robust_a, robust_b]) == dr.PAIR_MIXED
        assert dr.summarise_pair("A", "B", [robust_a, unresolved]) == dr.PAIR_CONSISTENT
        assert dr.summarise_pair("A", "B", [unresolved, none]) == dr.PAIR_UNRESOLVED
        assert dr.summarise_pair("A", "B", [none]) == dr.PAIR_NO_DIFFERENCE

    def test_sentences_stay_neutral(self):
        text = dr.describe(dr.classify("O2", "O1", 0.72, 0.35, 0.87), "Y1",
                           {"O1": "Q3", "O2": "Q4"})
        assert text.startswith("Q4 is robustly higher on Y1: higher in 87%")
        for word in ("best", "correct", "recommend", "should"):
            assert word not in text.lower()


# ── The trade-off graph ─────────────────────────────────────────────────────

ANCHOR = {
    "decision": "Commit to Q3 or Q4?",
    "options": [{"key": "O1", "label": "Q3"}, {"key": "O2", "label": "Q4"}],
    "outcomes": [{"key": "Y1", "label": "Ship on date"}, {"key": "Y2", "label": "Keep the team"}],
}


def _claim(cid, role, bears, origin="extraction"):
    return SimpleNamespace(id=cid, text=cid.replace("_", " "), decision_role=role,
                           bears_on=bears, origin=origin)


def trade_off_graph(bonus_confidence=0.8):
    g = nx.DiGraph()
    for node, prior in (("bonus", 0.5), ("slack", 0.5), ("vendor", 0.6), ("morale", 0.2),
                        ("y1", 0.5), ("y2", 0.5)):
        g.add_node(node, prior=prior)
    edge = dict(evidence_score=1.0, link_confidence=0.8, causal_type="direct")
    g.add_edge("slack", "y1", strength=0.8, edge_id="e-slack", **edge)
    g.add_edge("vendor", "y1", strength=0.5, edge_id="e-vendor", **edge)
    g.add_edge("bonus", "y2", strength=0.8, edge_id="e-bonus",
               **{**edge, "link_confidence": bonus_confidence})
    g.add_edge("morale", "y2", strength=1.0, edge_id="e-morale", **edge)
    claims = [
        _claim("bonus", "lever", ["O1"]), _claim("slack", "lever", ["O2"]),
        _claim("vendor", "contingency", ["O1", "O2"]), _claim("morale", "background", []),
        _claim("y1", "outcome", ["Y1"], origin="frame"),
        _claim("y2", "outcome", ["Y2"], origin="frame"),
    ]
    return g, claims


def _option_graphs(g):
    return {"O1": intervene(g, ["bonus"], ["slack"]), "O2": intervene(g, ["slack"], ["bonus"])}


class TestComparisonCarriesWeightsAndPairs:
    def test_pairwise_shares_are_complementary(self):
        g, _ = trade_off_graph()
        forecasts, _ = compare_options(_option_graphs(g), ["y1", "y2"], runs=100)
        for key in ("y1", "y2", WEIGHTED):
            assert forecasts["O1"].higher_than["O2"][key] + forecasts["O2"].higher_than["O1"][key] \
                == pytest.approx(1.0)
        assert forecasts["O2"].higher_than["O1"]["y1"] == pytest.approx(1.0)
        assert forecasts["O1"].higher_than["O2"]["y2"] == pytest.approx(1.0)

    def test_weights_decide_the_overall_score_not_the_outcome_values(self):
        g, _ = trade_off_graph()
        date_first, _ = compare_options(_option_graphs(g), ["y1", "y2"], runs=50,
                                        weights={"y1": 8, "y2": 1})
        team_first, _ = compare_options(_option_graphs(g), ["y1", "y2"], runs=50,
                                        weights={"y1": 1, "y2": 8})
        assert date_first["O2"].p_best == 1.0 and team_first["O1"].p_best == 1.0
        assert date_first["O1"].outcomes["y1"].point == team_first["O1"].outcomes["y1"].point

    def test_build_comparison_reports_the_trade_off(self):
        g, claims = trade_off_graph()
        result = build_comparison(g, claims, ANCHOR, runs=100,
                                  priorities={"Y1": "critical", "Y2": "low"})
        q3, q4 = result.options
        assert q3.outcomes["Y1"]["point"] == pytest.approx(0.3)
        assert q4.outcomes["Y1"]["point"] == pytest.approx(0.86)
        assert q4.weighted.score > q3.weighted.score
        assert result.leader == "O2"
        (pair,) = result.robustness
        assert pair["summary"] == dr.PAIR_MIXED
        y1, y2 = pair["outcomes"]
        assert (y1["higher"], y1["verdict"]) == ("O2", dr.ROBUST)
        assert (y2["higher"], y2["verdict"]) == ("O1", dr.ROBUST)
        assert pair["weighted"]["higher"] == "O2"
        payload = result.as_dict()
        assert payload["priorities"][0]["importance"] == "critical"
        assert payload["options"][1]["weighted"]["contributions"]["Y1"] > 0

    def test_priorities_never_change_the_model_implied_outcomes(self):
        g, claims = trade_off_graph()
        a = build_comparison(g, claims, ANCHOR, runs=50, priorities={"Y1": "critical"})
        b = build_comparison(g, claims, ANCHOR, runs=50, priorities={"Y2": "critical"})
        assert [o.outcomes for o in a.options] == [o.outcomes for o in b.options]
        assert a.headline_pair == b.headline_pair or set(a.headline_pair) == set(b.headline_pair)

    def test_no_weight_at_all_names_no_leader(self):
        g, claims = trade_off_graph()
        result = build_comparison(g, claims, ANCHOR, runs=30, priorities={"Y1": "none", "Y2": "none"})
        assert result.leader is None and not result.decisive
        assert all(o.weighted is None for o in result.options)
        # Review fix: no weighted view means nothing to explain. Drivers used to
        # be ranked on a hidden equal-weight gap and described as "the weighted
        # view", and information priority, automatic scenarios and the
        # assumption register built on them.
        assert result.drivers == [] and result.driver_impacts == []
        assert result.headline_pair is None


# ── Driver sensitivity ──────────────────────────────────────────────────────


class TestSensitivity:
    def _ranked(self, g, weights=None):
        graphs = _option_graphs(g)
        base, drivers = perturbation_drivers(graphs, ["y1", "y2"], fixed_nodes={"bonus", "slack"})
        return rank_drivers(base, drivers, "O1", "O2", weights or {"y1": 1, "y2": 1})

    def test_deterministic(self):
        g, _ = trade_off_graph()
        first = [(d.driver.key, d.impact) for d in self._ranked(g)]
        assert first == [(d.driver.key, d.impact) for d in self._ranked(g)]

    def test_levers_and_outcomes_are_never_perturbed(self):
        g, _ = trade_off_graph()
        keys = {d.driver.key for d in self._ranked(g)}
        assert keys.isdisjoint({"bonus", "slack", "y1", "y2"})
        assert "morale" in keys and "vendor" in keys  # root claims the options do not set

    def test_ranking_by_effect_on_the_gap(self):
        g, _ = trade_off_graph(bonus_confidence=0.2)
        ranked = self._ranked(g)
        assert ranked[0].driver.key == "bonus->y2"  # least sure of, most leverage on the gap
        assert [d.impact for d in ranked] == sorted((d.impact for d in ranked), reverse=True)

    def test_an_input_that_can_reverse_the_comparison(self):
        g, _ = trade_off_graph(bonus_confidence=0.2)
        top = self._ranked(g)[0]
        assert top.base_gap > 0 and top.flip == FLIPS and top.low_gap < 0

    def test_inputs_that_move_both_options_alike_drop_out(self):
        # Vendor feeds Y1 under both options; with Y1 weightless its effect on
        # the weighted gap vanishes, but it still moves the Y1 gap and stays.
        g, _ = trade_off_graph()
        ranked = self._ranked(g, weights={"y1": 0.0, "y2": 1.0})
        vendor = next(d for d in ranked if d.driver.key == "vendor")
        assert vendor.impact == pytest.approx(0.0)
        assert max(abs(h - l) for l, h in vendor.outcome_gaps.values()) > 0

    def test_no_uncertain_inputs(self):
        g = nx.DiGraph()
        g.add_node("a", prior=1.0)
        g.add_node("y", prior=0.5)
        graphs = {"O1": g, "O2": g.copy()}
        base, drivers = perturbation_drivers(graphs, ["y"], fixed_nodes={"a"})
        assert drivers == [] and rank_drivers(base, drivers, "O1", "O2", {"y": 1}) == []

    def test_single_input(self):
        g = nx.DiGraph()
        g.add_node("lever", prior=1.0)
        g.add_node("y", prior=0.5)
        g.add_edge("lever", "y", strength=0.5, evidence_score=1.0, link_confidence=0.5)
        graphs = {"O1": intervene(g, ["lever"], []), "O2": intervene(g, [], ["lever"])}
        base, drivers = perturbation_drivers(graphs, ["y"], fixed_nodes={"lever"})
        ranked = rank_drivers(base, drivers, "O1", "O2", {"y": 1})
        assert [d.driver.key for d in ranked] == ["lever->y"]
        assert ranked[0].flip == NO_FLIP  # O1 stays higher across the whole range

    def test_ties_are_broken_by_key(self):
        g = nx.DiGraph()
        g.add_node("lever", prior=1.0)
        for node in ("b", "a"):
            g.add_node(node, prior=0.5)
        g.add_node("y", prior=0.5)
        for parent in ("b", "a"):
            g.add_edge(parent, "y", strength=0.5, evidence_score=1.0, link_confidence=0.5)
        g.add_edge("lever", "y", strength=0.5, evidence_score=1.0, link_confidence=0.5)
        graphs = {"O1": intervene(g, ["lever"], []), "O2": intervene(g, [], ["lever"])}
        base, drivers = perturbation_drivers(graphs, ["y"], fixed_nodes={"lever"})
        ranked = rank_drivers(base, drivers, "O1", "O2", {"y": 1})
        twins = [d.driver.key for d in ranked if d.driver.key in ("a", "b")]
        assert twins == ["a", "b"]
        assert ranked[[d.driver.key for d in ranked].index("a")].impact == pytest.approx(
            ranked[[d.driver.key for d in ranked].index("b")].impact)

    @pytest.mark.parametrize("base, low, high, status", [
        (0.10, -0.05, 0.20, FLIPS), (0.10, 0.0, 0.20, ERASES), (0.10, 0.05, 0.20, NO_FLIP),
        (0.0, -0.3, 0.3, NO_FLIP),
    ])
    def test_flip_status(self, base, low, high, status):
        assert flip_status(base, low, high) == status

    def test_drivers_are_explained_in_the_comparison(self):
        g, claims = trade_off_graph(bonus_confidence=0.2)
        result = build_comparison(g, claims, ANCHOR, runs=30)
        top = result.drivers[0]
        assert top["kind"] == "link" and top["edge_id"] == "e-bonus"
        assert top["label"] == "bonus → y2"
        assert "can reverse the comparison" in top["explanation"]
        assert top["low"] < top["current"] < top["high"]


# ── Information priority ────────────────────────────────────────────────────


class TestInformationPriority:
    def test_uncertain_high_impact_flipping_inputs_come_first(self):
        g, claims = trade_off_graph(bonus_confidence=0.2)
        result = build_comparison(g, claims, ANCHOR, runs=30)
        text = {c.id: c.text for c in claims}
        items = rank_information(result, g, text)
        assert items[0]["key"] == "bonus->y2" and items[0]["can_flip"]
        assert items[0]["uncertainty_band"] == "high" and items[0]["impact_band"] == "high"
        assert "can reverse the comparison" in items[0]["why"]
        assert [i["score"] for i in items] == sorted((i["score"] for i in items), reverse=True)
        assert len(items) <= 5

    def test_an_open_link_test_becomes_the_action(self):
        g, claims = trade_off_graph(bonus_confidence=0.2)
        result = build_comparison(g, claims, ANCHOR, runs=30)
        test = SimpleNamespace(id="h1", statement="The bonus retains the senior engineers",
                               cheapest_test="Ask the two leads")
        items = rank_information(result, g, {c.id: c.text for c in claims}, {"e-bonus": test})
        assert items[0]["action"] == test.statement and items[0]["how"] == "Ask the two leads"
        assert items[0]["hypothesis_id"] == "h1"

    def test_nothing_to_compare_means_no_items(self):
        g, claims = trade_off_graph()
        result = build_comparison(g, claims, {**ANCHOR, "options": ANCHOR["options"][:1]}, runs=10)
        assert rank_information(result, g, {}) == []

    def test_bands(self):
        assert (band(0.7), band(0.5), band(0.1)) == ("high", "medium", "low")

    def test_impact_is_absolute_not_relative_to_the_largest(self):
        # The demo case: the largest driver moves the gap by 3 points. It must
        # not be called high impact just because nothing else moves more.
        g, claims = trade_off_graph()
        result = build_comparison(g, claims, ANCHOR, runs=10)
        for impact in result.driver_impacts:
            impact.impact = 0.03 if impact is result.driver_impacts[0] else 0.001
        items = rank_information(result, g, {c.id: c.text for c in claims})
        assert items[0]["impact_band"] == "medium" and "3 points" in items[0]["why"]
        # Below half a point, and flipping nothing: not listed at all.
        assert len(items) == 1 or all(
            i["key"] == items[0]["key"] or i["can_flip"] for i in items)


# ── What would change my mind ───────────────────────────────────────────────

NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)


def _theory(option, effect, *, reaches=True, title="t"):
    return SimpleNamespace(id=uuid4(), theory_key=uuid4(), title=title, option_key=option,
                           predicted_effect=effect, reaches_outcome=reaches, is_stale=False,
                           adjusted_score=0.6, confidence=0.6)


def _tripwire(direction, *, decisiveness="moderate", status="pending", due_in=10):
    return SimpleNamespace(id=uuid4(), observable=f"{direction} {decisiveness}", direction=direction,
                           decisiveness=decisiveness, status=status,
                           check_by=NOW + timedelta(days=due_in))


class TestMindChangers:
    def test_a_threatening_theory_inverts_the_effect(self):
        assert for_option(WEAKEN, "achieves") == WEAKEN
        assert for_option(WEAKEN, "threatens") == STRENGTHEN

    def test_signals_come_only_from_existing_tests(self):
        theory = _theory("O1", "achieves")
        hypothesis = SimpleNamespace(id=uuid4(), statement="Vendor delivery drives the date",
                                     refuted_if="Date met despite a late vendor",
                                     cheapest_test="Ask", status="open", decisiveness="decisive")
        signals = theory_signals(theory, [_tripwire("falsifies")], [hypothesis], [], 0.5, now=NOW)
        assert {s["kind"] for s in signals} == {"tripwire", "link_test"}
        assert len(signals) == 3  # a tripwire, and a link test both ways
        refuted = next(s for s in signals if s["condition"] == "if the link is refuted")
        assert refuted["text"] == "Date met despite a late vendor"
        assert refuted["likelihood_ratio"] == pytest.approx(0.1)  # decisive

    def test_overdue_and_resolved_statuses(self):
        theory = _theory("O1", "achieves")
        overdue = _tripwire("falsifies", due_in=-1)
        fired = _tripwire("falsifies", status="observed")
        signals = theory_signals(theory, [overdue, fired], [], [], 0.5, now=NOW)
        assert signals[0]["status"] == "overdue" and not signals[0]["resolved"]
        assert signals[1]["resolved"] and signals[1]["fired"] is True
        assert signals[1]["status"] == "happened"

    def test_consolidated_per_option_ranked_by_decisiveness(self):
        achieves = _theory("O1", "achieves", title="Q3 makes the date")
        threatens = _theory("O1", "threatens", title="Q3 burns the team")
        situational = _theory(None, None)
        weak = _tripwire("falsifies", decisiveness="weak")
        decisive = _tripwire("falsifies", decisiveness="decisive")
        against_threat = _tripwire("falsifies", decisiveness="moderate")
        signals = {
            str(achieves.id): theory_signals(achieves, [weak, decisive], [], [], 0.5, now=NOW),
            str(threatens.id): theory_signals(threatens, [against_threat], [], [], 0.5, now=NOW),
            str(situational.id): theory_signals(situational, [_tripwire("confirms")], [], [], 0.5, now=NOW),
        }
        beliefs = {str(achieves.theory_key): 0.68, str(threatens.theory_key): None}
        (q3, q4) = consolidate(ANCHOR, [achieves, threatens, situational], beliefs, signals)
        assert [s["id"] for s in q3["weaken"]] == [str(decisive.id), str(weak.id)]
        # Falsifying "Q3 burns the team" strengthens the case for Q3.
        assert [s["id"] for s in q3["strengthen"]] == [str(against_threat.id)]
        assert q3["theories"][0]["conviction"] == 0.68
        assert q4["weaken"] == [] and q4["strengthen"] == [] and q4["theories"] == []

    def test_unresolved_signals_rank_above_resolved_ones(self):
        theory = _theory("O1", "achieves")
        resolved = _tripwire("falsifies", decisiveness="decisive", status="not_observed")
        open_one = _tripwire("falsifies", decisiveness="weak")
        signals = {str(theory.id): theory_signals(theory, [resolved, open_one], [], [], 0.5, now=NOW)}
        (q3, _) = consolidate(ANCHOR, [theory], {}, signals)
        assert [s["id"] for s in q3["weaken"]] == [str(open_one.id), str(resolved.id)]


# ── The report ──────────────────────────────────────────────────────────────

from decision_studio.reasoning.brief_view import (  # noqa: E402
    build_forecast,
    build_mind_changers,
    build_robustness,
)


class TestReportViews:
    def _payload(self, **priorities):
        g, claims = trade_off_graph(bonus_confidence=0.2)
        return build_comparison(g, claims, ANCHOR, runs=60, priorities=priorities or None).as_dict()

    def test_two_tables_model_implied_then_weighted(self):
        forecast = build_forecast(self._payload(Y1="critical", Y2="low"))
        assert forecast.outcomes == ["Y1 Ship on date (Critical)", "Y2 Keep the team (Low)"]
        assert forecast.rows[1][1][0].startswith("86%")  # a probability, with its range
        assert forecast.weighted_rows[1][2].endswith("/ 100")  # points, not a percentage
        assert "Critical" in forecast.priorities_line and "of the weight" in forecast.priorities_line
        assert forecast.headline.startswith("Based on the priorities entered, the weighted model view")
        assert "O2 (Q4)" in forecast.headline and "remains the decider's" in forecast.headline
        for word in ("recommend", "best", "correct"):
            assert word not in forecast.headline.lower()
        assert "not a probability" in forecast.weighted_caveat

    def test_defaults_are_marked_in_the_report(self):
        forecast = build_forecast(self._payload())
        assert forecast.priorities_line.count("(not set)") == 2

    def test_robustness_answers_the_three_questions(self):
        robustness = build_robustness(self._payload())
        assert robustness.pair == "O1 Q3 vs O2 Q4"
        assert any("robustly higher on Y1" in r for r in robustness.robust)
        assert robustness.flips and "bonus → y2" in robustness.flips[0]
        assert "not an empirical forecast" in robustness.method

    def test_mind_changers_are_summarised_per_option(self):
        options = [{
            "key": "O1", "label": "Q3",
            "theories": [{"title": "Vendor decides Q3", "conviction": 0.68}],
            "weaken": [{"text": "Vendor misses Aug 15", "condition": "if it happens",
                        "decisiveness": "decisive", "status": "pending"}] * 3,
            "strengthen": [],
        }, {"key": "O2", "label": "Q4", "theories": [], "weaken": [], "strengthen": []}]
        (q3,) = build_mind_changers(options)
        assert q3.convictions == ["Vendor decides Q3: conviction 68%"]
        assert len(q3.weaken) == 2 and "decisive; not observed yet" in q3.weaken[0]
