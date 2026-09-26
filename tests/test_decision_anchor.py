"""The decision anchor: normalising, rendering, drafting and relevance scoring."""

from __future__ import annotations

from decision_studio.llm.prompts.decision_anchor import (
    ANCHOR_DRAFT_SYSTEM,
    RELEVANCE_SYSTEM,
)
from decision_studio.reasoning.decision_anchor import (
    MAX_OPTIONS,
    RELEVANCE_BATCH,
    STATUS_CONFIRMED,
    STATUS_DRAFT,
    anchor_keys,
    clean_claim_scores,
    draft_anchor,
    normalise_anchor,
    outcome_claim_text,
    render_anchor,
    score_relevance,
)
from tests.conftest import FakeLLM

ANCHOR = {
    "decision": "Whether to commit publicly to the Q3 delivery date",
    "options": [{"label": "Commit to Q3"}, {"label": "Commit to Q4"}],
    "outcomes": [{"label": "Ship on the committed date", "measure": "within 3 weeks"}],
    "deadline": "2026-10-15",
    "constraints": ["No additional headcount"],
}


class TestNormalise:
    def test_no_decision_is_no_anchor(self):
        assert normalise_anchor({"options": [{"label": "A"}]}) is None
        assert normalise_anchor({"decision": "   "}) is None
        assert normalise_anchor(None) is None
        assert normalise_anchor("a string") is None

    def test_assigns_keys_in_order(self):
        anchor = normalise_anchor(ANCHOR)
        assert [o["key"] for o in anchor["options"]] == ["O1", "O2"]
        assert [y["key"] for y in anchor["outcomes"]] == ["Y1"]
        assert anchor["status"] == STATUS_DRAFT

    def test_preserves_existing_keys_and_never_reuses_a_deleted_one(self):
        # The user deleted O2 and added a new option. If the new one took "O2",
        # every claim that bore on the deleted option would silently point at it.
        anchor = normalise_anchor({
            "decision": "d",
            "options": [{"key": "O1", "label": "A"}, {"key": "O3", "label": "C"},
                        {"label": "New"}],
        })
        assert [o["key"] for o in anchor["options"]] == ["O1", "O3", "O4"]

    def test_reserved_keys_are_never_reissued(self):
        # The user removed Y2 in the editor and added a new outcome. The
        # submitted anchor no longer shows Y2, but the project used it: reissuing
        # it would rename Y2's graph node and keep its links.
        anchor = normalise_anchor(
            {"decision": "d", "outcomes": [{"key": "Y1", "label": "A"}, {"label": "New"}]},
            reserved={"Y1", "Y2", "O1"},
        )
        assert [y["key"] for y in anchor["outcomes"]] == ["Y1", "Y3"]

    def test_replaces_invalid_and_duplicate_keys(self):
        anchor = normalise_anchor({
            "decision": "d",
            "options": [{"key": "O1", "label": "A"}, {"key": "O1", "label": "B"},
                        {"key": "Y1", "label": "C"}],
        })
        keys = [o["key"] for o in anchor["options"]]
        assert keys[0] == "O1" and len(set(keys)) == 3
        assert all(k.startswith("O") for k in keys)

    def test_caps_and_drops_empty_labels(self):
        anchor = normalise_anchor({
            "decision": "d",
            "options": [{"label": f"opt {i}"} for i in range(10)] + [{"label": ""}],
        })
        assert len(anchor["options"]) == MAX_OPTIONS

    def test_accepts_plain_strings_for_options(self):
        anchor = normalise_anchor({"decision": "d", "options": ["A", "B"]})
        assert [o["label"] for o in anchor["options"]] == ["A", "B"]

    def test_status_override(self):
        assert normalise_anchor(ANCHOR, status=STATUS_CONFIRMED)["status"] == STATUS_CONFIRMED
        assert normalise_anchor({**ANCHOR, "status": "bogus"})["status"] == STATUS_DRAFT


class TestRender:
    def test_empty_without_anchor(self):
        # A placeholder would invite the model to invent a decision.
        assert render_anchor(None) == ""

    def test_includes_every_part_with_keys(self):
        text = render_anchor(normalise_anchor(ANCHOR))
        for fragment in ("Q3 delivery date", "O1: Commit to Q3", "O2: Commit to Q4",
                         "Y1: Ship on the committed date", "within 3 weeks",
                         "2026-10-15", "No additional headcount"):
            assert fragment in text

    def test_outcome_claim_is_a_proposition(self):
        text = outcome_claim_text({"key": "Y1", "label": "Ship on time", "measure": "Q3"})
        assert text == "Success criterion met: Ship on time (Q3)"


class TestCleanScores:
    def test_filters_invented_keys_and_bad_values(self):
        cleaned = clean_claim_scores(
            {"decision_role": "villain", "relevance": 7, "bears_on": ["O1", "O9", 3],
             "relevance_reason": "  affects   O1 "},
            {"O1", "O2", "Y1"},
        )
        assert cleaned == {
            "decision_role": None, "relevance": 1.0,
            "relevance_reason": "affects O1", "bears_on": ["O1"],
        }

    def test_accepts_reason_alias_and_empty_bears_on(self):
        cleaned = clean_claim_scores(
            {"decision_role": "background", "relevance": "0.1", "bears_on": [],
             "reason": "context"},
            {"O1"},
        )
        assert cleaned["relevance"] == 0.1
        assert cleaned["bears_on"] is None
        assert cleaned["relevance_reason"] == "context"


