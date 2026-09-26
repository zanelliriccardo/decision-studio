"""Theories of value: conviction, link hypotheses and field results.

Kept apart from ``reasoning.py``, which already holds every other reasoning
endpoint. Everything here is about one question — what should the decider
believe about a theory, given what has been observed — and the three ways the
world can answer it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from decision_studio.db.models import LinkHypothesis, Project
from decision_studio.db.session import get_session
from decision_studio.exceptions import LLMError
from decision_studio.reasoning import experiments as experiment_service
from decision_studio.reasoning import link_tests, option_comparison
from decision_studio.reasoning import theory_value

router = APIRouter(prefix="/api/v1", tags=["theory-value"])


# --- Shapes ---


class ConvictionStepResponse(BaseModel):
    id: str
    likelihood_ratio: float
    source: str
    source_id: str | None = None
    note: str | None = None
    created_at: datetime | None = None
    #: False for evidence recorded before the latest prior: already reflected in it.
    applied: bool
    after: float | None = None
    #: The real-world event the observation came from, when one was named.
    event: str | None = None
    #: Another observation of the same event is the one counted.
    duplicate_of: str | None = None


class ConvictionResponse(BaseModel):
    theory_key: str
    prior: float | None = None
    prior_method: str | None = None
    prior_at: datetime | None = None
    current: float | None = None
    steps: list[ConvictionStepResponse] = []


class PriorRequest(BaseModel):
    value: float = Field(..., gt=0, lt=1)
    method: Literal["lottery", "direct"] = "direct"
    note: str | None = Field(None, max_length=2000)


class HypothesisResponse(BaseModel):
    id: UUID
    theory_key: UUID
    theory_id: UUID | None = None
    edge_id: UUID
    statement: str
    refuted_if: str
    cheapest_test: str = ""
    priority: float
    leverage: float
    uncertainty: float
    status: Literal["open", "held", "refuted", "inconclusive"]
    observed_note: str | None = None
    observed_at: datetime | None = None
    decisiveness: Literal["weak", "moderate", "decisive"] = "moderate"


class HypothesisListResponse(BaseModel):
    hypotheses: list[HypothesisResponse] = []


#: Names the real-world event an observation came from. Observations of one
#: event count once per theory (reasoning/theory_value.replay).
EventField = Field(None, max_length=200)


class HypothesisResultRequest(BaseModel):
    result: Literal["held", "refuted", "inconclusive"]
    likelihood_ratio: float | None = Field(None, gt=0, le=20)
    note: str | None = Field(None, max_length=2000)
    event: str | None = EventField


class FieldResultRequest(BaseModel):
    result: Literal["supports", "refutes", "inconclusive"]
    likelihood_ratio: float | None = Field(None, gt=0, le=20)
    note: str | None = Field(None, max_length=2000)
    event: str | None = EventField


class FieldResultResponse(BaseModel):
    id: UUID
    status: str
    summary: str | None = None
    executed_at: datetime | None = None


def _hypothesis(row: LinkHypothesis) -> HypothesisResponse:
    return HypothesisResponse(
        id=row.id, theory_key=row.theory_key, theory_id=row.theory_id,
        edge_id=row.edge_id, statement=row.statement, refuted_if=row.refuted_if,
        cheapest_test=row.cheapest_test or "", priority=row.priority,
        leverage=row.leverage, uncertainty=row.uncertainty,
        status=row.status,  # type: ignore[arg-type]
        observed_note=row.observed_note, observed_at=row.observed_at,
        decisiveness=row.decisiveness or "moderate",  # type: ignore[arg-type]
    )


async def _require_project(project_id: UUID, session: AsyncSession) -> None:
    if await session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")


# --- Conviction ---


@router.get(
    "/graph/{project_id}/theory-keys/{theory_key}/conviction",
    response_model=ConvictionResponse,
)
async def get_conviction(
    project_id: UUID,
    theory_key: UUID,
    session: AsyncSession = Depends(get_session),
) -> ConvictionResponse:
    """A theory's conviction and the evidence that moved it."""
    await _require_project(project_id, session)
    found = await theory_value.convictions(session, project_id, [theory_key])
    return ConvictionResponse(**found[str(theory_key)].as_dict())


