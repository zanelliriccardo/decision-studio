"""The decision workspace through its API. Skips without a database."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from decision_studio.api.routes.decision_workspace import (
    ScenarioCaseRequest,
    SubDecisionsRequest,
    get_assumptions,
    get_decision_scenarios,
    get_sub_decisions,
    get_timeline,
    reset_decision_scenario,
    set_decision_scenario,
    set_sub_decisions,
)
from decision_studio.api.routes.scenarios import list_scenarios
from decision_studio.api.routes.theory_value import (
    PrioritiesRequest,
    compare_options,
    get_conviction,
    set_decision_priorities,
)
from decision_studio.db.models import Claim, EventTimeline, TheoryTripwire
from decision_studio.reasoning import adversary, theory_value
from tests.test_anchor_pipeline_db import session  # noqa: F401 - the fixture is used by name
from tests.test_theory_value_db import _anchored_project_with_theories

VENDOR = "Vendor slippage decides Q3"


async def test_assumptions_come_from_the_graph(session):
    project, _ = await _anchored_project_with_theories(session)
    register = await get_assumptions(project.id, session)
    texts = {c.text for c in (await session.execute(
        select(Claim).where(Claim.project_id == project.id))).scalars()}
    for row in register.assumptions:
        assert row["text"] in texts
        assert row["decision_role"] != "lever" and row["outcomes"]
        assert {"belief", "options", "evidence", "stale", "driver_rank", "can_alter"} <= set(row)


async def test_the_journal_records_what_changed_belief(session):
    project, theories = await _anchored_project_with_theories(session)
    theory = theories[VENDOR]
    await theory_value.state_prior(session, project.id, theory.theory_key, 0.6)
    tripwire = TheoryTripwire(theory_id=theory.id, observable="Vendor misses 15 August",
                              direction="falsifies", horizon_days=30, decisiveness="decisive")
    session.add(tripwire)
    await session.commit()
    await adversary.record_observation(session, project.id, tripwire.id, observed=True)

    await compare_options(project.id, session)
    await compare_options(project.id, session)  # nothing moved: no second entry
    await set_decision_priorities(project.id, PrioritiesRequest(priorities={"Y1": "critical"}), session)

    timeline = await get_timeline(project.id, session)
    kinds = [e["kind"] for e in timeline.events]
    assert kinds[0] == "created"
    assert {"theories", "conviction", "tripwire", "priorities"} <= set(kinds)
    fired = next(e for e in timeline.events if e["kind"] == "tripwire")
    assert fired["title"] == "Tripwire happened: Vendor misses 15 August"
    assert fired["belief_change"] == f"conviction in “{VENDOR}” 60% → 13%"
    assert fired["material"] and "out of date" in fired["detail"]
    journal = (await session.execute(select(EventTimeline).where(
        EventTimeline.project_id == project.id, EventTimeline.event_type == "comparison"))).scalars().all()
    comparisons = [e for e in timeline.events if e["kind"] == "comparison"]
    assert len(journal) == len(comparisons) >= 1
    assert all("first seen" in e["detail"] for e in comparisons)
    assert [e["at"] for e in timeline.events] == sorted(e["at"] for e in timeline.events)


async def test_scenarios_are_stored_as_decision_cases_not_forks(session):
    project, _ = await _anchored_project_with_theories(session)
    scenarios = await get_decision_scenarios(project.id, session)
    assert [c["key"] for c in scenarios.cases] == ["base", "upside", "downside"]
    if scenarios.unavailable:
        pytest.skip(scenarios.unavailable)

    claim = next(c for c in (await session.execute(
        select(Claim).where(Claim.project_id == project.id))).scalars()
        if c.decision_role == "contingency")
    updated = await set_decision_scenario(project.id, "downside", ScenarioCaseRequest(
        assumptions=[{"kind": "claim", "id": str(claim.id), "value": 0.1}]), session)
    downside = updated.cases[2]
    assert downside["source"] == "user"
    assert downside["assumptions"][0]["value"] == pytest.approx(0.1)
    forks = await list_scenarios(project.id, session)
    assert forks.scenarios == []  # a decision case is not a fork

    with pytest.raises(HTTPException) as err:
        await set_decision_scenario(project.id, "upside", ScenarioCaseRequest(
            assumptions=[{"kind": "link", "id": "no-such-edge", "value": 0.5}]), session)
    assert err.value.status_code == 422

    reset = await reset_decision_scenario(project.id, "downside", session)
    assert reset.cases[2]["source"] == "automatic"
    kinds = [e["kind"] for e in (await get_timeline(project.id, session)).events]
    assert kinds.count("scenario") == 2


async def test_sub_decisions_round_trip(session):
    project, _ = await _anchored_project_with_theories(session)
    claims = {c.text: c for c in (await session.execute(
        select(Claim).where(Claim.project_id == project.id))).scalars()}
    vendor = next(c for t, c in claims.items() if t.startswith("The vendor has slipped"))
    team = next(c for t, c in claims.items() if t.startswith("The engineering team lost"))
    saved = await set_sub_decisions(project.id, SubDecisionsRequest(sub_decisions=[{
        "parent": "O1", "label": "Staffing",
        "choices": [{"label": "Keep the vendor", "claim_ids": [str(vendor.id)]},
                    {"label": "Rebuild the team", "claim_ids": [str(team.id)]}],
    }]), session)
    (sd,) = saved.sub_decisions
    assert (sd["key"], sd["parent"]) == ("S1", "O1")
    assert [c["label"] for c in sd["choices"]] == ["Keep the vendor", "Rebuild the team"]
    await session.refresh(project)
    assert project.sub_decisions[0]["choices"][0]["claim_ids"] == [str(vendor.id)]
    assert (await get_sub_decisions(project.id, session)).sub_decisions[0]["key"] == "S1"

    with pytest.raises(HTTPException):
        await set_sub_decisions(project.id, SubDecisionsRequest(sub_decisions=[{
            "parent": "O7", "label": "x",
            "choices": [{"label": "a", "claim_ids": [str(vendor.id)]},
                        {"label": "b", "claim_ids": [str(team.id)]}],
        }]), session)
    assert (await set_sub_decisions(project.id, SubDecisionsRequest(sub_decisions=[]), session)).sub_decisions == []


async def test_observations_carry_quality_labels(session):
    project, theories = await _anchored_project_with_theories(session)
    theory = theories[VENDOR]
    await theory_value.state_prior(session, project.id, theory.theory_key, 0.6)
    tripwire = TheoryTripwire(theory_id=theory.id, observable="Vendor misses 15 August",
                              direction="falsifies", horizon_days=30, decisiveness="decisive")
    session.add(tripwire)
    await session.commit()
    await adversary.record_observation(session, project.id, tripwire.id, observed=True,
                                       event="Vendor missed 15 August")
    conviction = await get_conviction(project.id, theory.theory_key, session)
    keys = {label["key"] for label in conviction.steps[0].quality}
    assert {"kind", "recent", "contradicts", "independent", "decisive"} <= keys


async def test_the_report_carries_the_workspace(session):
    from decision_studio.reasoning.brief import export_brief

    project, theories = await _anchored_project_with_theories(session)
    await theory_value.state_prior(session, project.id, theories[VENDOR].theory_key, 0.6)
    markdown, _, _ = await export_brief(session, project.id, "markdown")
    assert "## Decision journal" in markdown and "Analysis created" in markdown
    if "## Scenarios" in markdown:
        assert "not forecasts" in markdown
    pdf, media, _ = await export_brief(session, project.id, "pdf")
    assert media == "application/pdf" and pdf.startswith(b"%PDF")
