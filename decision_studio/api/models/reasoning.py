"""Pydantic schemas for the decision-reasoning endpoints.

Field naming follows the repo convention: snake_case on the wire, mapped to
camelCase in the frontend transformers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

ReviewStatus = Literal[
    "accepted",
    "rejected",
    "uncertain",
    "business_critical",
    "not_relevant",
    "needs_evidence",
]
TheoryStatus = Literal[
    "hypothesis", "supported", "contested", "insufficient_evidence", "superseded"
]
BusinessImpact = Literal["low", "medium", "high", "critical"]
AnswerType = Literal[
    "free_text", "single_choice", "multi_choice", "yes_no", "number", "date"
]
QuestionStatus = Literal["open", "answered", "dismissed", "skipped"]


# --- Graph review ---


class ReviewRequest(BaseModel):
    """Review a claim or an edge. Every field is optional; at least one required."""

    review_status: ReviewStatus | None = None
    is_active: bool | None = None
    user_note: str | None = Field(None, max_length=4000)
    strength_override: float | None = Field(None, ge=0.0, le=1.0)
    clear_strength_override: bool = False
    mechanism: str | None = Field(None, max_length=2000, description="Edges only.")
    note: str | None = Field(None, max_length=500, description="Audit-log note.")
    expected_graph_revision: int | None = Field(
        None,
        description="Optimistic concurrency: reject the edit if the graph moved on.",
    )


class ReviewStateResponse(BaseModel):
    """Current review state of one element."""

    id: UUID
    target_type: Literal["claim", "edge"]
    review_status: str
    is_active: bool
    user_note: str | None = None
    strength_override: float | None = None
    reviewed_at: datetime | None = None


class GraphOperationResponse(BaseModel):
    """One entry of the review audit log."""

    id: UUID
    operation_type: str
    target_type: str
    claim_id: UUID | None = None
    edge_id: UUID | None = None
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    revision_before: int
    revision_after: int
    source: str
    note: str | None = None
    undone_at: datetime | None = None
    created_at: datetime | None = None


class ReviewResult(BaseModel):
    """Result of a review operation."""

    element: ReviewStateResponse
    operation: GraphOperationResponse
    graph_revision: int
    stale_theory_count: int


class GraphOperationListResponse(BaseModel):
    operations: list[GraphOperationResponse]
    graph_revision: int


class GraphRevisionResponse(BaseModel):
    """Current revision plus effective-graph counts."""

    project_id: UUID
    graph_revision: int
    active_claim_count: int
    active_edge_count: int
    total_claim_count: int
    total_edge_count: int
    decision_objective: str | None = None


class DecisionObjectiveRequest(BaseModel):
    decision_objective: str = Field(..., max_length=2000)


class AnchorOption(BaseModel):
    key: str = ""
    label: str = Field(..., max_length=200)


class AnchorOutcome(BaseModel):
    key: str = ""
    label: str = Field(..., max_length=200)
    measure: str = Field("", max_length=200)


class DecisionAnchor(BaseModel):
    """The decision, stated so the pipeline can steer by it.

    Keys (O1, Y1 ...) are optional on input and assigned when missing; existing
    keys are preserved because claims refer to them.
    """

    decision: str = Field(..., max_length=2000)
    options: list[AnchorOption] = Field(default_factory=list, max_length=10)
    outcomes: list[AnchorOutcome] = Field(default_factory=list, max_length=10)
    deadline: str = Field("", max_length=200)
    constraints: list[str] = Field(default_factory=list, max_length=10)
    status: str = "draft"


class DecisionAnchorResponse(BaseModel):
    project_id: UUID
    anchor: DecisionAnchor | None = None


class DecisionAnchorSaveResponse(DecisionAnchorResponse):
    """The saved anchor, and what saving it changed in an existing graph."""

    report: dict[str, int] = Field(default_factory=dict)


# --- Theories ---


class CausalChainStep(BaseModel):
    """One step of a chain. `gap_before` marks where a link was dropped for
    failing to join its neighbours, so the UI can draw the break rather than
    render a broken chain as a continuous one."""

    """One hop of a theory's causal chain: either a claim or an edge."""

    claim_id: UUID | None = None
    edge_id: UUID | None = None
    source_claim_id: UUID | None = None
    target_claim_id: UUID | None = None
    label: str | None = None


