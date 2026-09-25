"""End to end against a real database: an anchored run, then an anchor edit.

Skips when no database is reachable (see TEST_DATABASE_URL in conftest).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from decision_studio.api.routes.graph import _compute_full_graph
from decision_studio.db.models import Base, CausalEdge, Claim, Project
from decision_studio.llm.prompts.causal_inference import (
    BFS_EXPANSION_SYSTEM,
    BFS_ROOT_IDENTIFICATION_SYSTEM,
    CAUSAL_INFERENCE_SYSTEM,
)
from decision_studio.llm.prompts.claim_extraction import CLAIM_EXTRACTION_SYSTEM
from decision_studio.llm.prompts.decision_anchor import (
    ANCHOR_DRAFT_SYSTEM,
    RELEVANCE_SYSTEM,
)
from decision_studio.pipeline.orchestrator import CausalPipeline
from decision_studio.reasoning import anchor_service
from tests.conftest import TEST_DATABASE_URL, FakeEmbedder, FakeLLM

MATERIAL = (
    "The vendor has slipped the integration twice this year. "
    "The engineering team lost three people in April. "
    "The office canteen was renovated in March. "
    "Customers were promised a Q3 launch at the spring event."
) * 3

DRAFT = {
    "decision": "Whether to commit publicly to the Q3 date",
    "options": [{"label": "Commit to Q3"}, {"label": "Commit to Q4"}],
    "outcomes": [{"label": "Ship on the committed date", "measure": "within 3 weeks"}],
    "deadline": "",
    "constraints": [],
}

CLAIMS = [
    ("The vendor has slipped the integration twice this year", "contingency", 0.9, ["O1", "Y1"]),
    # Under-read by the model, but causally linked: the peripheral case.
    ("The engineering team lost three people in April", "background", 0.1, []),
    ("The office canteen was renovated in March", "background", 0.0, []),
    ("Customers were promised a Q3 launch", "lever", 0.7, ["O1"]),
]


def _extract(user, schema):
    return {
        "has_temporal_relevance": False,
        "claims": [
            {"text": t, "type": "FACT", "confidence": 0.8, "prior": 0.7,
             "source_interest": "disinterested", "source_role": "", "source_sentence": t,
             "decision_role": role, "relevance": rel, "relevance_reason": "r",
             "bears_on": bears}
            for t, role, rel, bears in CLAIMS
        ],
    }


def _expand(user, schema):
    """Link each source to the outcome and nothing else — except the canteen."""
    if "SOURCE CLAIM: The office canteen" in user:
        return {"caused_claims": []}
    candidates = user.split("CANDIDATE CLAIMS:\n", 1)[1].splitlines()
    return {"caused_claims": [
        {"target_index": i, "mechanism": "delays delivery through reduced capacity",
         "effect": 0.7, "confidence": 0.8, "causal_type": "direct", "time_delay": "weeks"}
        for i, line in enumerate(candidates)
        if line.startswith(f"[{i}] Success criterion met")
    ]}


def _pipeline_llm() -> FakeLLM:
    return FakeLLM([
        (ANCHOR_DRAFT_SYSTEM, lambda u, s: DRAFT),
        (lambda s: s.startswith(CLAIM_EXTRACTION_SYSTEM), _extract),
        (BFS_ROOT_IDENTIFICATION_SYSTEM, lambda u, s: {"root_indices": [0, 1, 2, 3]}),
        (BFS_EXPANSION_SYSTEM, _expand),
    ])


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # pragma: no cover - environment dependent
        await engine.dispose()
        pytest.skip(f"No test database: {exc}")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _project(session, objective: str | None) -> Project:
    project = Project(title="Q3", input_text=MATERIAL, decision_objective=objective)
    session.add(project)
    await session.commit()
    return project


async def _claims(session, project_id) -> list[Claim]:
    return list((await session.execute(
        select(Claim).where(Claim.project_id == project_id).order_by(Claim.order_index)
    )).scalars().all())


async def test_anchored_run_builds_a_graph_that_reaches_the_decision(session):
    project = await _project(session, "Should we commit to Q3?")
    llm = _pipeline_llm()
    pipeline = CausalPipeline(session, llm, FakeEmbedder())
    await pipeline.run(str(project.id), MATERIAL, max_layers=1)

    await session.refresh(project)
    assert project.decision_anchor["decision"] == DRAFT["decision"]
    assert project.decision_anchor["status"] == "draft"

    # The extraction prompt carried the decision.
    extraction = [c for c in llm.calls if c["system"].startswith(CLAIM_EXTRACTION_SYSTEM)]
    assert "Commit to Q3" in extraction[0]["user"]

    claims = await _claims(session, project.id)
    outcome = [c for c in claims if c.origin == "frame"]
    assert len(outcome) == 1 and outcome[0].decision_role == "outcome"
    assert outcome[0].metadata_ == {"anchor_key": "Y1"}
    canteen = next(c for c in claims if "canteen" in c.text)
    assert canteen.relevance == 0.0 and canteen.decision_role == "background"
    vendor = next(c for c in claims if "vendor" in c.text)
    assert vendor.bears_on == ["O1", "Y1"]

    edges = list((await session.execute(
        select(CausalEdge).where(CausalEdge.project_id == project.id)
    )).scalars().all())
    assert edges and all(e.target_claim_id == outcome[0].id for e in edges)

    graph = await _compute_full_graph(project.id, session)
    by_text = {c.text: c for c in graph.claims}
    assert graph.decision_anchor["options"][0]["key"] == "O1"
    assert by_text[vendor.text].anchor_distance == 1
    assert by_text[vendor.text].in_lens
    assert by_text[canteen.text].anchor_distance is None
    assert not by_text[canteen.text].in_lens
    team = next(c for c in graph.claims if "three people" in c.text)
    assert team.is_peripheral and team.in_lens
    assert not by_text[vendor.text].is_peripheral
    assert by_text[outcome[0].text].anchor_distance == 0


async def test_run_without_objective_is_unanchored(session):
    project = await _project(session, None)
    llm = _pipeline_llm()
    await CausalPipeline(session, llm, FakeEmbedder()).run(
        str(project.id), MATERIAL, max_layers=1
    )
    assert not llm.calls_to(ANCHOR_DRAFT_SYSTEM)
    extraction = [c for c in llm.calls if c["system"].startswith(CLAIM_EXTRACTION_SYSTEM)]
    assert extraction[0]["system"] == CLAIM_EXTRACTION_SYSTEM
    claims = await _claims(session, project.id)
    assert not any(c.origin == "frame" for c in claims)
    graph = await _compute_full_graph(project.id, session)
    assert all(c.in_lens and not c.is_peripheral for c in graph.claims)


async def test_editing_the_anchor_syncs_outcomes_and_rescores(session):
    project = await _project(session, "Should we commit to Q3?")
    await CausalPipeline(session, _pipeline_llm(), FakeEmbedder()).run(
        str(project.id), MATERIAL, max_layers=1
    )
    await session.refresh(project)
    old_outcome = next(c for c in await _claims(session, project.id) if c.origin == "frame")

    def rescore(user, schema):
        lines = [line for line in user.splitlines() if line.startswith("[")]
        return {"scores": [
            {"index": i, "decision_role": "mechanism", "relevance": 0.42,
             "bears_on": ["Y2"], "reason": "re-scored"} for i in range(len(lines))
        ]}

    edit_llm = FakeLLM([
        (RELEVANCE_SYSTEM, rescore),
        (CAUSAL_INFERENCE_SYSTEM, lambda u, s: {"has_causal_link": False}),
    ])
    anchor = dict(project.decision_anchor)
    anchor["outcomes"] = [
        {"key": "Y1", "label": "Ship within a month of the date", "measure": ""},
        {"label": "Keep the enterprise contract", "measure": ""},
    ]
    result = await anchor_service.save_anchor(session, project.id, anchor, llm=edit_llm)

    report = result["report"]
    assert result["anchor"]["status"] == "confirmed"
    assert report["outcomes_updated"] == 1 and report["outcomes_added"] == 1
    assert report["claims_rescored"] == report["claims_total"] == len(CLAIMS)
    assert edit_llm.calls_to(CAUSAL_INFERENCE_SYSTEM), "new outcome was linked in"

    claims = await _claims(session, project.id)
    frame = {c.metadata_["anchor_key"]: c for c in claims if c.origin == "frame"}
    # Renamed in place: same node, links kept.
    assert frame["Y1"].id == old_outcome.id
    assert "within a month" in frame["Y1"].text
    assert set(frame) == {"Y1", "Y2"}
    assert all(c.relevance == 0.42 for c in claims if c.origin != "frame")

    # Replacing an outcome: the removed one's key is never reissued, so the new
    # outcome gets its own node instead of inheriting the old node's links.
    y2_id = frame["Y2"].id
    anchor = dict(result["anchor"])
    anchor["outcomes"] = [o for o in anchor["outcomes"] if o["key"] == "Y1"] + [
        {"label": "Keep the team intact", "measure": ""}
    ]
    result = await anchor_service.save_anchor(session, project.id, anchor, llm=edit_llm)
    assert [o["key"] for o in result["anchor"]["outcomes"]] == ["Y1", "Y3"]
    assert result["report"]["outcomes_added"] == 1
    assert result["report"]["outcomes_retired"] == 1
    claims = await _claims(session, project.id)
    old_y2 = next(c for c in claims if c.id == y2_id)
    assert old_y2.is_active is False and "Keep the team intact" not in old_y2.text

    # Removing an outcome deactivates its node rather than deleting it.
    anchor = dict(result["anchor"])
    anchor["outcomes"] = [o for o in anchor["outcomes"] if o["key"] == "Y1"]
    result = await anchor_service.save_anchor(session, project.id, anchor, llm=edit_llm)
    assert result["report"]["outcomes_retired"] == 1
    claims = await _claims(session, project.id)
    y3 = next(c for c in claims if c.origin == "frame" and c.metadata_["anchor_key"] == "Y3")
    assert y3.is_active is False
