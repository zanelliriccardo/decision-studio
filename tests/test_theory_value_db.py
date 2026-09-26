"""End to end: option-bound theories, conviction, tripwires, link tests, field results.

Runs the anchored pipeline from test_anchor_pipeline_db, then generates theories
with a fake model that cites the real reference tokens from the prompt — so the
validation under test is the production one. Skips without a database.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from decision_studio.api.routes.reasoning import list_theories
from decision_studio.db.models import Experiment, TheoryTripwire
from decision_studio.llm.prompts.link_hypotheses import LINK_HYPOTHESIS_SYSTEM
from decision_studio.llm.prompts.theory_generation import THEORY_GENERATION_SYSTEM
from decision_studio.pipeline.orchestrator import CausalPipeline
from decision_studio.reasoning import adversary, experiments, link_tests, theory_value
from decision_studio.reasoning.theories import generate_theories
from decision_studio.reasoning.theory_value import bayes_update
from tests.conftest import FakeEmbedder, FakeLLM
from tests.test_anchor_pipeline_db import (  # noqa: F401 - the fixture is used by name
    MATERIAL,
    _pipeline_llm,
    _project,
    session,
)


def _theory(title, chain, claims, edges, option, effect):
    return {
        "title": title, "summary": f"{title}, explained.", "status": "hypothesis",
        "causal_chain": chain, "supporting_claim_refs": claims,
        "supporting_edge_refs": edges, "supporting_evidence_refs": [],
        "contradicting_evidence_refs": [], "weak_assumptions": [], "confidence": 0.6,
        "business_impact": "high", "recommendation": "Act on it.",
        "option_key": option, "predicted_effect": effect, "outcome_keys": [],
        "previous_theory_key": "", "change_explanation": "",
    }


def _theories(user, schema):
    """Cite the prompt's own tokens: an edge into the outcome, and a lone claim."""
    claims = re.findall(r"^- \[(C\d+)\] \(\w+, confidence=[\d.]+\) (.*)$", user, re.M)
    outcome = next(ref for ref, rest in claims if "OUTCOME" in rest)
    edges = re.findall(r"^- \[(E\d+)\] (C\d+) -> (C\d+):", user, re.M)
    edge, source = next((e, s) for e, s, t in edges if t == outcome)
    lone = next(ref for ref, rest in claims if "canteen" in rest)
    return {
        "insufficient_reason": "",
        "theories": [
            _theory("Vendor slippage decides Q3", [source, edge, outcome],
                    [source, outcome], [edge], "O1", "achieves"),
            # An option the anchor does not have, and a chain that goes nowhere.
            _theory("The canteen matters", [lone], [lone], [], "O9", "threatens"),
        ],
    }


async def _anchored_project_with_theories(session):
    project = await _project(session, "Should we commit to Q3?")
    await CausalPipeline(session, _pipeline_llm(), FakeEmbedder()).run(
        str(project.id), MATERIAL, max_layers=1
    )
    llm = FakeLLM([(THEORY_GENERATION_SYSTEM, _theories)])
    result = await generate_theories(session, project.id, llm=llm)
    return project, {t.title: t for t in result.theories}


async def test_theories_are_bound_to_options_and_checked_against_the_graph(session):
    project, theories = await _anchored_project_with_theories(session)

    vendor = theories["Vendor slippage decides Q3"]
    assert vendor.option_key == "O1"
    assert vendor.predicted_effect == "achieves"
    # Reaching the outcome is computed from the chain, and adds its key.
    assert vendor.reaches_outcome is True
    assert vendor.outcome_keys == ["Y1"]

    canteen = theories["The canteen matters"]
    assert canteen.option_key is None  # O9 is not an option
    assert canteen.reaches_outcome is False

    listing = await list_theories(project.id, session)
    coverage = {row.key: row for row in listing.option_coverage}
    assert coverage["O1"].achieves == 1 and coverage["O1"].reaching_outcome == 1
    assert coverage["O2"].achieves == coverage["O2"].threatens == 0