class TestDraft:
    async def test_no_objective_means_no_draft_and_no_call(self):
        llm = FakeLLM()
        assert await draft_anchor(llm, "", "material") is None
        assert llm.calls == []

    async def test_draft_is_normalised(self):
        llm = FakeLLM([(ANCHOR_DRAFT_SYSTEM, lambda u, s: ANCHOR)])
        anchor = await draft_anchor(llm, "Q3 or not", "some material")
        assert anchor["status"] == STATUS_DRAFT
        assert anchor_keys(anchor) == {"O1", "O2", "Y1"}
        assert "Q3 or not" in llm.calls[0]["user"]

    async def test_empty_model_decision_falls_back_to_the_users_words(self):
        llm = FakeLLM([(ANCHOR_DRAFT_SYSTEM, lambda u, s: {"decision": ""})])
        anchor = await draft_anchor(llm, "Q3 or not", "m")
        assert anchor["decision"] == "Q3 or not"

    async def test_failure_returns_none(self):
        llm = FakeLLM([(ANCHOR_DRAFT_SYSTEM, lambda u, s: RuntimeError("down"))])
        assert await draft_anchor(llm, "Q3 or not", "m") is None


class TestScoreRelevance:
    async def test_batches_and_maps_indices(self):
        anchor = normalise_anchor(ANCHOR)
        texts = [f"claim {i}" for i in range(RELEVANCE_BATCH * 2 + 5)]

        def handler(user, schema):
            lines = [line for line in user.splitlines() if line.startswith("[")]
            return {"scores": [
                {"index": i, "decision_role": "lever", "relevance": 0.9,
                 "bears_on": ["O1", "O7"], "reason": line}
                for i, line in enumerate(lines)
            ]}

        llm = FakeLLM([(RELEVANCE_SYSTEM, handler)])
        results = await score_relevance(llm, anchor, texts)
        assert len(llm.calls) == 3
        assert all(r is not None for r in results)
        # Each result belongs to its own claim, across batch boundaries.
        assert results[RELEVANCE_BATCH + 3]["relevance_reason"].endswith(
            f"claim {RELEVANCE_BATCH + 3}"
        )
        assert results[0]["bears_on"] == ["O1"]

    async def test_failed_batch_leaves_its_claims_unscored(self):
        anchor = normalise_anchor(ANCHOR)
        calls = {"n": 0}

        def handler(user, schema):
            calls["n"] += 1
            if "[0] claim 0\n" in user or user.endswith("[0] claim 0"):
                return RuntimeError("batch failed")
            lines = [line for line in user.splitlines() if line.startswith("[")]
            return {"scores": [
                {"index": i, "decision_role": "background", "relevance": 0.0,
                 "bears_on": [], "reason": "x"} for i in range(len(lines))
            ]}

        llm = FakeLLM([(RELEVANCE_SYSTEM, handler)])
        texts = [f"claim {i}" for i in range(RELEVANCE_BATCH + 2)]
        results = await score_relevance(llm, anchor, texts)
        assert results[:RELEVANCE_BATCH] == [None] * RELEVANCE_BATCH
        assert results[RELEVANCE_BATCH]["relevance"] == 0.0

    async def test_no_anchor_scores_nothing(self):
        llm = FakeLLM()
        assert await score_relevance(llm, None, ["a", "b"]) == [None, None]
        assert llm.calls == []


def _strict_problems(schema: dict, path: str = "$") -> list[str]:
    """Strict structured output: every object closed, every property required."""
    problems: list[str] = []
    if schema.get("type") == "object":
        props = set(schema.get("properties", {}))
        if set(schema.get("required", [])) != props:
            problems.append(f"{path}: required != properties")
        if schema.get("additionalProperties") is not False:
            problems.append(f"{path}: additionalProperties is not false")
        for key, sub in schema.get("properties", {}).items():
            problems += _strict_problems(sub, f"{path}.{key}")
    if schema.get("type") == "array":
        problems += _strict_problems(schema.get("items", {}), f"{path}[]")
    return problems


def test_anchor_schemas_satisfy_strict_mode():
    from decision_studio.llm.prompts.claim_extraction import claim_extraction_schema
    from decision_studio.llm.prompts.decision_anchor import (
        ANCHOR_DRAFT_SCHEMA,
        RELEVANCE_SCHEMA,
    )

    from decision_studio.llm.prompts.link_hypotheses import LINK_HYPOTHESIS_SCHEMA
    from decision_studio.llm.prompts.theory_generation import THEORY_GENERATION_SCHEMA

    for schema in (ANCHOR_DRAFT_SCHEMA, RELEVANCE_SCHEMA,
                   claim_extraction_schema(True), claim_extraction_schema(False),
                   THEORY_GENERATION_SCHEMA, LINK_HYPOTHESIS_SCHEMA):
        assert _strict_problems(schema) == []
