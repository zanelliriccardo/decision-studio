"""Conviction arithmetic, replay rules, option coverage and link ranking."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import networkx as nx
import pytest

from decision_studio.graph.value_of_information import (
    break_cycles,
    link_uncertainty,
    rank_links,
)
from decision_studio.reasoning.theory_value import (
    LIKELIHOOD_SCALE,
    MAX_CONVICTION,
    MIN_CONVICTION,
    bayes_update,
    option_coverage,
    replay,
    tripwire_likelihood,
)

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _row(kind, minutes, value=None, lr=None, source="elicited"):
    return SimpleNamespace(
        id=uuid4(), kind=kind, value=value, likelihood_ratio=lr, source=source,
        source_id=None, method="lottery" if kind == "prior" else None, note=None,
        created_at=T0 + timedelta(minutes=minutes),
    )


class TestBayes:
    def test_even_odds_times_four(self):
        assert bayes_update(0.5, [4.0]) == pytest.approx(0.8)

    def test_order_does_not_matter(self):
        assert bayes_update(0.3, [4.0, 0.5, 2.0]) == pytest.approx(bayes_update(0.3, [2.0, 4.0, 0.5]))

    def test_symmetric_scale_cancels(self):
        assert bayes_update(0.37, [LIKELIHOOD_SCALE["strongly_for"],
                                   LIKELIHOOD_SCALE["strongly_against"]]) == pytest.approx(0.37)

    def test_certainty_cannot_be_stated_or_reached(self):
        assert bayes_update(1.0, []) == MAX_CONVICTION
        assert bayes_update(0.9, [20.0] * 10) == MAX_CONVICTION
        assert bayes_update(0.1, [0.05] * 10) == MIN_CONVICTION
        # Still movable from the bound: certainty would absorb every update.
        assert bayes_update(MAX_CONVICTION, [0.25]) < MAX_CONVICTION

    def test_tripwire_defaults(self):
        assert tripwire_likelihood("falsifies", True) < 1 < tripwire_likelihood("falsifies", False)
        assert tripwire_likelihood("confirms", True) > 1 > tripwire_likelihood("confirms", False)
        # A fired falsifier counts for more than a quiet one.
        assert 1 / tripwire_likelihood("falsifies", True) > tripwire_likelihood("falsifies", False)


class TestReplay:
    def test_no_prior_means_no_conviction_and_evidence_waits(self):
        conviction = replay("k", [_row("evidence", 1, lr=4.0, source="tripwire")])
        assert conviction.current is None
        assert conviction.steps[0].applied is False

    def test_evidence_after_the_prior_moves_it(self):
        conviction = replay("k", [
            _row("prior", 0, value=0.5),
            _row("evidence", 1, lr=4.0, source="tripwire"),
            _row("evidence", 2, lr=0.5, source="link_hypothesis"),
        ])
        assert conviction.prior == 0.5
        assert conviction.current == pytest.approx(bayes_update(0.5, [4.0, 0.5]))
        assert [s.after for s in conviction.steps] == [
            pytest.approx(0.8), pytest.approx(bayes_update(0.5, [4.0, 0.5]))
        ]

    def test_restated_prior_absorbs_earlier_evidence(self):
        # Restating after seeing a test: the test is already in the new prior,
        # so applying it again would count it twice.
        conviction = replay("k", [
            _row("prior", 0, value=0.5),
            _row("evidence", 1, lr=4.0, source="tripwire"),
            _row("prior", 2, value=0.7),
            _row("evidence", 3, lr=2.0, source="field_experiment"),
        ])
        assert conviction.prior == 0.7
        assert [s.applied for s in conviction.steps] == [False, True]
        assert conviction.current == pytest.approx(bayes_update(0.7, [2.0]))


class TestCoverage:
    def test_counts_per_option_and_shows_uncovered(self):
        anchor = {"options": [{"key": "O1", "label": "Q3"}, {"key": "O2", "label": "Q4"}]}
        theories = [
            SimpleNamespace(option_key="O1", predicted_effect="achieves", reaches_outcome=True),
            SimpleNamespace(option_key="O1", predicted_effect="threatens", reaches_outcome=False),
            SimpleNamespace(option_key=None, predicted_effect="unclear", reaches_outcome=False),
        ]
        rows = option_coverage(anchor, theories)
        assert rows[0] == {"key": "O1", "label": "Q3", "achieves": 1, "threatens": 1,
                           "unclear": 0, "reaching_outcome": 1}
        assert rows[1]["achieves"] == rows[1]["threatens"] == rows[1]["unclear"] == 0

    def test_no_anchor_no_rows(self):
        assert option_coverage(None, []) == []


def _chain_graph():
    g = nx.DiGraph()
    for node, prior in (("a", 0.7), ("b", 0.5), ("Y", 0.5), ("side", 0.5)):
        g.add_node(node, prior=prior, confidence=prior)
    g.add_edge("a", "b", strength=0.7, evidence_score=0.5)
    g.add_edge("b", "Y", strength=0.6, evidence_score=0.5)
    g.add_edge("side", "a", strength=0.4, evidence_score=0.5)
    return g


class TestValueOfInformation:
    def test_uncertainty(self):
        assert link_uncertainty(1.0, 1.0) == 0.0
        assert link_uncertainty(None, None) == pytest.approx(0.625)
        assert link_uncertainty(0.9, 0.9) < link_uncertainty(0.4, 0.2)

    def test_ranks_by_leverage_times_uncertainty(self):
        links = [
            {"edge_id": "e1", "source": "a", "target": "b", "uncertainty": 0.2},
            {"edge_id": "e2", "source": "b", "target": "Y", "uncertainty": 0.8},
        ]
        ranked = rank_links(_chain_graph(), links, "Y")
        assert [r["edge_id"] for r in ranked] == ["e2", "e1"]
        assert all(r["leverage"] > 0 for r in ranked)
        assert ranked[0]["priority"] == pytest.approx(ranked[0]["leverage"] * 0.8, abs=1e-3)

    def test_falls_back_to_uncertainty_without_leverage(self):
        links = [
            {"edge_id": "e1", "source": "a", "target": "b", "uncertainty": 0.3},
            {"edge_id": "e2", "source": "b", "target": "Y", "uncertainty": 0.6},
        ]
        # "side" is upstream of everything; nothing on the chain moves it.
        ranked = rank_links(_chain_graph(), links, "side")
        assert [r["priority"] for r in ranked] == [0.6, 0.3]

    def test_break_cycles_removes_the_weakest(self):
        g = nx.DiGraph()
        g.add_edge("a", "b", strength=0.9)
        g.add_edge("b", "a", strength=0.1)
        break_cycles(g)
        assert list(g.edges) == [("a", "b")]
