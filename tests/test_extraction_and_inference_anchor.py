"""Extraction and causal inference with and without a decision anchor."""

from __future__ import annotations

import numpy as np

from decision_studio.llm.prompts.causal_inference import (
    BFS_EXPANSION_SYSTEM,
    BFS_ROOT_IDENTIFICATION_SYSTEM,
    CAUSAL_INFERENCE_SYSTEM,
)
from decision_studio.llm.prompts.claim_extraction import (
    CLAIM_EXTRACTION_SCHEMA,
    CLAIM_EXTRACTION_SYSTEM,
)
from decision_studio.pipeline.causal_inferrer import CausalInferrer
from decision_studio.pipeline.claim_extractor import ClaimExtractor
from decision_studio.reasoning.decision_anchor import normalise_anchor
from tests.conftest import FakeEmbedder, FakeLLM

ANCHOR = normalise_anchor({
    "decision": "Whether to commit to Q3",
    "options": [{"label": "Commit to Q3"}, {"label": "Commit to Q4"}],
    "outcomes": [{"label": "Ship on time", "measure": "within 3 weeks"}],
})


def _claim(text: str, **extra) -> dict:
    return {
        "text": text, "type": "FACT", "confidence": 0.8, "prior": 0.7,
        "source_interest": "unknown", "source_role": "", "source_sentence": text, **extra,
    }


def _extraction_llm(claims: list[dict]) -> FakeLLM:
    return FakeLLM([
        (lambda s: s.startswith(CLAIM_EXTRACTION_SYSTEM),
         lambda u, s: {"claims": claims, "has_temporal_relevance": False}),
    ])


class TestExtraction:
    async def test_unanchored_run_is_unchanged(self):
        llm = _extraction_llm([_claim("A fact")])
        extractor = ClaimExtractor(llm, FakeEmbedder())
        claims, _ = await extractor.extract("Some text about things.")
        call = llm.calls[0]
        assert call["system"] == CLAIM_EXTRACTION_SYSTEM
        assert call["schema"] is CLAIM_EXTRACTION_SCHEMA
        assert "decision being made" not in call["user"]
        assert "decision_role" not in claims[0]

    async def test_anchored_run_sees_the_decision_and_scores_each_claim(self):
        llm = _extraction_llm([
            _claim("The vendor slipped twice", decision_role="contingency",
                   relevance=0.85, relevance_reason="threatens Y1",
                   bears_on=["O1", "Y1", "O9"]),
            _claim("The office has a canteen", decision_role="background",
                   relevance=0.0, relevance_reason="", bears_on=[]),
        ])
        extractor = ClaimExtractor(llm, FakeEmbedder())
        claims, _ = await extractor.extract(
            "Some text.", extra_context="# How to read this\n- x", anchor=ANCHOR
        )
        call = llm.calls[0]
        # Anchor first, then the intake reading, then the text.
        user = call["user"]
        assert user.index("Whether to commit to Q3") < user.index("How to read this") \
            < user.index("Some text.")
        item = call["schema"]["properties"]["claims"]["items"]
        assert {"decision_role", "relevance", "relevance_reason", "bears_on"} <= set(item["required"])
        # The shared schema object was not mutated.
        assert "decision_role" not in CLAIM_EXTRACTION_SCHEMA["properties"]["claims"]["items"]["properties"]
        # Scored, never filtered: background survives.
        assert [c["text"] for c in claims] == ["The vendor slipped twice", "The office has a canteen"]
        assert claims[0]["bears_on"] == ["O1", "Y1"]  # invented O9 dropped
        assert claims[1]["relevance"] == 0.0

    async def test_embed_claims_keeps_original_order_index(self):
        # Regression: embed_claims renumbered order_index after dropping a
        # near-duplicate, so the orchestrator mapped every later claim onto its
        # neighbour's saved row and deleted the wrong rows.
        texts = ["first", "first again", "second", "third"]
        embedder = FakeEmbedder(same={"first again": "first"})
        extractor = ClaimExtractor(FakeLLM(), embedder)
        claims = [{"text": t, "order_index": i} for i, t in enumerate(texts)]
        kept = await extractor.embed_claims(claims)
        assert [(c["text"], c["order_index"]) for c in kept] == [
            ("first", 0), ("second", 2), ("third", 3)
        ]


def _graph_claims(n_plain: int, embedder: FakeEmbedder) -> list[dict]:
    claims = [
        {"text": f"claim {i}", "embedding": embedder.vector(f"claim {i}")}
        for i in range(n_plain)
    ]
    outcome_text = "Success criterion met: Ship on time"
    claims.append({
        "text": outcome_text, "embedding": embedder.vector(outcome_text),
        "origin": "frame", "decision_role": "outcome",
    })
    return claims


class TestInference:
    def test_outcomes_are_always_candidates(self):
        embedder = FakeEmbedder(dimensions=64)
        claims = _graph_claims(4, embedder)
        # Random unit vectors in 64-d sit well below the 0.3 similarity filter,
        # so without the rule the outcome would never be offered.
        outcome = len(claims) - 1
        sims = [
            float(np.dot(claims[0]["embedding"], claims[j]["embedding"]))
            for j in range(1, len(claims))
        ]
        assert max(sims) < 0.3
        inferrer = CausalInferrer(FakeLLM())
        assert inferrer._find_candidates_for_source(claims, 0) == [outcome]

    async def test_outcomes_are_sinks_and_never_roots(self):
        embedder = FakeEmbedder(dimensions=64)
        claims = _graph_claims(3, embedder)
        outcome = len(claims) - 1

        def expand(user, schema):
            # Every source claims to cause every candidate.
            count = user.split("CANDIDATE CLAIMS:\n", 1)[1].count("\n[") + 1
            return {"caused_claims": [
                {"target_index": i, "mechanism": "a specific mechanism of change",
                 "effect": 0.7, "confidence": 0.8, "causal_type": "direct",
                 "time_delay": "weeks"}
                for i in range(count)
            ]}

        llm = FakeLLM([
            (BFS_ROOT_IDENTIFICATION_SYSTEM,
             lambda u, s: {"root_indices": list(range(len(claims)))}),
            (BFS_EXPANSION_SYSTEM, expand),
        ])
        edges = await CausalInferrer(llm).infer(claims)
        assert edges, "expected edges into the outcome"
        assert all(e["source_idx"] != outcome for e in edges)
        assert {e["source_idx"] for e in edges if e["target_idx"] == outcome} == {0, 1, 2}
        # The outcome was never expanded as a source.
        sources = [c["user"] for c in llm.calls_to(BFS_EXPANSION_SYSTEM)]
        assert not any("SOURCE CLAIM: Success criterion met" in u for u in sources)

    async def test_incremental_pairs_reach_outcomes_and_drop_reversed_links(self):
        embedder = FakeEmbedder(dimensions=64)
        claims = _graph_claims(2, embedder)
        outcome = len(claims) - 1
        inferrer = CausalInferrer(FakeLLM())
        pairs = inferrer._find_incremental_candidate_pairs(claims, {0})
        assert (0, outcome) in pairs

        # A pair judge answering "the outcome causes the claim" is discarded.
        llm = FakeLLM([(CAUSAL_INFERENCE_SYSTEM, lambda u, s: {
            "has_causal_link": True, "direction": "target_to_source",
            "mechanism": "a specific mechanism of change", "effect": 0.7,
            "confidence": 0.8,
        })])
        edges = await CausalInferrer(llm).infer_incremental(claims, {0})
        assert all(e["source_idx"] != outcome for e in edges)
