"""The decision workspace: assumptions, timeline, scenarios and sub-decisions.

All four read the reviewed graph and the existing option comparison; see
docs/DECISION_VIEW.md. Nothing here calls a model.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from decision_studio.db.models import Project
from decision_studio.db.session import get_session
from decision_studio.reasoning import (
    assumptions,
    decision_scenarios,
    decision_timeline,
    sub_decisions,
)

router = APIRouter(prefix="/api/v1", tags=["decision-workspace"])


async def _require_project(project_id: UUID, session: AsyncSession) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


# --- Assumption register ---


class AssumptionRegisterResponse(BaseModel):
    assumptions: list[dict[str, Any]] = []
    total: int = 0
    #: "comparison" when influence comes from the option comparison's drivers,
    #: "relevance" when no comparison could be made.
    influence_basis: str = "comparison"


@router.get("/graph/{project_id}/assumptions", response_model=AssumptionRegisterResponse)
async def get_assumptions(
    project_id: UUID, session: AsyncSession = Depends(get_session),
) -> AssumptionRegisterResponse:
    """The claims the decision rests on, uncertain and influential first."""
    await _require_project(project_id, session)
    return AssumptionRegisterResponse(**await assumptions.assumption_register(session, project_id))


# --- Timeline ---


class TimelineResponse(BaseModel):
    events: list[dict[str, Any]] = []
    total: int = 0
    material: int = 0


@router.get("/graph/{project_id}/timeline", response_model=TimelineResponse)
async def get_timeline(
    project_id: UUID, session: AsyncSession = Depends(get_session),
) -> TimelineResponse:
    """What was believed, and what changed it: dated events, oldest first."""
    await _require_project(project_id, session)
    return TimelineResponse(**await decision_timeline.decision_timeline(session, project_id))


# --- Scenarios ---


class ScenariosResponse(BaseModel):
    outcomes: list[dict[str, str]] = []
    cases: list[dict[str, Any]] = []
    unavailable: str | None = None


class ScenarioAssumption(BaseModel):
    kind: Literal["link", "claim"]
    #: Edge id for a link, claim id for a claim.
    id: str
    value: float = Field(..., ge=0, le=1)


class ScenarioCaseRequest(BaseModel):
    assumptions: list[ScenarioAssumption] = Field(..., max_length=20)


@router.get("/graph/{project_id}/decision-scenarios", response_model=ScenariosResponse)
async def get_decision_scenarios(
    project_id: UUID, session: AsyncSession = Depends(get_session),
) -> ScenariosResponse:
    """Base case, upside and downside: the option comparison under explicit assumptions."""
    await _require_project(project_id, session)
    return ScenariosResponse(**await decision_scenarios.project_scenarios(session, project_id))


@router.put("/graph/{project_id}/decision-scenarios/{case}", response_model=ScenariosResponse)
async def set_decision_scenario(
    project_id: UUID,
    case: Literal["upside", "downside"],
    req: ScenarioCaseRequest,
    session: AsyncSession = Depends(get_session),
) -> ScenariosResponse:
    """Replace the automatic assumptions of a case with the decider's own."""
    await _require_project(project_id, session)
    try:
        await decision_scenarios.save_case(
            session, project_id, case, [a.model_dump() for a in req.assumptions])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await decision_timeline.record(
        session, project_id, "scenario", f"{decision_scenarios.CASE_LABELS[case]} assumptions set",
        f"{len(req.assumptions)} input(s) set by the decider")
    return ScenariosResponse(**await decision_scenarios.project_scenarios(session, project_id))


@router.delete("/graph/{project_id}/decision-scenarios/{case}", response_model=ScenariosResponse)
async def reset_decision_scenario(
    project_id: UUID,
    case: Literal["upside", "downside"],
    session: AsyncSession = Depends(get_session),
) -> ScenariosResponse:
    """Back to the automatic assumptions for the case."""
    await _require_project(project_id, session)
    if await decision_scenarios.reset_case(session, project_id, case):
        await decision_timeline.record(
            session, project_id, "scenario",
            f"{decision_scenarios.CASE_LABELS[case]} reset to automatic assumptions")
    return ScenariosResponse(**await decision_scenarios.project_scenarios(session, project_id))


# --- Sub-decisions ---


class SubDecisionChoiceIn(BaseModel):
    label: str = Field(..., min_length=1, max_length=200)
    claim_ids: list[str] = Field(..., min_length=1, max_length=20)


class SubDecisionIn(BaseModel):
    parent: str
    label: str = Field(..., min_length=1, max_length=200)
    choices: list[SubDecisionChoiceIn] = Field(..., min_length=2, max_length=4)


class SubDecisionsRequest(BaseModel):
    sub_decisions: list[SubDecisionIn] = Field(..., max_length=6)


class SubDecisionsResponse(BaseModel):
    sub_decisions: list[dict[str, Any]] = []


@router.get("/graph/{project_id}/sub-decisions", response_model=SubDecisionsResponse)
async def get_sub_decisions(
    project_id: UUID, session: AsyncSession = Depends(get_session),
) -> SubDecisionsResponse:
    """Each sub-decision with its choices evaluated as interventions on the map."""
    await _require_project(project_id, session)
    return SubDecisionsResponse(sub_decisions=await sub_decisions.project_sub_decisions(session, project_id))


@router.put("/graph/{project_id}/sub-decisions", response_model=SubDecisionsResponse)
async def set_sub_decisions(
    project_id: UUID, req: SubDecisionsRequest, session: AsyncSession = Depends(get_session),
) -> SubDecisionsResponse:
    """Replace the project's sub-decisions. Choices must reference existing claims."""
    await _require_project(project_id, session)
    try:
        saved = await sub_decisions.save_sub_decisions(
            session, project_id, [s.model_dump() for s in req.sub_decisions])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await decision_timeline.record(
        session, project_id, "sub_decision", "Sub-decisions updated",
        "; ".join(f"{s['parent']}: {s['label']} ({len(s['choices'])} choices)" for s in saved) or "All removed")
    return SubDecisionsResponse(sub_decisions=await sub_decisions.project_sub_decisions(session, project_id))
