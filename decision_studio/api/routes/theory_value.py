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
from decision_studio.reasoning import link_tests
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
