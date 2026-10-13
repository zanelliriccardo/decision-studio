"""End to end for the improvements in docs/LOGIC_REVIEW.md, part 2. Skips without a database."""

from __future__ import annotations

import re

import pytest

from decision_studio.api.routes.reasoning import list_theories
from decision_studio.db.models import TheoryTripwire
from decision_studio.llm.prompts.link_hypotheses import LINK_HYPOTHESIS_SYSTEM
from decision_studio.llm.prompts.outside_view import (
    OUTSIDE_VIEW_MATCH_SYSTEM,
    REFERENCE_CLASS_SYSTEM,
)
from decision_studio.llm.prompts.theory_generation import THEORY_GENERATION_SYSTEM
from decision_studio.reasoning import adversary, link_tests, outside_view, theory_value
from decision_studio.reasoning.theories import generate_theories
from decision_studio.reasoning.theory_value import bayes_update
from tests.conftest import FakeLLM
from tests.test_anchor_pipeline_db import session  # noqa: F401 - the fixture is used by name
from tests.test_theory_value_db import _anchored_project_with_theories, _theories

VENDOR = "Vendor slippage decides Q3"


def _outside_llm(polarity: str) -> FakeLLM:
    def match(user, schema):
        index = re.search(rf"\[T(\d+)\] {VENDOR}", user).group(1)
        return {"matches": [{"theory_ref": f"T{index}", "reference_ref": "R0",
                             "polarity": polarity, "reason": "both about the date"}]}

    return FakeLLM([
        (REFERENCE_CLASS_SYSTEM, lambda u, s: {"cases": [{
            "outcome": "the date slipped", "cases_total": 5, "cases_with_outcome": 3,
            "basis": "3 of the last 5 slipped"}]}),
        (OUTSIDE_VIEW_MATCH_SYSTEM, match),
    ])


async def _vendor(project, session):
    listing = await list_theories(project.id, session)
    return next(t for t in listing.theories if t.title == VENDOR)


async def test_comparable_cases_are_checked_against_conviction(session):
    project, theories = await _anchored_project_with_theories(session)
    key = theories[VENDOR].theory_key
    await theory_value.state_prior(session, project.id, key, 0.85)

    llm = _outside_llm("opposite")
    cases = await outside_view.extract_reference_cases(
        session, project.id, "Of the last 5 dates we committed to, 3 slipped.", llm=llm)
    assert [c.base_rate for c in cases] == [pytest.approx(0.6)]
    report = await outside_view.check_theories_against_base_rates(session, project.id, llm=llm)
    assert report == {"cases": 1, "checked": 1, "diverging": 1}
    await session.refresh(project)
    assert project.outside_view_recollection.startswith("Of the last 5")

    # 85% that the date holds implies a 15% slip, against 60% remembered.
    vendor = await _vendor(project, session)
    assert vendor.outside_view_delta == pytest.approx(0.15 - 0.6)
    assert vendor.outside_view_note.startswith("Differs from your experience")

    # Restating conviction moves the comparison with no model call.
    calls = len(llm.calls)
    await theory_value.state_prior(session, project.id, key, 0.4)
    vendor = await _vendor(project, session)
    assert vendor.outside_view_note.startswith("Consistent")
    assert len(llm.calls) == calls

    # Regenerating keeps the match: same option, same effect.
    await generate_theories(session, project.id, llm=FakeLLM([(THEORY_GENERATION_SYSTEM, _theories)]))
    vendor = await _vendor(project, session)
    assert vendor.version == 2 and vendor.outside_view_note.startswith("Consistent")

    # Clearing the recollection clears its base rates.
    assert await outside_view.extract_reference_cases(session, project.id, "", llm=llm) == []
    assert await outside_view.list_reference_cases(session, project.id) == []


async def test_one_event_moves_conviction_once(session):
    project, theories = await _anchored_project_with_theories(session)
    theory = theories[VENDOR]
    key = theory.theory_key
    await theory_value.state_prior(session, project.id, key, 0.6)

    tripwire = TheoryTripwire(theory_id=theory.id, observable="Vendor misses 1 August",
                              direction="falsifies", horizon_days=30)
    session.add(tripwire)
    await session.commit()
    await adversary.record_observation(session, project.id, tripwire.id, observed=True,
                                       event="Vendor missed 1 August")

    llm = FakeLLM([(LINK_HYPOTHESIS_SYSTEM, lambda u, s: {"hypotheses": [
        {"index": 0, "statement": "Vendor delivery drives integration",
         "refuted_if": "Integration on time despite a late vendor", "cheapest_test": "Ask"},
    ]})])
    hypothesis = (await link_tests.propose_hypotheses(session, project.id, theory.id, llm=llm))[0]
    await link_tests.record_result(session, project.id, hypothesis.id, "refuted",
                                   event="vendor missed 1 august")

    conviction = (await theory_value.convictions(session, project.id, [key]))[str(key)]
    assert conviction.current == pytest.approx(bayes_update(0.6, [0.25]))
    assert sum(s.applied for s in conviction.steps) == 1
    assert await theory_value.known_events(session, project.id) == [
        "vendor missed 1 august", "Vendor missed 1 August"]


