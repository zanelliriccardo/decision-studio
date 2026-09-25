"""Decision-reasoning API routes.

Graph review, theory generation and clarification questions. Path convention
follows the existing operations router (``/api/v1/graph/{project_id}/...``) so
these sit alongside expand/trace-back/challenge rather than in a parallel API.

Every handler verifies that the entity it touches belongs to the project in the
route; the service layer re-checks, because a 404 is cheaper than a leak.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_studio.api.models.reasoning import (
    AdversaryReport,
    CausalChainStep,
    ChangeSummary,
    DecisionObjectiveRequest,
    GenerateTheoriesRequest,
    GraphOperationListResponse,
    GraphOperationResponse,
    GraphRevisionResponse,
    ObjectionResponse,
    RecommendationResponse,
    ObservationRequest,
    AddClaimRequest,
    AddEdgeRequest,
    AuthoringResult,
    DebateListResponse,
    DebateReport,
    DebateResponse,
    ExperimentListResponse,
    ExperimentResponse_,
    InferLinksResponse,
    OutsideViewResponse,
    PersonaResponse,
    RecomputePlanResponse,
    RecomputeResponse,
    ReactionResponse,
    ReferenceCaseResponse,
    ReviewRequest,
    ReviewResult,
    ReviewStateResponse,
    TheoryGenerationResponse,
    TheoryListResponse,
    TheoryResponse,
    TheoryRevisionListResponse,
    TheoryRevisionResponse,
    TheoryVersionsResponse,
    TripwireReport,
    TripwireResponse,
)
from decision_studio.db.models import (
    CausalEdge,
    TheoryDebate,
    Claim,
    GraphOperation,
    Project,
    Theory,
    TheoryObjection,
    TheoryTripwire,
)
from decision_studio.db.session import get_session
from decision_studio.exceptions import LLMError
from decision_studio.reasoning import adversary as adversary_service
from decision_studio.reasoning import authoring as authoring_service
from decision_studio.reasoning import brief as brief_service
from decision_studio.reasoning import debate_service
from decision_studio.reasoning import recommendation as recommendation_service
from decision_studio.reasoning import experiments as experiment_service
from decision_studio.reasoning import outside_view as outside_view_service
from decision_studio.reasoning import review as review_service
from decision_studio.reasoning import theories as theory_service
from decision_studio.reasoning.calibration import band
from decision_studio.reasoning.effective_graph import is_claim_effective, is_edge_effective
from decision_studio.reasoning.review import ReviewChange, ReviewError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["reasoning"])


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


async def _require_project(project_id: UUID, session: AsyncSession) -> Project:
    """The project, or a 404."""
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _operation_response(operation: GraphOperation) -> GraphOperationResponse:
    """Map a graph operation to its response shape."""
    return GraphOperationResponse(
        id=operation.id,
        operation_type=operation.operation_type,
        target_type=operation.target_type,
        claim_id=operation.claim_id,
        edge_id=operation.edge_id,
        before_state=operation.before_state,
        after_state=operation.after_state,
        revision_before=operation.revision_before,
        revision_after=operation.revision_after,
        source=operation.source,
        note=operation.note,
        undone_at=operation.undone_at,
        created_at=operation.created_at,
    )


def _review_state(element, target_type: str) -> ReviewStateResponse:
    """Map a reviewed claim or edge to its review-state shape."""
    return ReviewStateResponse(
        id=element.id,
        target_type=target_type,  # type: ignore[arg-type]
        review_status=element.review_status,
        is_active=element.is_active,
        user_note=element.user_note,
        strength_override=getattr(element, "strength_override", None),
        reviewed_at=element.reviewed_at,
    )


def _theory_response(
    theory: Theory,
    objections: list[ObjectionResponse] | None = None,
    tripwires: list[TripwireResponse] | None = None,
) -> TheoryResponse:
    """Map a theory to its response shape, with objections and tripwires."""
    supporting_ev = [
        link.evidence_id for link in theory.evidence_links if link.role == "supporting"
    ]
    contradicting_ev = [
        link.evidence_id
        for link in theory.evidence_links
        if link.role == "contradicting"
    ]
    # Two claims in a row means the link between them was dropped for not
    # joining them. Marked so the UI draws the break: rendering a broken chain
    # as a continuous one is the bug this whole check exists to stop.
    chain: list[CausalChainStep] = []
    previous_was_claim = False
    for step in (theory.causal_chain or []):
        if not isinstance(step, dict):
            continue
        is_claim = bool(step.get("claim_id"))
        chain.append(CausalChainStep(
            **step, gap_before=is_claim and previous_was_claim
        ))
        previous_was_claim = is_claim
    return TheoryResponse(
        id=theory.id,
        project_id=theory.project_id,
        theory_key=theory.theory_key,
        title=theory.title,
        summary=theory.summary,
        status=theory.status,  # type: ignore[arg-type]
        causal_chain=chain,
        connected_links=getattr(theory, "connected_links", 0),
        cited_links=getattr(theory, "cited_links", 0),
        supporting_claim_ids=[
            link.claim_id
            for link in sorted(theory.claim_links, key=lambda link: link.position)
        ],
        supporting_edge_ids=[
            link.edge_id
            for link in sorted(theory.edge_links, key=lambda link: link.position)
        ],
        supporting_evidence_ids=supporting_ev,
        contradicting_evidence_ids=contradicting_ev,
        weak_assumptions=list(theory.weak_assumptions or []),
        confidence=theory.confidence,
        business_impact=theory.business_impact,  # type: ignore[arg-type]
        recommendation=theory.recommendation or "",
        graph_revision=theory.graph_revision,
        theory_revision=theory.theory_revision,
        version=theory.version,
        is_current=theory.is_current,
        objection_load=theory.objection_load or 0.0,
        contested=theory.contested or False,
        adjusted_score=theory.adjusted_score,
        objections=objections or [],
        tripwires=tripwires or [],
        outside_view_delta=theory.outside_view_delta,
        outside_view_note=theory.outside_view_note,
        confidence_band=band(theory.confidence),
        is_stale=theory.is_stale,
        stale_reason=theory.stale_reason,
        change_kind=theory.change_kind,
        change_explanation=theory.change_explanation,
        created_at=theory.created_at,
    )


async def _objections_by_theory(
    session: AsyncSession, project_id: UUID
) -> dict[UUID, list[ObjectionResponse]]:
    """All objections for a project in one query (no N+1)."""
    result = await session.execute(
        select(TheoryObjection)
        .join(Theory, Theory.id == TheoryObjection.theory_id)
        .where(Theory.project_id == project_id)
        .order_by(TheoryObjection.severity.desc())
    )
    mapping: dict[UUID, list[ObjectionResponse]] = {}
    for row in result.scalars().all():
        mapping.setdefault(row.theory_id, []).append(
            ObjectionResponse(
                id=row.id,
                objection=row.objection,
                kind=row.kind,
                severity=row.severity,
                dismissed=row.dismissed,
            )
        )
    return mapping


async def _tripwires_by_theory(
    session: AsyncSession, project_id: UUID
) -> dict[UUID, list[TripwireResponse]]:
    """All tripwires for a project in one query."""
    result = await session.execute(
        select(TheoryTripwire)
        .join(Theory, Theory.id == TheoryTripwire.theory_id)
        .where(Theory.project_id == project_id)
        .order_by(TheoryTripwire.check_by)
    )
    mapping: dict[UUID, list[TripwireResponse]] = {}
    for row in result.scalars().all():
        mapping.setdefault(row.theory_id, []).append(
            TripwireResponse(
                id=row.id,
                observable=row.observable,
                direction=row.direction,
                horizon_days=row.horizon_days,
                check_by=row.check_by,
                status=row.status,
                observed_at=row.observed_at,
                observed_note=row.observed_note,
            )
        )
    return mapping


# ---------------------------------------------------------------------------
# Graph review
# ---------------------------------------------------------------------------


async def _apply_review(
    project_id: UUID,
    target_type: str,
    target_id: UUID,
    req: ReviewRequest,
    session: AsyncSession,
) -> ReviewResult:
    """Apply one review decision, shared by the claim and edge endpoints.

    Both take the same optimistic-concurrency path: a stale
    `expected_graph_revision` is a 409 rather than a silent overwrite.
    """
    project = await _require_project(project_id, session)

    if (
        req.expected_graph_revision is not None
        and req.expected_graph_revision != (project.graph_revision or 1)
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Graph has moved on (revision {project.graph_revision}, "
                f"expected {req.expected_graph_revision}). Reload before editing."
            ),
        )

    change = ReviewChange(
        review_status=req.review_status,
        is_active=req.is_active,
        user_note=req.user_note,
        strength_override=req.strength_override,
        clear_strength_override=req.clear_strength_override,
        mechanism=req.mechanism,
    )

    try:
        # One transaction: element update, audit row, revision bump and
        # staleness marking either all land or none do.
        element, operation = await review_service.apply_review(
            session,
            project_id,
            target_type=target_type,
            target_id=target_id,
            change=change,
            note=req.note,
        )
    except ReviewError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    stale_count = await session.scalar(
        select(func.count())
        .select_from(Theory)
        .where(
            Theory.project_id == project_id,
            Theory.is_current.is_(True),
            Theory.is_stale.is_(True),
        )
    )

    return ReviewResult(
        element=_review_state(element, target_type),
        operation=_operation_response(operation),
        graph_revision=operation.revision_after,
        stale_theory_count=int(stale_count or 0),
    )


@router.patch("/graph/{project_id}/claims/{claim_id}/review", response_model=ReviewResult)
async def review_claim(
    project_id: UUID,
    claim_id: UUID,
    req: ReviewRequest,
    session: AsyncSession = Depends(get_session),
) -> ReviewResult:
    """Review a claim: accept, reject, flag, disable, restore or annotate."""
    return await _apply_review(project_id, "claim", claim_id, req, session)


@router.patch("/graph/{project_id}/edges/{edge_id}/review", response_model=ReviewResult)
async def review_edge(
    project_id: UUID,
    edge_id: UUID,
    req: ReviewRequest,
    session: AsyncSession = Depends(get_session),
) -> ReviewResult:
    """Review an edge, including human strength override and mechanism edits."""
    return await _apply_review(project_id, "edge", edge_id, req, session)


@router.get(
    "/graph/{project_id}/graph-operations", response_model=GraphOperationListResponse
)
async def list_graph_operations(
    project_id: UUID,
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
) -> GraphOperationListResponse:
    """Review history for the project, newest first."""
    project = await _require_project(project_id, session)
    operations = await review_service.list_operations(
        session, project_id, limit=min(max(limit, 1), 500)
    )
    return GraphOperationListResponse(
        operations=[_operation_response(op) for op in operations],
        graph_revision=project.graph_revision or 1,
    )


@router.post(
    "/graph/{project_id}/graph-operations/{operation_id}/undo",
    response_model=ReviewResult,
)
async def undo_graph_operation(
    project_id: UUID,
    operation_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ReviewResult:
    """Undo a review operation by replaying its recorded before-state."""
    await _require_project(project_id, session)
    try:
        element, operation = await review_service.undo_operation(
            session, project_id, operation_id
        )
    except ReviewError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    stale_count = await session.scalar(
        select(func.count())
        .select_from(Theory)
        .where(
            Theory.project_id == project_id,
            Theory.is_current.is_(True),
            Theory.is_stale.is_(True),
        )
    )
    return ReviewResult(
        element=_review_state(element, operation.target_type),
        operation=_operation_response(operation),
        graph_revision=operation.revision_after,
        stale_theory_count=int(stale_count or 0),
    )


@router.get("/graph/{project_id}/graph-revision", response_model=GraphRevisionResponse)
async def get_graph_revision(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> GraphRevisionResponse:
    """Current graph revision and effective-graph size."""
    project = await _require_project(project_id, session)

    claims = list(
        (
            await session.execute(select(Claim).where(Claim.project_id == project_id))
        ).scalars().all()
    )
    edges = list(
        (
            await session.execute(
                select(CausalEdge).where(CausalEdge.project_id == project_id)
            )
        ).scalars().all()
    )
    active_claims = [c for c in claims if is_claim_effective(c)]
    active_ids = {str(c.id) for c in active_claims}
    active_edges = [e for e in edges if is_edge_effective(e, active_ids)]

    return GraphRevisionResponse(
        project_id=project_id,
        graph_revision=project.graph_revision or 1,
        active_claim_count=len(active_claims),
        active_edge_count=len(active_edges),
        total_claim_count=len(claims),
        total_edge_count=len(edges),
        decision_objective=getattr(project, "decision_objective", None),
    )


@router.patch(
    "/graph/{project_id}/decision-objective", response_model=GraphRevisionResponse
)
async def set_decision_objective(
    project_id: UUID,
    req: DecisionObjectiveRequest,
    session: AsyncSession = Depends(get_session),
) -> GraphRevisionResponse:
    """Set what decision the user is trying to make.

    Steers theory and question generation; does not change the graph, so it does
    not bump the graph revision.
    """
    project = await _require_project(project_id, session)
    project.decision_objective = req.decision_objective.strip() or None
    await session.commit()
    return await get_graph_revision(project_id, session)


# ---------------------------------------------------------------------------
# Theories
# ---------------------------------------------------------------------------


async def _generate(
    project_id: UUID,
    trigger: str,
    session: AsyncSession,
    max_claims: int | None = None,
) -> TheoryGenerationResponse:
    """Generate or regenerate theories, shared by both entry points."""
    await _require_project(project_id, session)
    try:
        result = await theory_service.generate_theories(
            session, project_id, trigger=trigger, max_claims=max_claims
        )
    except theory_service.TheoryGenerationError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMError as exc:
        await session.rollback()
        logger.exception("Theory generation failed for project %s", project_id)
        raise HTTPException(
            status_code=502, detail=f"Theory generation failed: {exc}"
        ) from exc
    objection_map = await _objections_by_theory(session, project_id)
    tripwire_map = await _tripwires_by_theory(session, project_id)
    return TheoryGenerationResponse(
        graph_revision=result.revision.graph_revision,
        theory_revision=result.revision.revision,
        theories=[
            _theory_response(
                t,
                objection_map.get(t.id, []),
                tripwire_map.get(t.id, []),
            )
            for t in result.theories
        ],
        change_summary=ChangeSummary(**result.change_summary),
        validation=result.validation,
    )


@router.post(
    "/graph/{project_id}/theories/generate", response_model=TheoryGenerationResponse
)
async def generate_theories(
    project_id: UUID,
    req: GenerateTheoriesRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> TheoryGenerationResponse:
    """Generate decision-oriented theories from the effective reviewed graph."""
    return await _generate(
        project_id, "generate", session, req.max_claims if req else None
    )


@router.post(
    "/graph/{project_id}/theories/regenerate", response_model=TheoryGenerationResponse
)
async def regenerate_theories(
    project_id: UUID,
    req: GenerateTheoriesRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> TheoryGenerationResponse:
    """Regenerate theories, preserving prior versions and explaining changes."""
    return await _generate(
        project_id, "regenerate", session, req.max_claims if req else None
    )


@router.get("/graph/{project_id}/theories", response_model=TheoryListResponse)
async def list_theories(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> TheoryListResponse:
    """Current theories, ordered by business impact then confidence."""
    project = await _require_project(project_id, session)
    theories = await theory_service.list_current_theories(session, project_id)
    objection_map = await _objections_by_theory(session, project_id)
    tripwire_map = await _tripwires_by_theory(session, project_id)
    return TheoryListResponse(
        theories=[
            _theory_response(
                t,
                objection_map.get(t.id, []),
                tripwire_map.get(t.id, []),
            )
            for t in theories
        ],
        graph_revision=project.graph_revision or 1,
        theory_revision=theories[0].theory_revision if theories else None,
        stale_count=sum(1 for t in theories if t.is_stale),
    )


@router.get(
    "/graph/{project_id}/theory-revisions", response_model=TheoryRevisionListResponse
)
async def list_theory_revisions(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> TheoryRevisionListResponse:
    """Generation history with per-run change summaries."""
    await _require_project(project_id, session)
    revisions = await theory_service.list_revisions(session, project_id)
    return TheoryRevisionListResponse(
        revisions=[
            TheoryRevisionResponse(
                id=r.id,
                revision=r.revision,
                graph_revision=r.graph_revision,
                trigger=r.trigger,
                change_summary=(
                    ChangeSummary(**r.change_summary) if r.change_summary else None
                ),
                generation_metadata=r.generation_metadata,
                created_at=r.created_at,
            )
            for r in revisions
        ]
    )


@router.get(
    "/graph/{project_id}/theories/{theory_id}/versions",
    response_model=TheoryVersionsResponse,
)
async def list_versions(
    project_id: UUID,
    theory_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> TheoryVersionsResponse:
    """Every stored version of the theory, oldest first."""
    await _require_project(project_id, session)
    theory = await theory_service.get_theory(session, project_id, theory_id)
    if theory is None:
        raise HTTPException(status_code=404, detail="Theory not found")
    versions = await theory_service.list_theory_versions(
        session, project_id, theory.theory_key
    )
    return TheoryVersionsResponse(
        theory_key=theory.theory_key,
        versions=[_theory_response(v) for v in versions],
    )


@router.get("/graph/{project_id}/theories/{theory_id}", response_model=TheoryResponse)
async def get_theory(
    project_id: UUID,
    theory_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> TheoryResponse:
    """One theory with its full provenance."""
    await _require_project(project_id, session)
    theory = await theory_service.get_theory(session, project_id, theory_id)
    if theory is None:
        raise HTTPException(status_code=404, detail="Theory not found")
    objection_map = await _objections_by_theory(session, project_id)
    tripwire_map = await _tripwires_by_theory(session, project_id)
    return _theory_response(
        theory,
        objection_map.get(theory.id, []),
        tripwire_map.get(theory.id, []),
    )


# ---------------------------------------------------------------------------
# Clarifications
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# Decision frame
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Adversarial review and tripwires
# ---------------------------------------------------------------------------


@router.post("/graph/{project_id}/theories/challenge", response_model=AdversaryReport)
async def challenge_theories(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> AdversaryReport:
    """Attack every current theory, and let the objections cost rank."""
    await _require_project(project_id, session)
    try:
        report = await adversary_service.challenge_theories(session, project_id)
    except LLMError as exc:
        await session.rollback()
        logger.exception("Adversarial review failed for project %s", project_id)
        raise HTTPException(status_code=502, detail=f"Review failed: {exc}") from exc
    return AdversaryReport(**report)


@router.post("/graph/{project_id}/theories/tripwires", response_model=TripwireReport)
async def generate_tripwires(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> TripwireReport:
    """Give every current theory observations that could prove it wrong."""
    await _require_project(project_id, session)
    try:
        report = await adversary_service.generate_tripwires(session, project_id)
    except LLMError as exc:
        await session.rollback()
        logger.exception("Tripwire generation failed for project %s", project_id)
        raise HTTPException(status_code=502, detail=f"Generation failed: {exc}") from exc
    return TripwireReport(**report)


@router.post(
    "/graph/{project_id}/tripwires/{tripwire_id}/observe",
    response_model=TripwireResponse,
)
async def observe_tripwire(
    project_id: UUID,
    tripwire_id: UUID,
    req: ObservationRequest,
    session: AsyncSession = Depends(get_session),
) -> TripwireResponse:
    """Record whether a tripwire fired.

    A falsifying tripwire that fires marks its theory stale: the thing the user
    said would change their mind has happened.
    """
    await _require_project(project_id, session)
    try:
        row = await adversary_service.record_observation(
            session, project_id, tripwire_id, observed=req.observed, note=req.note
        )
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return TripwireResponse(
        id=row.id,
        observable=row.observable,
        direction=row.direction,
        horizon_days=row.horizon_days,
        check_by=row.check_by,
        status=row.status,
        observed_at=row.observed_at,
        observed_note=row.observed_note,
    )


@router.patch(
    "/graph/{project_id}/objections/{objection_id}/dismiss",
    response_model=ObjectionResponse,
)
async def dismiss_objection(
    project_id: UUID,
    objection_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ObjectionResponse:
    """Judge an objection unfounded, so it stops costing the theory rank."""
    await _require_project(project_id, session)
    row = (
        await session.execute(
            select(TheoryObjection)
            .join(Theory, Theory.id == TheoryObjection.theory_id)
            .where(TheoryObjection.id == objection_id, Theory.project_id == project_id)
        )
    ).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Objection not found")

    row.dismissed = True
    theory = await session.get(Theory, row.theory_id)
    if theory is not None:
        remaining = (
            await session.execute(
                select(TheoryObjection).where(TheoryObjection.theory_id == theory.id)
            )
        ).scalars().all()
        load = adversary_service.objection_load(remaining)
        theory.objection_load = load
        theory.contested = load >= adversary_service.CONTESTED_THRESHOLD
        theory.adjusted_score = adversary_service.adjusted_score(theory.confidence, load)

    await session.commit()
    await session.refresh(row)
    return ObjectionResponse(
        id=row.id,
        objection=row.objection,
        kind=row.kind,
        severity=row.severity,
        dismissed=row.dismissed,
    )


# ---------------------------------------------------------------------------
# Outside view
# ---------------------------------------------------------------------------


@router.post("/graph/{project_id}/outside-view", response_model=OutsideViewResponse)
async def run_outside_view(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> OutsideViewResponse:
    """Extract base rates from the user's recollection and check theories against them.

    The inside view is what the uploaded documents describe. This is the only
    outside view a one-off decision has, and it is usually the better predictor.
    """
    await _require_project(project_id, session)
    try:
        cases = await outside_view_service.extract_reference_cases(session, project_id)
        report = await outside_view_service.check_theories_against_base_rates(
            session, project_id
        )
    except LLMError as exc:
        await session.rollback()
        logger.exception("Outside view failed for project %s", project_id)
        raise HTTPException(status_code=502, detail=f"Outside view failed: {exc}") from exc

    return OutsideViewResponse(
        cases=[
            ReferenceCaseResponse(
                id=c.id,
                outcome=c.outcome,
                cases_total=c.cases_total,
                cases_with_outcome=c.cases_with_outcome,
                base_rate=c.base_rate,
                basis=c.basis,
                source=c.source,
            )
            for c in cases
        ],
        checked=report["checked"],
        diverging=report["diverging"],
    )


@router.get("/graph/{project_id}/outside-view", response_model=OutsideViewResponse)
async def get_outside_view(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> OutsideViewResponse:
    """Base rates already extracted for this project."""
    await _require_project(project_id, session)
    cases = await outside_view_service.list_reference_cases(session, project_id)
    return OutsideViewResponse(
        cases=[
            ReferenceCaseResponse(
                id=c.id,
                outcome=c.outcome,
                cases_total=c.cases_total,
                cases_with_outcome=c.cases_with_outcome,
                base_rate=c.base_rate,
                basis=c.basis,
                source=c.source,
            )
            for c in cases
        ]
    )


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------


def _experiment_response(experiment) -> ExperimentResponse_:
    """Map an experiment to its response shape."""
    persona_names = {p.id: p.name for p in experiment.personas}
    return ExperimentResponse_(
        id=experiment.id,
        theory_id=experiment.theory_id,
        kind=experiment.kind,
        hypothesis=experiment.hypothesis,
        design=experiment.design or "",
        measure=experiment.measure,
        cost_estimate=experiment.cost_estimate,
        duration_days=experiment.duration_days,
        status=experiment.status,
        support_count=experiment.support_count,
        oppose_count=experiment.oppose_count,
        neutral_count=experiment.neutral_count,
        summary=experiment.summary,
        executed_at=experiment.executed_at,
        personas=[
            PersonaResponse(
                id=p.id, name=p.name, role=p.role, stake=p.stake,
                prior_position=p.prior_position,
                grounded_in_frame=p.grounded_in_frame,
            )
            for p in experiment.personas
        ],
        reactions=[
            ReactionResponse(
                persona_id=r.persona_id,
                persona_name=persona_names.get(r.persona_id, ""),
                verdict=r.verdict,
                reaction=r.reaction,
                key_objection=r.key_objection,
                would_need=r.would_need,
            )
            for r in experiment.responses
        ],
        # Only a field experiment observes the world. A simulated room measures
        # how an argument lands, which is a different and lesser thing.
        is_evidence_about_the_world=experiment.kind == "field"
        and experiment.status == "executed",
    )


@router.post(
    "/graph/{project_id}/theories/{theory_id}/experiments/synthetic",
    response_model=ExperimentResponse_,
)
async def design_synthetic_experiment(
    project_id: UUID,
    theory_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ExperimentResponse_:
    """Cast the room this theory would have to survive."""
    await _require_project(project_id, session)
    try:
        experiment = await experiment_service.design_synthetic(
            session, project_id, theory_id
        )
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except experiment_service.ExperimentError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LLMError as exc:
        await session.rollback()
        logger.exception("Persona design failed for theory %s", theory_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _experiment_response(experiment)


@router.post(
    "/graph/{project_id}/experiments/{experiment_id}/execute",
    response_model=ExperimentResponse_,
)
async def execute_experiment(
    project_id: UUID,
    experiment_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ExperimentResponse_:
    """Run the simulated room.

    Substantive objections are promoted into the theory's adversarial log, where
    they cost rank and can be dismissed. The theory's confidence is deliberately
    untouched: nobody observed anything about the world.
    """
    await _require_project(project_id, session)
    try:
        experiment = await experiment_service.execute_synthetic(
            session, project_id, experiment_id
        )
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except experiment_service.ExperimentError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LLMError as exc:
        await session.rollback()
        logger.exception("Simulation failed for experiment %s", experiment_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _experiment_response(experiment)


@router.post(
    "/graph/{project_id}/theories/{theory_id}/experiments/field",
    response_model=ExperimentResponse_,
)
async def design_field_experiment(
    project_id: UUID,
    theory_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ExperimentResponse_:
    """Propose a real test that could be run before the decision is due.

    An empty design with a stated reason is a legitimate answer: it means the
    decision must be made on judgement, and the user should know that.
    """
    await _require_project(project_id, session)
    try:
        experiment = await experiment_service.design_field(
            session, project_id, theory_id
        )
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMError as exc:
        await session.rollback()
        logger.exception("Field design failed for theory %s", theory_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _experiment_response(experiment)


@router.get("/graph/{project_id}/experiments", response_model=ExperimentListResponse)
async def list_experiments(
    project_id: UUID,
    theory_id: UUID | None = None,
    session: AsyncSession = Depends(get_session),
) -> ExperimentListResponse:
    """Experiments for the project, newest first."""
    await _require_project(project_id, session)
    rows = await experiment_service.list_experiments(session, project_id, theory_id)
    return ExperimentListResponse(experiments=[_experiment_response(r) for r in rows])


# ---------------------------------------------------------------------------
# Manual graph authoring
# ---------------------------------------------------------------------------


@router.post("/graph/{project_id}/claims", response_model=AuthoringResult)
async def add_claim(
    project_id: UUID,
    req: AddClaimRequest,
    session: AsyncSession = Depends(get_session),
) -> AuthoringResult:
    """Add a claim the documents did not contain.

    In a strategic decision the factors that matter are often not written down
    anywhere. A graph that can only be pruned cannot be corrected.
    """
    project = await _require_project(project_id, session)
    try:
        claim, plan = await authoring_service.add_claim(
            session, project_id,
            text=req.text, claim_type=req.claim_type,
            prior=req.prior, confidence=req.confidence, user_note=req.user_note,
        )
    except authoring_service.AuthoringError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    await session.refresh(project)
    return AuthoringResult(
        element_id=claim.id,
        target_type="claim",
        graph_revision=project.graph_revision or 1,
        plan=RecomputePlanResponse(**plan.as_dict()),
    )


@router.post("/graph/{project_id}/edges", response_model=AuthoringResult)
async def add_edge(
    project_id: UUID,
    req: AddEdgeRequest,
    session: AsyncSession = Depends(get_session),
) -> AuthoringResult:
    """Add a causal link the model did not infer."""
    project = await _require_project(project_id, session)
    try:
        edge, plan = await authoring_service.add_edge(
            session, project_id,
            source_claim_id=req.source_claim_id,
            target_claim_id=req.target_claim_id,
            mechanism=req.mechanism,
            effect=req.effect,
            link_confidence=req.link_confidence,
            user_note=req.user_note,
        )
    except authoring_service.AuthoringError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    await session.refresh(project)
    return AuthoringResult(
        element_id=edge.id,
        target_type="edge",
        graph_revision=project.graph_revision or 1,
        plan=RecomputePlanResponse(**plan.as_dict()),
    )


@router.post("/graph/{project_id}/infer-links", response_model=InferLinksResponse)
async def infer_links(
    project_id: UUID,
    claim_ids: list[UUID],
    session: AsyncSession = Depends(get_session),
) -> InferLinksResponse:
    """Infer causal links between newly added claims and the existing graph.

    Only pairs involving a new claim are considered: re-inferring everything
    would regenerate links the user has already rejected.
    """
    project = await _require_project(project_id, session)
    try:
        edges = await authoring_service.infer_links_for_new_claims(
            session, project_id, claim_ids
        )
    except LLMError as exc:
        await session.rollback()
        logger.exception("Incremental inference failed for project %s", project_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    await session.refresh(project)
    return InferLinksResponse(
        new_edge_ids=[e.id for e in edges],
        graph_revision=project.graph_revision or 1,
    )


@router.post("/graph/{project_id}/recompute", response_model=RecomputeResponse)
async def recompute(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> RecomputeResponse:
    """Rebuild the DAG and re-propagate beliefs.

    Pure computation, no LLM. Must cover the whole graph: one new node changes
    topology, cycles and every downstream belief.
    """
    await _require_project(project_id, session)
    return RecomputeResponse(
        **await authoring_service.recompute_beliefs(session, project_id)
    )


# ---------------------------------------------------------------------------
# Theory debate
# ---------------------------------------------------------------------------


def _debate_response(debate: TheoryDebate) -> DebateResponse:
    """Map a debate to its response shape."""
    return DebateResponse(
        id=debate.id,
        theory_a_id=debate.theory_a_id,
        theory_b_id=debate.theory_b_id,
        overlap_jaccard=debate.overlap_jaccard,
        relation=debate.relation,  # type: ignore[arg-type]
        shared_claim_ids=debate.shared_claim_ids or [],
        shared_edge_ids=debate.shared_edge_ids or [],
        divergent_claim_ids=debate.divergent_claim_ids or [],
        divergent_edge_ids=debate.divergent_edge_ids or [],
        crux=debate.crux,
        discriminator=debate.discriminator,
        discriminator_feasible=debate.discriminator_feasible,
        discriminator_horizon_days=debate.discriminator_horizon_days,
        evidence_favours=debate.evidence_favours,  # type: ignore[arg-type]
        both_possible=debate.both_possible,
        is_stale=debate.is_stale,
        promoted_tripwire_at=debate.promoted_tripwire_at,
        created_at=debate.created_at,
    )


@router.post("/graph/{project_id}/debates", response_model=DebateReport)
async def run_debates(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> DebateReport:
    """Compare the leading theories pairwise.

    Overlap is computed from the graph, so pairs that turn out to be the same
    theory in two wordings never reach the model.
    """
    await _require_project(project_id, session)
    try:
        report = await debate_service.run_debates(session, project_id)
    except debate_service.DebateError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMError as exc:
        await session.rollback()
        logger.exception("Debate failed for project %s", project_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return DebateReport(**{k: v for k, v in report.items() if k != "debate_ids"})


@router.get("/graph/{project_id}/debates", response_model=DebateListResponse)
async def list_debates(
    project_id: UUID,
    include_stale: bool = False,
    session: AsyncSession = Depends(get_session),
) -> DebateListResponse:
    """Comparisons for the project, the ones that generate work first."""
    await _require_project(project_id, session)
    debates = await debate_service.list_debates(
        session, project_id, include_stale=include_stale
    )
    return DebateListResponse(debates=[_debate_response(d) for d in debates])


@router.post(
    "/graph/{project_id}/debates/{debate_id}/tripwire",
    response_model=list[TripwireResponse],
)
async def promote_discriminator(
    project_id: UUID,
    debate_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> list[TripwireResponse]:
    """Turn a discriminator into a tripwire on both theories.

    Explicit rather than automatic, for consistency: everywhere else here the
    model proposes and the user commits.
    """
    await _require_project(project_id, session)
    try:
        tripwires = await debate_service.promote_to_tripwire(
            session, project_id, debate_id
        )
    except debate_service.DebateError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return [
        TripwireResponse(
            id=t.id, observable=t.observable, direction=t.direction,
            horizon_days=t.horizon_days, check_by=t.check_by, status=t.status,
            observed_at=t.observed_at, observed_note=t.observed_note,
        )
        for t in tripwires
    ]


# ---------------------------------------------------------------------------
# Decision domains
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# Decision brief
# ---------------------------------------------------------------------------


@router.get("/graph/{project_id}/brief")
async def export_brief(
    project_id: UUID,
    format: str = "markdown",
    session: AsyncSession = Depends(get_session),
):
    """Export the decision brief.

    A decision is presented in a room, not in a web application. If the
    objections and tripwires can only be reached by clicking, what reaches the
    room is the recommendation with its qualifications stripped — so the brief
    carries them at the same level as the conclusion.
    """
    from fastapi.responses import Response

    await _require_project(project_id, session)
    try:
        content, media_type, filename = await brief_service.export_brief(
            session, project_id, format
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Decision profile — answered once, reused
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# The recommendation
# ---------------------------------------------------------------------------


def _recommendation_response(row, stale: bool) -> RecommendationResponse:
    """Map the recommendation to its response shape."""
    return RecommendationResponse(
        recommendation=row.recommendation,
        reasoning=row.reasoning or "",
        depends_on=row.depends_on or [],
        against_it=row.against_it,
        next_step=row.next_step,
        confidence=row.confidence,  # type: ignore[arg-type]
        is_stale=stale,
        created_at=row.created_at,
    )


@router.get("/graph/{project_id}/recommendation", response_model=RecommendationResponse)
async def get_recommendation(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> RecommendationResponse:
    """What the analysis recommends, weighed across every theory."""
    await _require_project(project_id, session)
    row = await recommendation_service.get_recommendation(session, project_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="No recommendation has been generated for this project yet.",
        )
    return _recommendation_response(
        row, await recommendation_service.is_stale(session, row)
    )


@router.post("/graph/{project_id}/recommendation", response_model=RecommendationResponse)
async def generate_recommendation(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> RecommendationResponse:
    """Weigh the current theories and say what to do."""
    await _require_project(project_id, session)
    try:
        row = await recommendation_service.generate_recommendation(session, project_id)
    except recommendation_service.RecommendationError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMError as exc:
        await session.rollback()
        logger.exception("Recommendation failed for project %s", project_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _recommendation_response(row, False)


# ---------------------------------------------------------------------------
# Token and cost accounting
# ---------------------------------------------------------------------------


@router.get("/graph/{project_id}/usage")
async def get_usage(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """What this analysis cost, per stage.

    Returns every run, newest first: re-running after a failure is a second real
    cost, and folding them together would understate what the project consumed.

    Costs are advisory — computed from a hard-coded price table whose date is
    returned alongside them. Token counts come from the provider and are exact.
    """
    from decision_studio.db.models import AnalysisUsage

    await _require_project(project_id, session)
    rows = (
        await session.execute(
            select(AnalysisUsage)
            .where(AnalysisUsage.project_id == project_id)
            .order_by(AnalysisUsage.created_at.desc())
        )
    ).scalars().all()

    runs = [
        {
            "calls": r.calls,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "total_tokens": r.input_tokens + r.output_tokens,
            "cost_usd": round(r.cost_usd, 4),
            "unpriced_calls": r.unpriced_calls,
            "price_table_date": r.price_table_date,
            "by_stage": r.by_stage or {},
            "created_at": r.created_at,
        }
        for r in rows
    ]

    return {
        "runs": runs,
        "total_cost_usd": round(sum(r["cost_usd"] for r in runs), 4),
        "total_tokens": sum(r["total_tokens"] for r in runs),
    }
