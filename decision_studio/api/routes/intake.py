"""The intake endpoints.

Four of them, and the split between the first two is the design decision most
likely to look like ceremony:

``POST /intake`` creates the project and returns immediately — no model call, no
pipeline. ``POST /intake/{id}/questions`` does the reading, which takes five to
ten seconds.

Fused into one call, the client would have no ``project_id`` during those
seconds — which is exactly when the user may decide not to wait. Without an id,
"start anyway" either blocks until the reading finishes, cancelling itself, or
opens a second project and abandons the first. Separated, the id exists from the
first frame. It costs one round trip.

``POST /intake/{id}/start`` is where the answers become context and the pipeline
begins. ``POST /api/v1/analyze`` is untouched and remains the skip path.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from decision_studio.api.models.analysis import AnalyzeResponse
from decision_studio.api.models.intake import (
    IntakeCreateRequest,
    IntakeQuestionResponse,
    IntakeQuestionsResponse,
    IntakeResponse,
    IntakeStartRequest,
)
from decision_studio.api.sources import (
    attach_documents,
    combine_input,
    require_analysable,
)
from decision_studio.db.models import IntakeQuestion, Project
from decision_studio.db.session import get_session
from decision_studio.reasoning import intake as intake_service
from decision_studio.reasoning.decision_anchor import (
    STATUS_CONFIRMED,
    anchor_keys,
    normalise_anchor,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["intake"])


def _question_response(question: IntakeQuestion) -> IntakeQuestionResponse:
    """Map an intake question to its response shape."""
    return IntakeQuestionResponse(
        id=question.id,
        kind=question.kind,  # type: ignore[arg-type]
        question=question.question,
        quoted_source=question.quoted_source,
        rationale=question.rationale or "",
        options=question.options or [],
        answer_choice=question.answer_choice,
        answer_text=question.answer_text,
    )


async def _require_project(project_id: UUID, session: AsyncSession) -> Project:
    """The project, or a 404."""
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("/intake", response_model=IntakeResponse)
async def create_intake(
    req: IntakeCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> IntakeResponse:
    """Create the project and return at once.

    No model call and no pipeline: this exists so the client holds an id while
    the questions are being generated.
    """
    # Shared with /analyze so the two paths cannot assemble the same request
    # differently: a quotation verified against this text has to be findable in
    # the text the pipeline is then given.
    combined = await combine_input(session, req.text, req.document_ids)
    require_analysable(combined)

    project = Project(
        title=req.title,
        input_text=combined,
        status="pending",
        decision_objective=(req.decision_objective or "").strip() or None,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)

    if req.document_ids:
        await attach_documents(session, project.id, req.document_ids)

    return IntakeResponse(project_id=project.id)


@router.post("/intake/{project_id}/questions", response_model=IntakeQuestionsResponse)
async def generate_questions(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> IntakeQuestionsResponse:
    """Read the material and ask about what it left unclear.

    An empty list is a correct outcome — the material was clear — and the client
    treats it as "nothing to ask" and forwards to the analysis. So does a
    failure: this step improves a run that can proceed without it.
    """
    project = await _require_project(project_id, session)
    questions = await intake_service.generate_questions(
        session, project_id, project.input_text or ""
    )
    return IntakeQuestionsResponse(
        project_id=project_id,
        questions=[_question_response(q) for q in questions],
    )


@router.get("/intake/{project_id}", response_model=IntakeQuestionsResponse)
async def get_intake(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> IntakeQuestionsResponse:
    """Questions and any answers already given.

    Separate from generation so a reload does not re-read the material and
    replace the questions the user was halfway through answering.
    """
    await _require_project(project_id, session)
    questions = await intake_service.list_questions(session, project_id)
    return IntakeQuestionsResponse(
        project_id=project_id,
        questions=[_question_response(q) for q in questions],
    )


@router.post("/intake/{project_id}/start", response_model=AnalyzeResponse)
async def start_analysis(
    project_id: UUID,
    req: IntakeStartRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> AnalyzeResponse:
    """Save the answers, render them, and start the pipeline.

    An empty answer list is valid and means "start without answering" — the
    rendered context is then an empty string, which the pipeline cannot
    distinguish from no context at all.
    """
    project = await _require_project(project_id, session)

    if project.status == "processing":
        raise HTTPException(status_code=409, detail="Analysis already running")

    questions = await intake_service.save_answers(
        session, project_id, [a.model_dump() for a in req.answers]
    )
    context = intake_service.render_answers(questions)

    if req.decision_anchor is not None:
        # Confirmed by being submitted: the user saw it and started from it.
        anchor = normalise_anchor(
            req.decision_anchor,
            status=STATUS_CONFIRMED,
            reserved=anchor_keys(normalise_anchor(project.decision_anchor)),
        )
        if anchor is not None:
            project.decision_anchor = anchor
            project.decision_objective = anchor["decision"]

    # Stored verbatim: six months on, the question is what the model actually
    # read, and re-rendering under changed code would answer a different one.
    project.intake_context = context or None
    project.status = "processing"
    await session.commit()

    # Imported here rather than at module scope: the analysis module owns the
    # in-memory event log, and importing it at load time would make the two
    # modules' import order matter.
    from decision_studio.api.routes.analysis import _PipelineEventLog, _pipeline_logs, _run_pipeline

    project_id_str = str(project_id)
    _pipeline_logs[project_id_str] = _PipelineEventLog()

    answered = sum(1 for q in questions if q.answered_at is not None)
    logger.info(
        "Starting analysis for %s with %d of %d intake question(s) answered",
        project_id, answered, len(questions),
    )

    background_tasks.add_task(
        _run_pipeline, project_id_str, project.input_text, context or None
    )

    return AnalyzeResponse(project_id=project.id, status="processing")