@router.post(
    "/graph/{project_id}/theory-keys/{theory_key}/conviction",
    response_model=ConvictionResponse,
)
async def state_prior(
    project_id: UUID,
    theory_key: UUID,
    req: PriorRequest,
    session: AsyncSession = Depends(get_session),
) -> ConvictionResponse:
    """State (or restate) how convinced you are that a theory holds."""
    await _require_project(project_id, session)
    try:
        conviction = await theory_value.state_prior(
            session, project_id, theory_key, req.value, method=req.method, note=req.note
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ConvictionResponse(**conviction.as_dict())


class EventListResponse(BaseModel):
    events: list[str] = []


@router.get("/graph/{project_id}/observation-events", response_model=EventListResponse)
async def list_observation_events(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> EventListResponse:
    """Events already named on observations, most recent first, for reuse."""
    await _require_project(project_id, session)
    return EventListResponse(events=await theory_value.known_events(session, project_id))


# --- What the causal map predicts for each option ---


class ForecastStats(BaseModel):
    point: float
    p10: float
    p50: float
    p90: float
    #: Share of simulations in which this option was best on this outcome.
    p_best: float


class LeverResponse(BaseModel):
    claim_id: str
    text: str


class OptionForecastResponse(BaseModel):
    key: str
    label: str
    #: modelled, only_as_alternative, no_path or not_modelled
    status: str
    levers_on: list[LeverResponse] = []
    levers_off: list[LeverResponse] = []
    reaches_outcome: bool = False
    #: Per outcome key.
    outcomes: dict[str, ForecastStats] = {}
    score: float | None = None
    p_best: float | None = None
    #: The weighted view under the decider's priorities: 0-1, not a probability.
    weighted: "WeightedViewResponse | None" = None


class WeightedViewResponse(BaseModel):
    score: float
    #: Outcome key -> normalised weight × option-implied probability.
    contributions: dict[str, float] = {}


class PriorityResponse(BaseModel):
    key: str
    label: str
    importance: Literal["critical", "high", "medium", "low", "none"]
    weight: float
    normalized_weight: float
    is_default: bool


class VerdictResponse(BaseModel):
    #: robust, sensitive, unresolved or no_difference (reasoning/decision_robustness.py)
    verdict: str
    higher: str | None = None
    share: float
    difference: float
    value_a: float
    value_b: float
    sentence: str


class OutcomeVerdictResponse(VerdictResponse):
    key: str
    label: str


class PairRobustnessResponse(BaseModel):
    a: str
    b: str
    outcomes: list[OutcomeVerdictResponse] = []
    weighted: VerdictResponse | None = None
    #: consistent, mixed, unresolved or no_difference
    summary: str


class DriverResponse(BaseModel):
    kind: Literal["link", "claim"]
    key: str
    edge_id: str | None = None
    claim_id: str | None = None
    label: str
    current: float
    low: float
    high: float
    uncertainty: float
    #: Gap between the headline pair on the weighted view, at central/low/high.
    base_gap: float
    low_gap: float
    high_gap: float
    impact: float
    #: flips, erases or no_flip
    flip: str
    flips_outcomes: list[str] = []
    explanation: str


class InformationItemResponse(BaseModel):
    kind: Literal["link", "claim"]
    key: str
    edge_id: str | None = None
    claim_id: str | None = None
    subject: str
    action: str
    how: str | None = None
    hypothesis_id: str | None = None
    uncertainty: float
    uncertainty_band: str
    impact: float
    impact_band: str
    can_flip: bool
    score: float
    why: str


class OutcomeRef(BaseModel):
    key: str
    label: str


class OptionComparisonResponse(BaseModel):
    outcomes: list[OutcomeRef] = []
    options: list[OptionForecastResponse] = []
    decisive: bool = False
    leader: str | None = None
    runs: int = 0
    unavailable: str | None = None
    priorities: list[PriorityResponse] = []
    robustness: list[PairRobustnessResponse] = []
    headline_pair: list[str] | None = None
    drivers: list[DriverResponse] = []
    information_priority: list[InformationItemResponse] = []


class SignalResponse(BaseModel):
    kind: Literal["tripwire", "link_test", "field_test"]
    #: The tripwire, link hypothesis or field experiment this comes from.
    id: str
    theory_id: str
    theory_title: str
    text: str
    condition: str
    #: weaken or strengthen, for the option (see reasoning/mind_changers.py)
    effect: Literal["weaken", "strengthen"]
    theory_effect: Literal["weaken", "strengthen"]
    theory_predicts: str
    decisiveness: Literal["weak", "moderate", "decisive"]
    likelihood_ratio: float
    status: str
    resolved: bool
    fired: bool | None = None
    detail: str | None = None
    score: float


class MindTheoryResponse(BaseModel):
    id: str
    title: str
    predicted_effect: str
    #: The decider's conviction; null until stated. Not an outcome probability.
    conviction: float | None = None
    model_support: float | None = None
    reaches_outcome: bool = False
    is_stale: bool = False


class MindOptionResponse(BaseModel):
    key: str
    label: str
    theories: list[MindTheoryResponse] = []
    weaken: list[SignalResponse] = []
    strengthen: list[SignalResponse] = []


class MindChangersResponse(BaseModel):
    options: list[MindOptionResponse] = []


@router.get("/graph/{project_id}/what-would-change-my-mind", response_model=MindChangersResponse)
async def what_would_change_my_mind(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> MindChangersResponse:
    """Per option: the tripwires, link tests and field tests that would weaken or strengthen it."""
    from decision_studio.reasoning.mind_changers import what_would_change_my_mind as consolidate

    await _require_project(project_id, session)
    return MindChangersResponse(options=await consolidate(session, project_id))


class PrioritiesRequest(BaseModel):
    """Outcome key -> importance. Keys left out return to the default (medium)."""

    priorities: dict[str, Literal["critical", "high", "medium", "low", "none"]]


@router.put("/graph/{project_id}/decision-priorities", response_model=OptionComparisonResponse)
async def set_decision_priorities(
    project_id: UUID,
    req: PrioritiesRequest,
    session: AsyncSession = Depends(get_session),
) -> OptionComparisonResponse:
    """Set how much each success criterion matters, and return the comparison under them.

    Changes nothing in the causal graph: only the weighted view and the
    robustness and sensitivity of that view move.
    """
    from decision_studio.reasoning.decision_anchor import normalise_anchor
    from decision_studio.reasoning.decision_priorities import clean_priorities

    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    anchor = normalise_anchor(project.decision_anchor) or {}
    known = [o["key"] for o in anchor.get("outcomes", [])]
    unknown = sorted(set(req.priorities) - set(known))
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown success criteria: {', '.join(unknown)}")
    project.outcome_priorities = clean_priorities(req.priorities, known) or None
    await session.commit()
    comparison = await option_comparison.compare_project_options(session, project_id)
    return OptionComparisonResponse(**comparison.as_dict())


@router.get("/graph/{project_id}/options/compare", response_model=OptionComparisonResponse)
async def compare_options(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> OptionComparisonResponse:
    """Choose each option in turn, propagate, and read the success criteria.

    Pure computation on the reviewed graph: no model call. Repeated with the
    link weights shaken, so each option also gets a win rate.
    """
    await _require_project(project_id, session)
    comparison = await option_comparison.compare_project_options(session, project_id)
    return OptionComparisonResponse(**comparison.as_dict())


# --- Link hypotheses ---


@router.post(
    "/graph/{project_id}/theories/{theory_id}/hypotheses",
    response_model=HypothesisListResponse,
)
async def propose_hypotheses(
    project_id: UUID,
    theory_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> HypothesisListResponse:
    """Turn the theory's most valuable links to test into falsifiable hypotheses."""
    await _require_project(project_id, session)
    try:
        rows = await link_tests.propose_hypotheses(session, project_id, theory_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except link_tests.LinkTestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LLMError as exc:
        await session.rollback()
        raise HTTPException(status_code=502, detail=f"Hypothesis generation failed: {exc}") from exc
    return HypothesisListResponse(hypotheses=[_hypothesis(r) for r in rows])


@router.get("/graph/{project_id}/hypotheses", response_model=HypothesisListResponse)
async def list_hypotheses(
    project_id: UUID,
    theory_key: UUID | None = None,
    session: AsyncSession = Depends(get_session),
) -> HypothesisListResponse:
    """Link hypotheses, open ones first, most valuable first."""
    await _require_project(project_id, session)
    rows = await link_tests.list_hypotheses(session, project_id, theory_key)
    return HypothesisListResponse(hypotheses=[_hypothesis(r) for r in rows])


@router.post(
    "/graph/{project_id}/hypotheses/{hypothesis_id}/result",
    response_model=HypothesisResponse,
)
async def record_hypothesis_result(
    project_id: UUID,
    hypothesis_id: UUID,
    req: HypothesisResultRequest,
    session: AsyncSession = Depends(get_session),
) -> HypothesisResponse:
    """Record what testing a link found. Moves the theory's conviction."""
    await _require_project(project_id, session)
    try:
        row = await link_tests.record_result(
            session, project_id, hypothesis_id, req.result,
            likelihood_ratio=req.likelihood_ratio, note=req.note, event=req.event,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _hypothesis(row)


class DecisivenessRequest(BaseModel):
    decisiveness: Literal["weak", "moderate", "decisive"]


@router.patch(
    "/graph/{project_id}/hypotheses/{hypothesis_id}/decisiveness",
    response_model=HypothesisResponse,
)
async def set_hypothesis_decisiveness(
    project_id: UUID,
    hypothesis_id: UUID,
    req: DecisivenessRequest,
    session: AsyncSession = Depends(get_session),
) -> HypothesisResponse:
    """How much this link test would count. Only while it is still open."""
    await _require_project(project_id, session)
    try:
        row = await link_tests.set_decisiveness(session, project_id, hypothesis_id, req.decisiveness)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _hypothesis(row)


class HypothesisDataRequest(BaseModel):
    #: Two columns, cause then effect, one row per period or case. CSV, TSV or
    #: semicolon-separated; a header row and a leading label column are fine.
    table: str = Field(..., max_length=200_000)
    #: Rows are in time order (enables a lagged, directional test).
    time_ordered: bool = True
    event: str | None = EventField


class HypothesisDataResponse(BaseModel):
    hypothesis: HypothesisResponse
    result: Literal["held", "refuted", "inconclusive"]
    method: str
    n: int
    statistic: float | None = None
    p_value: float | None = None
    summary: str


@router.post(
    "/graph/{project_id}/hypotheses/{hypothesis_id}/data",
    response_model=HypothesisDataResponse,
)
async def record_hypothesis_data(
    project_id: UUID,
    hypothesis_id: UUID,
    req: HypothesisDataRequest,
    session: AsyncSession = Depends(get_session),
) -> HypothesisDataResponse:
    """Test a link against the decider's own numbers. Moves conviction like any result."""
    from decision_studio.reasoning.link_data import TableError

    await _require_project(project_id, session)
    try:
        row, verdict = await link_tests.record_data_result(
            session, project_id, hypothesis_id, req.table,
            time_ordered=req.time_ordered, event=req.event,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TableError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return HypothesisDataResponse(
        hypothesis=_hypothesis(row), result=verdict.result,  # type: ignore[arg-type]
        method=verdict.method, n=verdict.n, statistic=verdict.statistic,
        p_value=verdict.p_value, summary=verdict.summary,
    )


# --- Field experiment results ---


@router.post(
    "/graph/{project_id}/experiments/{experiment_id}/result",
    response_model=FieldResultResponse,
)
async def record_field_result(
    project_id: UUID,
    experiment_id: UUID,
    req: FieldResultRequest,
    session: AsyncSession = Depends(get_session),
) -> FieldResultResponse:
    """Record what a real test found. The only experiment that moves conviction."""
    await _require_project(project_id, session)
    try:
        experiment = await experiment_service.record_field_result(
            session, project_id, experiment_id, req.result,
            likelihood_ratio=req.likelihood_ratio, note=req.note, event=req.event,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FieldResultResponse(
        id=experiment.id, status=experiment.status,
        summary=experiment.summary, executed_at=experiment.executed_at,
    )