async def test_options_are_compared_on_the_reviewed_graph(session):
    from decision_studio.api.routes.theory_value import compare_options
    from decision_studio.reasoning.option_comparison import compare_project_options

    project, _ = await _anchored_project_with_theories(session)
    comparison = await compare_project_options(session, project.id, runs=20)
    assert [o.key for o in comparison.options][:2] == ["O1", "O2"]
    q3 = comparison.options[0]
    assert [t for _, t in q3.levers_on] == ["Customers were promised a Q3 launch"]
    assert comparison.options[1].levers_off == q3.levers_on
    assert comparison.outcomes and comparison.outcomes[0][0] == "Y1"
    if comparison.unavailable is None:
        assert sum(o.p_best for o in comparison.options) == pytest.approx(1.0)

    response = await compare_options(project.id, session)
    assert response.options[0].key == "O1"


async def test_decisiveness_is_stated_in_advance_and_sets_the_weight(session):
    project, theories = await _anchored_project_with_theories(session)
    theory = theories[VENDOR]
    key = theory.theory_key
    await theory_value.state_prior(session, project.id, key, 0.6)
    decisive = TheoryTripwire(theory_id=theory.id, observable="Vendor misses 1 August",
                              direction="falsifies", horizon_days=30)
    session.add(decisive)
    await session.commit()

    await adversary.set_tripwire_decisiveness(session, project.id, decisive.id, "decisive")
    await adversary.record_observation(session, project.id, decisive.id, observed=True)
    conviction = (await theory_value.convictions(session, project.id, [key]))[str(key)]
    assert conviction.current == pytest.approx(bayes_update(0.6, [0.1]))

    # Locked once observed: the weight cannot be chosen to fit the result.
    with pytest.raises(ValueError):
        await adversary.set_tripwire_decisiveness(session, project.id, decisive.id, "weak")


def test_moderate_is_the_old_default():
    from decision_studio.reasoning.link_tests import DEFAULT_RESULT_LR, result_likelihood
    from decision_studio.reasoning.theory_value import tripwire_likelihood

    assert tripwire_likelihood("falsifies", True) == pytest.approx(0.25)
    assert tripwire_likelihood("confirms", False) == pytest.approx(1 / 1.5)
    assert tripwire_likelihood("falsifies", True, "weak") == pytest.approx(0.5)
    assert result_likelihood("refuted", None) == DEFAULT_RESULT_LR["refuted"]
    assert result_likelihood("held", "decisive") > result_likelihood("held", "weak")


async def test_a_link_is_tested_against_pasted_data(session):
    from decision_studio.api.routes.theory_value import HypothesisDataRequest, record_hypothesis_data

    project, theories = await _anchored_project_with_theories(session)
    theory = theories[VENDOR]
    await theory_value.state_prior(session, project.id, theory.theory_key, 0.5)
    llm = FakeLLM([(LINK_HYPOTHESIS_SYSTEM, lambda u, s: {"hypotheses": [
        {"index": 0, "statement": "Vendor slips push the date", "refuted_if": "no relation",
         "cheapest_test": "Compare last year's slips with our dates"},
    ]})])
    hypothesis = (await link_tests.propose_hypotheses(session, project.id, theory.id, llm=llm))[0]

    table = "quarter,vendor_slip_weeks,our_slip_weeks\n" + "\n".join(
        f"Q{i},{w},{w + (i % 2)}" for i, w in enumerate([0, 1, 3, 2, 5, 4, 6, 8, 7, 9], start=1)
    )
    response = await record_hypothesis_data(
        project.id, hypothesis.id, HypothesisDataRequest(table=table, time_ordered=False), session)
    assert response.result == "held" and response.method == "spearman" and response.n == 10
    assert response.hypothesis.status == "held"
    assert response.hypothesis.observed_note.startswith("From your data:")
    conviction = (await theory_value.convictions(session, project.id, [theory.theory_key]))[
        str(theory.theory_key)]
    assert conviction.current == pytest.approx(bayes_update(0.5, [2.0]))
