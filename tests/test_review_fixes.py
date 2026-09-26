"""Regression tests for the bugs found in the logic review (see docs/LOGIC_REVIEW.md)."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import networkx as nx
import pytest

from decision_studio.api.routes.graph import _build_nx_graph
from decision_studio.api.routes.scenarios import _apply_overrides
from decision_studio.graph.belief_propagation import EVIDENCE_FLOOR, propagate_beliefs
from decision_studio.graph.stability import compile_graph, propagate_once
from decision_studio.reasoning.theories import match_previous
from decision_studio.reasoning.validation import ValidatedTheory


def _claim(**kw):
    base = dict(id=uuid4(), text="c", claim_type="FACT", confidence=0.8, prior=0.8,
                order_index=0, logic_gate="or", is_active=True, review_status="accepted")
    return SimpleNamespace(**{**base, **kw})


def _edge(source, target, **kw):
    base = dict(id=uuid4(), source_claim_id=source.id, target_claim_id=target.id,
                mechanism="m", strength=0.6, strength_override=None, link_confidence=0.9,
                time_delay=None, conditions=[], reversible=False, evidence_score=0.0,
                evidences=[], causal_type="direct", condition_type="contributing",
                temporal_window=None, decay_type="none", bias_warnings=[],
                is_feedback=False, is_active=True, review_status="accepted")
    return SimpleNamespace(**{**base, **kw})


def _two_node_graph(has_contradiction: bool) -> nx.DiGraph:
    g = nx.DiGraph()
    g.add_node("a", prior=1.0)
    g.add_node("b")
    g.add_edge("a", "b", strength=1.0, evidence_score=0.0, has_contradiction=has_contradiction)
    return g


class TestContradictionReachesPropagation:
    def test_point_propagation(self):
        unsearched = propagate_beliefs(_two_node_graph(False)).nodes["b"]["belief"]
        contradicted = propagate_beliefs(_two_node_graph(True)).nodes["b"]["belief"]
        assert unsearched == pytest.approx(EVIDENCE_FLOOR)
        assert contradicted < unsearched

    def test_monte_carlo_matches_point_estimate(self):
        g = _two_node_graph(True)
        point = propagate_beliefs(g.copy()).nodes["b"]["belief"]
        assert propagate_once(compile_graph(g))["b"] == pytest.approx(point)


class TestDisplayedGraphHonoursReview:
    def test_rejected_elements_and_overrides(self):
        a, b, c = _claim(), _claim(), _claim(review_status="rejected")
        kept = _edge(a, b, strength=0.6, strength_override=0.2)
        rejected_edge = _edge(b, a, review_status="rejected")
        dangling = _edge(a, c)
        g = _build_nx_graph([a, b, c], [kept, rejected_edge, dangling])
        assert set(g.nodes) == {str(a.id), str(b.id)}
        assert list(g.edges) == [(str(a.id), str(b.id))]
        data = g.edges[str(a.id), str(b.id)]
        assert data["strength"] == 0.2  # the user's override, not the model's 0.6
        assert data["link_confidence"] == 0.9

    def test_scenario_value_beats_override(self):
        a, b = _claim(), _claim()
        edge = _edge(a, b, strength_override=0.2)
        patched = _apply_overrides([edge], {str(edge.id): 0.9})[0]
        g = _build_nx_graph([a, b], [patched])
        assert g.edges[str(a.id), str(b.id)]["strength"] == 0.9
        assert edge.strength_override == 0.2  # the stored edge is untouched


def _candidate(option, effect, edges):
    return ValidatedTheory(
        title="t", summary="s", status="hypothesis", confidence=0.5,
        business_impact="high", recommendation="", weak_assumptions=[],
        supporting_claim_ids=[], supporting_edge_ids=edges,
        supporting_evidence_ids=[], contradicting_evidence_ids=[], causal_chain=[],
        option_key=option, predicted_effect=effect,
    )


def _previous(option, effect, edges):
    return SimpleNamespace(
        theory_key=uuid4(), option_key=option, predicted_effect=effect,
        edge_links=[SimpleNamespace(edge_id=e) for e in edges],
    )


class TestTheoryMatching:
    def test_same_path_opposite_effect_is_a_new_theory(self):
        # Otherwise a conviction stated for "Q3 achieves" would transfer to
        # "Q3 threatens" because the two read the same links.
        previous = _previous("O1", "achieves", ["e1", "e2"])
        assert match_previous(_candidate("O1", "threatens", ["e1", "e2"]), [previous], set()) is None

    def test_other_option_is_a_new_theory(self):
        previous = _previous("O1", "achieves", ["e1", "e2"])
        assert match_previous(_candidate("O2", "achieves", ["e1", "e2"]), [previous], set()) is None

    def test_same_claim_still_matches(self):
        previous = _previous("O1", "achieves", ["e1", "e2"])
        assert match_previous(_candidate("O1", "achieves", ["e1", "e2"]), [previous], set()) is previous

    def test_legacy_theories_without_options_still_match(self):
        previous = _previous(None, None, ["e1", "e2"])
        assert match_previous(_candidate("O1", "achieves", ["e1", "e2"]), [previous], set()) is previous


def test_usage_is_attributed_to_the_running_stage():
    # set_stage had lost its `def` line, so every call landed under "other".
    from types import SimpleNamespace as NS

    from decision_studio.llm import usage

    ledger = usage.start_ledger("p")
    usage.set_stage("claim_extraction")
    usage.record_usage("gpt-4o", NS(prompt_tokens=10, completion_tokens=5))
    assert usage.current_ledger() is ledger
    assert ledger.stages["claim_extraction"].calls == 1