async def test_conviction_moves_only_through_observations(session):
    project, theories = await _anchored_project_with_theories(session)
    theory = theories["Vendor slippage decides Q3"]
    key = theory.theory_key

    # Evidence before any prior waits.
    tripwire = TheoryTripwire(
        theory_id=theory.id, observable="The vendor misses the September drop",
        direction="falsifies", horizon_days=30,
        check_by=datetime.now(timezone.utc) + timedelta(days=30),
    )
    session.add(tripwire)
    await session.commit()

    conviction = await theory_value.state_prior(session, project.id, key, 0.5, method="lottery")
    assert conviction.current == 0.5

    await adversary.record_observation(session, project.id, tripwire.id, observed=True)
    # Recording the same tripwire again corrects the result; it does not add a
    # second piece of evidence (review fix: evidence was double-counted).
    await adversary.record_observation(session, project.id, tripwire.id, observed=True)
    after_tripwire = (await theory_value.convictions(session, project.id, [key]))[str(key)]
    assert after_tripwire.current == pytest.approx(0.2)
    assert len(after_tripwire.steps) == 1
    assert after_tripwire.steps[0].source == "tripwire"

    # A link test: the model writes the hypothesis, the result moves conviction.
    llm = FakeLLM([(LINK_HYPOTHESIS_SYSTEM, lambda u, s: {"hypotheses": [
        {"index": 0, "statement": "Vendor slips push shipping past three weeks",
         "refuted_if": "The vendor ships within a week of the date",
         "cheapest_test": "Ask the vendor's delivery lead"},
    ]})])
    hypotheses = await link_tests.propose_hypotheses(session, project.id, theory.id, llm=llm)
    assert len(hypotheses) == 1 and hypotheses[0].priority > 0
    await link_tests.record_result(session, project.id, hypotheses[0].id, "refuted")
    after_link = (await theory_value.convictions(session, project.id, [key]))[str(key)]
    assert after_link.current == pytest.approx(bayes_update(0.2, [0.25]))
    await session.refresh(theory)
    assert theory.is_stale and "refuted" in theory.stale_reason

    # A field experiment's result counts; a synthetic one cannot be recorded.
    field = Experiment(project_id=project.id, theory_id=theory.id, kind="field",
                       hypothesis="Vendor ships on time", design="Ask", status="designed")
    synthetic = Experiment(project_id=project.id, theory_id=theory.id, kind="synthetic",
                           hypothesis="The room agrees", design="Simulate", status="designed")
    session.add_all([field, synthetic])
    await session.commit()
    executed = await experiments.record_field_result(session, project.id, field.id, "supports")
    assert executed.status == "executed"
    with pytest.raises(ValueError):
        await experiments.record_field_result(session, project.id, synthetic.id, "supports")

    final = (await theory_value.convictions(session, project.id, [key]))[str(key)]
    assert final.current == pytest.approx(bayes_update(0.5, [0.25, 0.25, 2.0]))
    assert [s.source for s in final.steps] == ["tripwire", "link_hypothesis", "field_experiment"]

    # Model confidence was never touched by any of it.
    await session.refresh(theory)
    assert theory.confidence == 0.6


async def test_regenerating_keeps_conviction_and_results(session):
    project, theories = await _anchored_project_with_theories(session)
    first = theories["Vendor slippage decides Q3"]
    key = first.theory_key
    await theory_value.state_prior(session, project.id, key, 0.7)
    pending = TheoryTripwire(theory_id=first.id, observable="Vendor confirms in writing",
                             direction="confirms", horizon_days=10)
    field = Experiment(project_id=project.id, theory_id=first.id, kind="field",
                       hypothesis="h", design="d", status="designed")
    session.add_all([pending, field])
    await session.commit()

    llm = FakeLLM([(THEORY_GENERATION_SYSTEM, _theories)])
    result = await generate_theories(session, project.id, llm=llm)
    again = next(t for t in result.theories if t.title == "Vendor slippage decides Q3")
    assert again.theory_key == key and again.version == 2

    listing = await list_theories(project.id, session)
    current = next(t for t in listing.theories if t.theory_key == key)
    assert current.conviction == pytest.approx(0.7)
    # Commitments follow the theory to its new version (review fix).
    assert [tw.observable for tw in current.tripwires] == ["Vendor confirms in writing"]
    await session.refresh(field)
    assert field.theory_id == again.id


async def test_executive_brief_leads_with_the_answer_and_the_options(session):
    from decision_studio.reasoning.brief import export_brief

    project, theories = await _anchored_project_with_theories(session)
    key = theories["Vendor slippage decides Q3"].theory_key
    await theory_value.state_prior(session, project.id, key, 0.6)

    markdown, media, _ = await export_brief(session, project.id, "markdown")
    assert media.startswith("text/markdown")
    order = [markdown.index(h) for h in (
        "## Executive summary", "## Options at a glance",
        "## The theories on O1", "## Appendix: quality of the analysis",
    )]
    assert order == sorted(order)
    # Q4 was never examined: the brief must say so on page one, not hide it.
    assert "| O2 Commit to Q4 | — | — | Not examined |" in markdown
    assert "No theory examines O2" in markdown
    assert "your conviction 60%" in markdown

    html, _, _ = await export_brief(session, project.id, "html")
    assert "<table>" in html and "<h4>" in html
    pdf, media, name = await export_brief(session, project.id, "pdf")
    assert media == "application/pdf" and pdf.startswith(b"%PDF") and name.endswith(".pdf")
