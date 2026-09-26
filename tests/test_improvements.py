"""Unit tests for the improvements in docs/LOGIC_REVIEW.md, part 2."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from decision_studio.reasoning.outside_view import compare, implied_rate
from decision_studio.reasoning.theory_value import bayes_update, replay

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _row(kind, minutes, *, value=None, lr=None, event=None, source="tripwire"):
    return SimpleNamespace(
        id=uuid4(), kind=kind, value=value, likelihood_ratio=lr, source=source,
        source_id=None, method="direct", note=None, event=event,
        created_at=T0 + timedelta(minutes=minutes),
    )


class TestOneEventCountsOnce:
    def test_two_observations_of_one_event_apply_the_strongest(self):
        rows = [
            _row("prior", 0, value=0.6),
            _row("evidence", 1, lr=0.25, event="Vendor missed 1 August"),
            _row("evidence", 2, lr=0.25, event="  vendor MISSED 1 august ", source="link_hypothesis"),
        ]
        conviction = replay("k", rows)
        assert conviction.current == pytest.approx(bayes_update(0.6, [0.25]))
        counted, duplicate = conviction.steps
        assert counted.applied and counted.duplicate_of is None
        assert not duplicate.applied and duplicate.duplicate_of == counted.id

    def test_the_strongest_counts_even_when_it_came_second(self):
        rows = [
            _row("prior", 0, value=0.6),
            _row("evidence", 1, lr=0.5, event="e"),
            _row("evidence", 2, lr=0.1, event="e"),
        ]
        conviction = replay("k", rows)
        assert conviction.current == pytest.approx(bayes_update(0.6, [0.1]))
        assert [s.applied for s in conviction.steps] == [False, True]

    def test_unnamed_or_different_events_stay_independent(self):
        rows = [
            _row("prior", 0, value=0.6),
            _row("evidence", 1, lr=0.25, event="a"),
            _row("evidence", 2, lr=0.25, event="b"),
            _row("evidence", 3, lr=2.0),
        ]
        assert replay("k", rows).current == pytest.approx(bayes_update(0.6, [0.25, 0.25, 2.0]))

    def test_an_event_known_when_the_prior_was_restated_is_already_in_it(self):
        rows = [
            _row("evidence", 0, lr=0.25, event="e"),
            _row("prior", 1, value=0.3),
            _row("evidence", 2, lr=0.25, event="e"),
        ]
        conviction = replay("k", rows)
        assert conviction.current == pytest.approx(0.3)
        assert not any(s.applied for s in conviction.steps)


def _case(with_outcome=3, total=5):
    return SimpleNamespace(outcome="the date slipped", cases_with_outcome=with_outcome,
                           cases_total=total, base_rate=with_outcome / total)


class TestOutsideView:
    def test_polarity_turns_the_theory_round(self):
        # "We will ship on time" at 85% implies a slip at 15%.
        assert implied_rate(0.85, "opposite") == pytest.approx(0.15)
        assert implied_rate(0.85, "same") == pytest.approx(0.85)

    def test_an_optimistic_conviction_is_flagged(self):
        delta, note = compare(_case(), "opposite", conviction=0.85, model_confidence=0.4)
        assert delta == pytest.approx(0.15 - 0.6)
        assert note.startswith("Differs from your experience") and "your conviction" in note

    def test_agreeing_with_experience_is_not_flagged(self):
        # Before the fix, 0.4 was compared with 0.6 directly and flagged.
        delta, note = compare(_case(), "opposite", conviction=0.4, model_confidence=0.9)
        assert delta == pytest.approx(0.0)
        assert note.startswith("Consistent")

    def test_model_confidence_stands_in_until_a_conviction_is_stated(self):
        _, note = compare(_case(), "same", conviction=None, model_confidence=0.6)
        assert "the model's confidence" in note and note.startswith("Consistent")