class TheoryResponse(BaseModel):
    #: Chain links whose endpoints match their neighbours, over links cited.
    #: Exposed rather than folded into the score — see the model comment.
    connected_links: int = 0
    cited_links: int = 0

    """A decision-oriented theory with full provenance."""

    id: UUID
    project_id: UUID
    theory_key: UUID
    title: str
    summary: str
    status: TheoryStatus
    causal_chain: list[CausalChainStep] = []
    supporting_claim_ids: list[UUID] = []
    supporting_edge_ids: list[UUID] = []
    supporting_evidence_ids: list[UUID] = []
    contradicting_evidence_ids: list[UUID] = []
    weak_assumptions: list[str] = []
    confidence: float
    business_impact: BusinessImpact
    recommendation: str
    graph_revision: int
    theory_revision: int
    version: int
    is_current: bool
    # --- Adversarial review ---
    objection_load: float = 0.0
    contested: bool = False
    adjusted_score: float | None = None
    objections: list[ObjectionResponse] = []
    tripwires: list[TripwireResponse] = []
    # --- Outside view: how far this departs from comparable cases ---
    outside_view_delta: float | None = None
    outside_view_note: str | None = None
    # --- Calibration: bands, because the decimals were never earned ---
    confidence_band: str = "unknown"
    is_stale: bool
    stale_reason: str | None = None
    change_kind: str | None = None
    change_explanation: str | None = None
    created_at: datetime | None = None
    # --- Theory of value ---
    #: The anchor option this is a theory of, and what it predicts for it.
    option_key: str | None = None
    predicted_effect: str | None = None
    outcome_keys: list[str] = []
    #: Computed from the validated chain, not taken from the model.
    reaches_outcome: bool = False
    # --- The decider's conviction, apart from the model's confidence ---
    conviction: float | None = None
    conviction_prior: float | None = None


class OptionCoverage(BaseModel):
    """How many current theories argue for and against one option."""

    key: str
    label: str
    achieves: int = 0
    threatens: int = 0
    unclear: int = 0
    reaching_outcome: int = 0


class ChangeSummary(BaseModel):
    new_theory_ids: list[UUID] = []
    changed_theory_ids: list[UUID] = []
    unchanged_theory_ids: list[UUID] = []
    superseded_theory_ids: list[UUID] = []


class TheoryListResponse(BaseModel):
    theories: list[TheoryResponse]
    graph_revision: int
    theory_revision: int | None = None
    stale_count: int = 0
    #: One row per anchor option. An option with no theory is a finding.
    option_coverage: list[OptionCoverage] = []


class TheoryGenerationResponse(BaseModel):
    """Result of generate/regenerate, including what changed."""

    graph_revision: int
    theory_revision: int
    theories: list[TheoryResponse]
    change_summary: ChangeSummary
    validation: dict[str, Any] = {}


class TheoryRevisionResponse(BaseModel):
    id: UUID
    revision: int
    graph_revision: int
    trigger: str
    change_summary: ChangeSummary | None = None
    generation_metadata: dict[str, Any] | None = None
    created_at: datetime | None = None


class TheoryRevisionListResponse(BaseModel):
    revisions: list[TheoryRevisionResponse]


class TheoryVersionsResponse(BaseModel):
    theory_key: UUID
    versions: list[TheoryResponse]








class ObjectionResponse(BaseModel):
    """An adversarial critique written without seeing the theory's case-for."""

    id: UUID
    objection: str
    kind: str
    severity: float
    dismissed: bool


class TripwireResponse(BaseModel):
    """A falsifiable forward commitment."""

    id: UUID
    observable: str
    direction: Literal["falsifies", "confirms"]
    horizon_days: int
    check_by: datetime | None = None
    status: Literal["pending", "observed", "not_observed", "expired"]
    observed_at: datetime | None = None
    observed_note: str | None = None


class ObservationRequest(BaseModel):
    observed: bool
    note: str | None = Field(None, max_length=2000)
    #: How much more likely this outcome is if the theory holds. Omitted, the
    #: tripwire's direction supplies a default (reasoning/theory_value.py).
    likelihood_ratio: float | None = Field(None, gt=0, le=20)


class ReferenceCaseResponse(BaseModel):
    """A base rate drawn from the user's own experience."""

    id: UUID
    outcome: str
    cases_total: int
    cases_with_outcome: int
    base_rate: float
    basis: str | None = None
    source: str = "user_recall"


class OutsideViewResponse(BaseModel):
    cases: list[ReferenceCaseResponse] = []
    checked: int = 0
    diverging: int = 0


class RecommendationResponse(BaseModel):
    """What to do, weighed across every theory at once.

    Distinct from `Theory.recommendation`, which speaks for one explanation.
    Stacking those produces contradictory advice with nothing to resolve it.
    """

    recommendation: str
    reasoning: str = ""
    depends_on: list[str] = []
    against_it: str | None = None
    next_step: str | None = None
    confidence: Literal["low", "moderate", "high"] = "moderate"
    is_stale: bool = Field(
        False,
        description="True when the theories have been regenerated since. The "
                    "advice describes explanations the reader can no longer find.",
    )
    created_at: datetime | None = None


class DebateResponse(BaseModel):
    """A structural comparison of two theories, plus what would separate them.

    There is deliberately no transcript field: two agents arguing are the same
    model twice. What is decision-relevant is the crux and the discriminator.
    """

    id: UUID
    theory_a_id: UUID
    theory_b_id: UUID
    overlap_jaccard: float
    relation: Literal["same_story", "competing", "orthogonal"]
    shared_claim_ids: list[UUID] = []
    shared_edge_ids: list[UUID] = []
    divergent_claim_ids: list[UUID] = []
    divergent_edge_ids: list[UUID] = []
    crux: str | None = None
    discriminator: str | None = None
    discriminator_feasible: bool = False
    discriminator_horizon_days: int | None = None
    evidence_favours: Literal["a", "b", "neither"] | None = None
    both_possible: bool = False
    is_stale: bool = False
    promoted_tripwire_at: datetime | None = None
    created_at: datetime | None = None


