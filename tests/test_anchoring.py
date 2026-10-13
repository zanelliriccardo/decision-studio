"""Graph-side anchoring: distances, relevance, lens, edge priority, discovery gating."""

from __future__ import annotations

import networkx as nx

from decision_studio.graph.anchoring import (
    anchor_distances,
    anchored_edges,
    edge_priority,
    effective_relevance,
    in_lens,
    is_peripheral,
    structural_relevance,
)


def _outcome() -> dict:
    return {"text": "Success criterion met: X", "origin": "frame", "decision_role": "outcome"}


class TestDistances:
    def test_follows_edge_direction_towards_outcomes(self):
        g = nx.DiGraph([("a", "b"), ("b", "Y"), ("Y", "after"), ("c", "a")])
        distances = anchor_distances(g, ["Y"])
        assert distances == {"Y": 0, "b": 1, "a": 2, "c": 3}
        # A consequence of success is not a factor in reaching it.
        assert "after" not in distances

    def test_nearest_of_several_outcomes(self):
        g = nx.DiGraph([("a", "Y1"), ("a", "b"), ("b", "c"), ("c", "Y2")])
        assert anchor_distances(g, ["Y1", "Y2"])["a"] == 1

    def test_missing_outcome_node_is_ignored(self):
        assert anchor_distances(nx.DiGraph([("a", "b")]), ["nope"]) == {}


class TestRelevance:
    def test_structural_decays_with_distance(self):
        values = [structural_relevance(d) for d in (0, 1, 2, 3, 4, 9)]
        assert values == sorted(values, reverse=True)
        assert structural_relevance(None) == 0.0

    def test_effective_is_the_larger_and_never_demotes(self):
        assert effective_relevance(0.1, 1) == structural_relevance(1)
        # A missed edge is not evidence of irrelevance.
        assert effective_relevance(0.9, None) == 0.9
        assert effective_relevance(None, None) is None

    def test_peripheral_is_low_stated_relevance_on_a_path(self):
        assert is_peripheral(0.1, 2)
        assert not is_peripheral(0.8, 2)
        assert not is_peripheral(0.1, None)
        assert not is_peripheral(None, 2)
        assert not is_peripheral(0.0, 0)  # the outcome itself

    def test_lens(self):
        assert in_lens(0.0, 3)
        assert not in_lens(0.0, 4)
        assert in_lens(0.6, None)
        assert not in_lens(0.2, None)


class TestEdgePriority:
    def test_plain_strength_without_relevance(self):
        claims = [{"text": "a"}, {"text": "b"}]
        edge = {"source_idx": 0, "target_idx": 1, "strength": 0.7}
        assert edge_priority(edge, claims) == 0.7

    def test_relevance_reorders_the_budget(self):
        claims = [
            {"text": "bg1", "relevance": 0.0}, {"text": "bg2", "relevance": 0.0},
            {"text": "lever", "relevance": 0.9}, _outcome(),
        ]
        strong_background = {"source_idx": 0, "target_idx": 1, "strength": 0.8}
        moderate_to_outcome = {"source_idx": 2, "target_idx": 3, "strength": 0.6}
        assert edge_priority(moderate_to_outcome, claims) > edge_priority(strong_background, claims)


class TestAnchoredEdges:
    def test_everything_without_an_anchor(self):
        claims = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
        edges = [{"source_idx": 0, "target_idx": 1}, {"source_idx": 1, "target_idx": 2}]
        assert anchored_edges(claims, edges) == edges

    def test_keeps_path_edges_and_relevant_pairs(self):
        claims = [
            {"text": "a", "relevance": 0.1}, {"text": "b", "relevance": 0.1}, _outcome(),
            {"text": "side", "relevance": 0.1}, {"text": "r1", "relevance": 0.8},
            {"text": "r2", "relevance": 0.7},
        ]
        on_path = [{"source_idx": 0, "target_idx": 1}, {"source_idx": 1, "target_idx": 2}]
        off_path = {"source_idx": 1, "target_idx": 3}  # b -> side: not towards Y
        relevant_pair = {"source_idx": 4, "target_idx": 5}
        kept = anchored_edges(claims, [*on_path, off_path, relevant_pair])
        assert kept == [*on_path, relevant_pair]

    def test_falls_back_to_everything_when_nothing_is_anchored_yet(self):
        claims = [{"text": "a", "relevance": 0.1}, {"text": "b", "relevance": 0.1}, _outcome()]
        edges = [{"source_idx": 0, "target_idx": 1}]
        assert anchored_edges(claims, edges) == edges
