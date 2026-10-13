"""The anchoring report computes what it says it computes."""

from __future__ import annotations

from decision_studio.tools.anchor_report import compute_report, render


def test_report_on_an_anchored_graph():
    claims = [
        {"id": "a", "relevance": 0.9, "decision_role": "lever"},
        {"id": "b", "relevance": 0.1, "decision_role": "mechanism"},
        {"id": "c", "relevance": 0.0, "decision_role": "background"},
        {"id": "iso", "relevance": 0.0, "decision_role": "background"},
        {"id": "Y", "origin": "frame", "decision_role": "outcome", "relevance": 1.0},
    ]
    edges = [
        {"source": "a", "target": "b"}, {"source": "b", "target": "Y"},
        {"source": "Y", "target": "c"},
    ]
    report = compute_report(
        claims, edges,
        theory_claims={"t1": {"a", "Y"}, "t2": {"c"}},
        anchor={"decision": "d", "options": [{"key": "O1"}]},
    )
    assert report["claims"] == 4
    assert report["outcome_nodes"] == 1
    assert report["reach_outcome"] == 2  # a, b — not c, which Y causes
    assert report["reach_outcome_share"] == 0.5
    assert report["edges_into_outcomes"] == 1
    assert report["isolated"] == 1
    assert report["components"] == 2
    assert report["peripheral"] == 1  # b: read as background, on the path
    assert report["theories_reaching_outcome"] == 1
    assert report["roles"] == {"lever": 1, "mechanism": 1, "background": 2}
    assert "Reach an outcome" in render(report)


def test_report_on_an_unanchored_graph_says_na():
    claims = [{"id": "a"}, {"id": "b"}]
    report = compute_report(claims, [{"source": "a", "target": "b"}])
    assert report["anchored"] is False
    assert report["reach_outcome"] is None
    assert report["in_lens"] is None
    assert "n/a" in render(report)
