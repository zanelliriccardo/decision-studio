"""Decision priorities, robustness and "what would change my mind" through the API. Skips without a database."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from decision_studio.api.routes.theory_value import (
    PrioritiesRequest,
    compare_options,
    set_decision_priorities,
    what_would_change_my_mind,
)
from decision_studio.db.models import TheoryTripwire
from decision_studio.llm.prompts.link_hypotheses import LINK_HYPOTHESIS_SYSTEM
from decision_studio.reasoning import link_tests, theory_value
from tests.conftest import FakeLLM
from tests.test_anchor_pipeline_db import session  # noqa: F401 - the fixture is used by name
from tests.test_theory_value_db import _anchored_project_with_theories

VENDOR = "Vendor slippage decides Q3"


async def test_priorities_are_stored_apart_from_the_graph(session):
    project, _ = await _anchored_project_with_theories(session)
    before = await compare_options(project.id, session)
    assert all(p.is_default and p.importance == "medium" for p in before.priorities)
    anchor_before = dict(project.decision_anchor)

    after = await set_decision_priorities(
        project.id, PrioritiesRequest(priorities={"Y1": "critical"}), session)
    await session.refresh(project)
    assert project.outcome_priorities == {"Y1": "critical"}
    assert project.decision_anchor == anchor_before  # the graph's anchor is untouched
    y1 = next(p for p in after.priorities if p.key == "Y1")
    assert y1.importance == "critical" and not y1.is_default
    # Model-implied outcomes do not move with priorities.
    assert [o.outcomes for o in after.options] == [o.outcomes for o in before.options]
    for option in after.options:
        if option.weighted is not None:
            assert 0.0 <= option.weighted.score <= 1.0

    with pytest.raises(HTTPException) as err:
        await set_decision_priorities(project.id, PrioritiesRequest(priorities={"Y9": "low"}), session)
    assert err.value.status_code == 422


async def test_the_comparison_carries_robustness_drivers_and_information(session):
    project, theories = await _anchored_project_with_theories(session)
    llm = FakeLLM([(LINK_HYPOTHESIS_SYSTEM, lambda u, s: {"hypotheses": [
        {"index": 0, "statement": "Vendor slips push the date", "refuted_if": "no relation",
         "cheapest_test": "Ask the vendor"},
    ]})])
    await link_tests.propose_hypotheses(session, project.id, theories[VENDOR].id, llm=llm)

    response = await compare_options(project.id, session)
    if response.unavailable:
        pytest.skip(f"comparison unavailable on the fixture graph: {response.unavailable}")
    (pair,) = response.robustness
    assert {pair.a, pair.b} == {"O1", "O2"}
    assert {o.key for o in pair.outcomes} == {o.key for o in response.outcomes}
    for row in pair.outcomes:
        assert row.verdict in ("robust", "sensitive", "unresolved", "no_difference")
    assert response.headline_pair and set(response.headline_pair) == {"O1", "O2"}
    for driver in response.drivers:
        assert driver.low <= driver.current <= driver.high
    for item in response.information_priority:
        assert item.why and item.action


async def test_what_would_change_my_mind_uses_existing_signals(session):
    project, theories = await _anchored_project_with_theories(session)
    theory = theories[VENDOR]  # "Q3 achieves the date"
    await theory_value.state_prior(session, project.id, theory.theory_key, 0.68)
    tripwire = TheoryTripwire(theory_id=theory.id, observable="Vendor misses 15 August",
                              direction="falsifies", horizon_days=30, decisiveness="decisive")
    session.add(tripwire)
    await session.commit()

    response = await what_would_change_my_mind(project.id, session)
    q3 = next(o for o in response.options if o.key == "O1")
    assert q3.theories[0].title == VENDOR and q3.theories[0].conviction == pytest.approx(0.68)
    (signal,) = [s for s in q3.weaken if s.kind == "tripwire"]
    assert signal.id == str(tripwire.id) and signal.decisiveness == "decisive"
    assert signal.status == "not_observed" and not signal.resolved
    assert q3.strengthen == [] or all(s.kind != "tripwire" for s in q3.strengthen)
