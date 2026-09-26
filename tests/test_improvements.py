"""Unit tests for the improvements in docs/LOGIC_REVIEW.md, part 2."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from decision_studio.reasoning.outside_view import compare, implied_rate
from decision_studio.reasoning.theory_value import bayes_update, replay

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _row(kind, minutes, *, value=None, lr=None, event=None, source="tripwire"):
    return SimpleNamespace(
        id=uuid4(), kind=kind, value=value, likelihood_ratio=lr, source=source,
        source_id=None, method="direct", note=None, event=event,
        created_at=T0 + timedelta(minutes=minutes),
    )


class TestOneEventCountsOnce:
    def test_two_observations_of_one_event_apply_the_strongest(self):
        rows = [
            _row("prior", 0, value=0.6),
            _row("evidence", 1, lr=0.25, event="Vendor missed 1 August"),
            _row("evidence", 2, lr=0.25, event="  vendor MISSED 1 august ", source="link_hypothesis"),
        ]
        conviction = replay("k", rows)
        assert conviction.current == pytest.approx(bayes_update(0.6, [0.25]))
        counted, duplicate = conviction.steps
        assert counted.applied and counted.duplicate_of is None
        assert not duplicate.applied and duplicate.duplicate_of == counted.id

    def test_the_strongest_counts_even_when_it_came_second(self):
        rows = [
            _row("prior", 0, value=0.6),
            _row("evidence", 1, lr=0.5, event="e"),
            _row("evidence", 2, lr=0.1, event="e"),
        ]
        conviction = replay("k", rows)
        assert conviction.current == pytest.approx(bayes_update(0.6, [0.1]))
        assert [s.applied for s in conviction.steps] == [False, True]

    def test_unnamed_or_different_events_stay_independent(self):
        rows = [
            _row("prior", 0, value=0.6),
            _row("evidence", 1, lr=0.25, event="a"),
            _row("evidence", 2, lr=0.25, event="b"),
            _row("evidence", 3, lr=2.0),
        ]
        assert replay("k", rows).current == pytest.approx(bayes_update(0.6, [0.25, 0.25, 2.0]))

    def test_an_event_known_when_the_prior_was_restated_is_already_in_it(self):
        rows = [
            _row("evidence", 0, lr=0.25, event="e"),
            _row("prior", 1, value=0.3),
            _row("evidence", 2, lr=0.25, event="e"),
        ]
        conviction = replay("k", rows)
        assert conviction.current == pytest.approx(0.3)
        assert not any(s.applied for s in conviction.steps)


def _case(with_outcome=3, total=5):
    return SimpleNamespace(outcome="the date slipped", cases_with_outcome=with_outcome,
                           cases_total=total, base_rate=with_outcome / total)


class TestOutsideView:
    def test_polarity_turns_the_theory_round(self):
        # "We will ship on time" at 85% implies a slip at 15%.
        assert implied_rate(0.85, "opposite") == pytest.approx(0.15)
        assert implied_rate(0.85, "same") == pytest.approx(0.85)

    def test_an_optimistic_conviction_is_flagged(self):
        delta, note = compare(_case(), "opposite", conviction=0.85, model_confidence=0.4)
        assert delta == pytest.approx(0.15 - 0.6)
        assert note.startswith("Differs from your experience") and "your conviction" in note

    def test_agreeing_with_experience_is_not_flagged(self):
        # Before the fix, 0.4 was compared with 0.6 directly and flagged.
        delta, note = compare(_case(), "opposite", conviction=0.4, model_confidence=0.9)
        assert delta == pytest.approx(0.0)
        assert note.startswith("Consistent")

    def test_model_confidence_stands_in_until_a_conviction_is_stated(self):
        _, note = compare(_case(), "same", conviction=None, model_confidence=0.6)
        assert "the model's confidence" in note and note.startswith("Consistent")


# --- What the causal map predicts for each option ---

import networkx as nx  # noqa: E402

from decision_studio.reasoning.option_comparison import build_comparison  # noqa: E402

ANCHOR = {
    "decision": "Commit to Q3 or Q4?",
    "options": [{"key": "O1", "label": "Commit to Q3"}, {"key": "O2", "label": "Commit to Q4"}],
    "outcomes": [{"key": "Y1", "label": "Ship on the committed date"}],
}


def _claim_row(cid, role, bears, origin="extraction"):
    return SimpleNamespace(id=cid, text=cid, decision_role=role, bears_on=bears, origin=origin)


def _q3_graph():
    """Q3 compresses testing, which threatens the date; Q4 adds slack, which helps it."""
    g = nx.DiGraph()
    for node in ("compress", "slack", "defects", "y1"):
        g.add_node(node, prior=0.5)
    g.add_node("vendor", prior=0.3)  # a contingency either way
    kw = dict(evidence_score=0.5, link_confidence=0.8, causal_type="direct")
    g.add_edge("compress", "defects", strength=0.8, **kw)
    g.add_edge("defects", "y1", strength=0.7, causal_type="inhibiting",
               evidence_score=0.5, link_confidence=0.8)
    g.add_edge("slack", "y1", strength=0.8, **kw)
    g.add_edge("vendor", "y1", strength=0.3, **kw)
    claims = [
        _claim_row("compress", "lever", ["O1"]),
        _claim_row("slack", "lever", ["O2"]),
        _claim_row("defects", "mechanism", []),
        _claim_row("vendor", "contingency", ["O1", "O2"]),
        _claim_row("y1", "outcome", ["Y1"], origin="frame"),
    ]
    return g, claims


class TestOptionComparison:
    def test_each_option_is_an_intervention_on_its_levers(self):
        graph, claims = _q3_graph()
        result = build_comparison(graph, claims, ANCHOR, runs=200)
        q3, q4 = result.options
        assert [c for c, _ in q3.levers_on] == ["compress"]
        assert [c for c, _ in q3.levers_off] == ["slack"]
        assert q3.status == q4.status == "modelled"
        # Q4: slack on, no compression. Q3: compression on, no slack.
        assert q4.outcomes["Y1"]["point"] > q3.outcomes["Y1"]["point"]
        assert q4.p_best > 0.9 and result.decisive and result.leader == "O2"
        assert q3.p_best + q4.p_best == pytest.approx(1.0)
        # The caller's graph is untouched.
        assert graph.nodes["compress"]["prior"] == 0.5 and graph.in_degree("compress") == 0

    def test_identical_options_are_a_tie_not_a_finding(self):
        graph, claims = _q3_graph()
        for claim in claims:
            if claim.decision_role == "lever":
                claim.decision_role = "mechanism"
        result = build_comparison(graph, claims, ANCHOR, runs=50)
        assert result.unavailable and "cannot tell the options apart" in result.unavailable

    def test_a_lever_with_no_path_to_success_is_said_so(self):
        graph, claims = _q3_graph()
        graph.remove_edge("slack", "y1")
        claims[0].bears_on = ["O1", "O2"]  # compression now comes with either option
        result = build_comparison(graph, claims, ANCHOR, runs=50)
        q3, q4 = result.options
        assert q4.status == "no_path" and q4.reaches_outcome is False
        assert q3.status == "no_path"  # it only switches slack off, which leads nowhere
        assert q3.p_best == pytest.approx(0.5)  # indistinguishable: a tie


# --- Theories ranked by what was measured, not the model's impact label ---

from decision_studio.reasoning.theories import rank_key  # noqa: E402


def _ranked_theory(title, *, impact="low", reaches=True, stale=False, score=0.5):
    return SimpleNamespace(title=title, business_impact=impact, reaches_outcome=reaches,
                           is_stale=stale, adjusted_score=score, confidence=score)


def test_ranking_ignores_the_models_impact_label():
    critical_but_off_target = _ranked_theory("a", impact="critical", reaches=False, score=0.9)
    low_but_on_target = _ranked_theory("b", impact="low", score=0.4)
    stale = _ranked_theory("c", stale=True, score=0.9)
    order = sorted([critical_but_off_target, stale, low_but_on_target],
                   key=lambda t: rank_key(t, None))
    assert [t.title for t in order] == ["b", "c", "a"]


def test_a_stated_conviction_replaces_the_model_score():
    confident = _ranked_theory("model says 90%", score=0.9)
    believed = _ranked_theory("decider says 95%", score=0.3)
    doubted = _ranked_theory("decider says 5%", score=0.95)
    convictions = {"decider says 95%": 0.95, "decider says 5%": 0.05}
    order = sorted([confident, believed, doubted],
                   key=lambda t: rank_key(t, convictions.get(t.title)))
    assert [t.title for t in order] == ["decider says 95%", "model says 90%", "decider says 5%"]