class DebateListResponse(BaseModel):
    debates: list[DebateResponse] = []


class DebateReport(BaseModel):
    """What a debate run found, and what it cost."""

    pairs: int = 0
    same_story: int = 0
    competing: int = 0
    orthogonal: int = 0
    model_calls: int = Field(
        0, description="Fewer than pairs: same-story pairs skip the model entirely."
    )
    with_discriminator: int = 0


class AddClaimRequest(BaseModel):
    """Add a claim the uploaded documents did not contain."""

    text: str = Field(..., min_length=1, max_length=2000)
    claim_type: Literal["FACT", "ASSUMPTION", "PREDICTION", "OPINION"] = "ASSUMPTION"
    prior: float = Field(0.5, ge=0.0, le=1.0, description="Probability it is true.")
    confidence: float = Field(
        0.8, ge=0.0, le=1.0, description="How firmly you assert it."
    )
    user_note: str | None = Field(None, max_length=2000)


class AddEdgeRequest(BaseModel):
    """Add a causal link the model did not infer."""

    source_claim_id: UUID
    target_claim_id: UUID
    mechanism: str = Field(..., min_length=1, max_length=2000)
    effect: float = Field(0.5, ge=0.0, le=1.0)
    link_confidence: float = Field(0.5, ge=0.0, le=1.0)
    user_note: str | None = Field(None, max_length=2000)


class RecomputePlanResponse(BaseModel):
    """What a graph change invalidated, and what restoring it will cost."""

    new_claim_ids: list[UUID] = []
    new_edge_ids: list[UUID] = []
    needs_causal_inference: bool = False
    needs_evidence_grounding: bool = False
    needs_propagation: bool = True
    estimated_llm_calls: int = 0
    skipped: list[str] = []


class AuthoringResult(BaseModel):
    element_id: UUID
    target_type: Literal["claim", "edge"]
    graph_revision: int
    plan: RecomputePlanResponse


class InferLinksResponse(BaseModel):
    """Links inferred between newly added claims and the existing graph."""

    new_edge_ids: list[UUID] = []
    graph_revision: int


class RecomputeResponse(BaseModel):
    claims: int = 0
    edges: int = 0
    nodes_propagated: int = 0


class PersonaResponse(BaseModel):
    """A simulated stakeholder. A role, not a real person."""

    id: UUID
    name: str
    role: str
    stake: str
    prior_position: str | None = None
    grounded_in_frame: bool = False


class ReactionResponse(BaseModel):
    persona_id: UUID
    persona_name: str = ""
    verdict: Literal["supports", "opposes", "neutral"]
    reaction: str
    key_objection: str | None = None
    would_need: str | None = None


class ExperimentResponse_(BaseModel):
    """A synthetic or field experiment.

    `kind` is load-bearing. A synthetic run measures how an argument lands with
    the people who must agree; it is NOT evidence about the world and never
    moves a theory's confidence. Only a field experiment does that.
    """

    id: UUID
    theory_id: UUID
    kind: Literal["synthetic", "field"]
    hypothesis: str
    design: str
    measure: str | None = None
    cost_estimate: str | None = None
    duration_days: int | None = None
    status: Literal["designed", "executed", "abandoned"]
    support_count: int = 0
    oppose_count: int = 0
    neutral_count: int = 0
    summary: str | None = None
    executed_at: datetime | None = None
    personas: list[PersonaResponse] = []
    reactions: list[ReactionResponse] = []
    #: Always false for synthetic runs; the UI must not present them as proof.
    is_evidence_about_the_world: bool = False


class ExperimentListResponse(BaseModel):
    experiments: list[ExperimentResponse_] = []


class AdversaryReport(BaseModel):
    theories: int = 0
    objections: int = 0
    contested: int = 0


class TripwireReport(BaseModel):
    theories: int = 0
    tripwires: int = 0


class GenerateTheoriesRequest(BaseModel):
    """Options for a generation run."""

    max_claims: int | None = Field(
        None, ge=5, le=200, description="Cap on claims sent to the model."
    )


# --- Clarifications ---










# DEAD-CODE-CANDIDATE DC-22: clarification-system response model; no route uses it. See docs/DEAD_CODE_REPORT.md
class AnswerResponse(BaseModel):
    affected_theory_ids: list[UUID] = []
    stale_theory_count: int = 0


# DEAD-CODE-CANDIDATE DC-22: clarification-system request model; no route uses it. See docs/DEAD_CODE_REPORT.md
class QuestionStatusRequest(BaseModel):
    status: QuestionStatus




# DEAD-CODE-CANDIDATE DC-22: clarification-system model; used only by dead frontend DC-36. See docs/DEAD_CODE_REPORT.md
class ProposedGraphChange(BaseModel):
    """A graph edit an answer suggests. Never applied automatically."""

    target_type: Literal["claim", "edge"]
    target_id: UUID
    suggested_review_status: ReviewStatus
    rationale: str
    question_id: UUID


