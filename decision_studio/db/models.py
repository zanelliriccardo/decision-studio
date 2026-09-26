import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "project"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(500))
    input_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    has_temporal: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    last_completed_stage: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="Checkpoint for pipeline resume: claim_extraction, causal_inference, bias_audit, evidence_grounding, dag_construction, belief_propagation",
    )

    # --- Decision reasoning (human-in-the-loop review) ---
    graph_revision: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1",
        comment="Monotonic counter bumped by every persisted graph review operation. "
                "Theories are pinned to the revision they were generated from.",
    )
    intake_context: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="The rendered answers to the intake questions, exactly as they "
                "were prepended to the extraction and inference prompts. Stored "
                "verbatim rather than rebuilt from the answers: six months on, "
                "the question is what the model actually read, and re-rendering "
                "under changed code would answer a different one.",
    )
    decision_objective: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="What decision the user is trying to make. Steers theory and "
                "theory generation.",
    )
    outside_view_recollection: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="The decider's own account of comparable past decisions and how "
                "they went. Base rates are read from it (reference_case).",
    )
    sub_decisions: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="Sub-decisions under an option, each with choices defined by existing "
                "claims. See reasoning/sub_decisions.py.",
    )
    outcome_priorities: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="Outcome key (Y1..) -> importance (critical, high, medium, low, none): "
                "how much each success criterion matters to the decider. See "
                "reasoning/decision_priorities.py. Never changes the graph.",
    )
    decision_anchor: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="The decision in a form the pipeline can steer by: decision, "
                "options, outcomes, deadline, constraints and whether the user "
                "confirmed it. See reasoning/decision_anchor.py.",
    )

    # Relationships
    claims: Mapped[list["Claim"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    edges: Mapped[list["CausalEdge"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    scenarios: Mapped[list["Scenario"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Claim(Base):
    __tablename__ = "claim"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE")
    )
    text: Mapped[str] = mapped_column(Text)
    claim_type: Mapped[str] = mapped_column(
        String(50), comment="FACT, ASSUMPTION, PREDICTION, or OPINION"
    )
    confidence: Mapped[float] = mapped_column(
        Float, default=0.5,
        comment="How firmly the SOURCE asserts this claim (assertion strength). "
                "Emphatic, unhedged writing scores high. This is a property of the "
                "text, NOT of the world -- never use it as a probability.",
    )
    prior: Mapped[float] = mapped_column(
        Float, default=0.5, server_default="0.5",
        comment="Probability the claim is actually TRUE, accounting for source type, "
                "hedging and author incentive. This is what belief propagation seeds "
                "root nodes with. A vendor's emphatic promise has high confidence and "
                "low prior; a hedged internal admission of a problem is the reverse.",
    )
    source_interest: Mapped[str] = mapped_column(
        String(20), default="unknown", server_default="unknown",
        comment="Does the author of this claim gain from it being believed? "
                "against_interest (an admission that costs them), disinterested, "
                "interested (they benefit), or unknown. An admission against "
                "interest is strong evidence; an assurance from a beneficiary is "
                "weak however emphatic. Feeds `prior`.",
    )
    source_role: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Who is asserting it, in the extractor's words, e.g. "
                "'the vendor's account manager'. Shown to the user so the "
                "interest judgement is auditable rather than a bare label.",
    )
    corroborated_by: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="Source sentences of duplicate claims merged into this one, so a fact "
                "stated in several places is visibly one fact with several witnesses.",
    )
    duplicate_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0",
        comment="How many near-identical claims were merged into this one.",
    )
    # 1536 to match settings.embedding_dimensions and the migration that
    # created the column. The model said 1024, which the live database
    # contradicted: anything built from Base.metadata (the test fixtures) got a
    # column too narrow for a real embedding, and the mismatch only surfaced as
    # "expected 1536 dimensions, not 1024" at insert time.
    embedding = mapped_column(Vector(1536), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSON, nullable=True
    )
    source_sentence: Mapped[str | None] = mapped_column(Text, nullable=True)
    logic_gate: Mapped[str] = mapped_column(String(10), default="or")
    order_index: Mapped[int] = mapped_column(Integer)
    layer: Mapped[int] = mapped_column(Integer, default=0)

    # --- Human review state (see decision_studio/reasoning/review.py) ---
    review_status: Mapped[str] = mapped_column(
        String(30), default="accepted", server_default="accepted",
        comment="accepted, rejected, uncertain, business_critical, not_relevant, needs_evidence",
    )
    origin: Mapped[str] = mapped_column(
        String(10), default="ai", server_default="ai",
        comment="ai, user or frame. A user-authored claim is not blind re-scored: "
                "that pass exists to correct a model scoring its own proposal, and "
                "a human's own judgement is authoritative here by design. 'frame' "
                "marks an outcome node created from the decision anchor.",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true",
        comment="Reversible soft delete. Inactive claims stay visible in the graph "
                "but are excluded from the effective graph used for reasoning.",
    )
    user_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Relation to the decision (see reasoning/decision_anchor.py) ---
    # Scores, never filters. All null when the project has no anchor.
    decision_role: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="lever, contingency, mechanism, outcome or background. "
                "'outcome' with origin 'frame' marks an anchor node.",
    )
    relevance: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        comment="0-1, how directly this claim bears on the decision, as judged "
                "by the model. Structural relevance is computed from the graph.",
    )
    relevance_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    bears_on: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="Anchor keys this claim affects, e.g. ['O1', 'Y2'].",
    )

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="claims")


class CausalEdge(Base):
    __tablename__ = "causal_edge"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE")
    )
    source_claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("claim.id", ondelete="CASCADE")
    )
    target_claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("claim.id", ondelete="CASCADE")
    )
    mechanism: Mapped[str] = mapped_column(Text)
    strength: Mapped[float] = mapped_column(
        Float,
        comment="Operative weight used by propagation. DERIVED: effect * link_confidence "
                "(see decision_studio.graph.edge_weight.edge_strength). Kept as a stored column "
                "so every existing consumer keeps working unchanged.",
    )
    effect: Mapped[float] = mapped_column(
        Float, default=0.5, server_default="0.5",
        comment="Size of the effect IF the link is real, 0-1. Answers 'how much gets "
                "through', not 'is this true'.",
    )
    link_confidence: Mapped[float] = mapped_column(
        Float, default=0.5, server_default="0.5",
        comment="Certainty the causal link exists at all, 0-1. A weak-but-certain link "
                "(effect 0.2, confidence 0.95) and a strong-but-speculative one "
                "(effect 0.9, confidence 0.2) are opposite situations that a single "
                "strength value cannot distinguish.",
    )
    author_effect: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        comment="Effect as scored by the call that PROPOSED this edge, before blind "
                "re-scoring. Kept to measure per-source inflation.",
    )
    author_confidence: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        comment="Link confidence as scored by the proposing call, before blind re-scoring.",
    )
    blind_scored: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false",
        comment="True once a rater that could not see which claim pair belongs to which "
                "argument has re-scored this edge.",
    )
    time_delay: Mapped[str | None] = mapped_column(Text, nullable=True)
    conditions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reversible: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_score: Mapped[float] = mapped_column(Float, default=0.5)
    causal_type: Mapped[str] = mapped_column(String(50), default="direct")
    condition_type: Mapped[str] = mapped_column(String(50), default="contributing")
    temporal_window: Mapped[str | None] = mapped_column(Text, nullable=True)
    decay_type: Mapped[str] = mapped_column(String(50), default="none")
    bias_warnings = mapped_column(JSON, nullable=True)
    is_feedback: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # Statistical validation (populated by StatisticalValidator stage)
    statistical_validation: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="confirmed, unsupported, contradicted, or not_tested",
    )
    stat_p_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    stat_f_statistic: Mapped[float | None] = mapped_column(Float, nullable=True)
    stat_effect_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    stat_lag: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Human review state (see decision_studio/reasoning/review.py) ---
    review_status: Mapped[str] = mapped_column(
        String(30), default="accepted", server_default="accepted",
        comment="accepted, rejected, uncertain, business_critical, not_relevant, needs_evidence",
    )
    origin: Mapped[str] = mapped_column(
        String(10), default="ai", server_default="ai",
        comment="ai or user. User-authored edges skip blind re-scoring.",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true",
        comment="Reversible soft delete. Inactive edges stay visible in the graph "
                "but are excluded from the effective graph used for reasoning.",
    )
    user_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    strength_override: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        comment="Human override of the AI-inferred strength (0..1). Takes precedence "
                "over `strength` in the effective graph; `strength` is preserved.",
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="edges")
    source_claim: Mapped["Claim"] = relationship(foreign_keys=[source_claim_id])
    target_claim: Mapped["Claim"] = relationship(foreign_keys=[target_claim_id])
    evidences: Mapped[list["Evidence"]] = relationship(
        back_populates="edge", cascade="all, delete-orphan"
    )


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    edge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causal_edge.id", ondelete="CASCADE")
    )
    evidence_type: Mapped[str] = mapped_column(
        String(50), comment="supporting or contradicting"
    )
    source_url: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Null for internal sources (reports, meeting notes, interviews), "
                "which have no URL and must not be forced to invent one.",
    )
    author_interest: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="Does the author gain from being believed? disinterested, "
                "interested or against_interest. An admission that costs the "
                "author something is strong evidence; an assurance from a "
                "beneficiary is weak however emphatic.",
    )
    source_title: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(
        String(50), comment="academic, news, blog, forum, or other"
    )
    snippet: Mapped[str] = mapped_column(Text)
    relevance_score: Mapped[float] = mapped_column(Float)
    credibility_score: Mapped[float] = mapped_column(Float)
    source_tier: Mapped[int] = mapped_column(Integer, default=4)
    published_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    freshness_score: Mapped[float] = mapped_column(Float, default=0.5)

    # Relationships
    edge: Mapped["CausalEdge"] = relationship(back_populates="evidences")


class Scenario(Base):
    __tablename__ = "scenario"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE")
    )
    parent_scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenario.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    edge_overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    decision_case: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="upside or downside: the decider's assumptions for that case of the "
                "option comparison (reasoning/decision_scenarios.py). Null for forks.",
    )
    claim_overrides: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="Claim id -> prior, for decision cases.",
    )
    injected_events: Mapped[list] = mapped_column(JSON, default=list)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_insights: Mapped[list | None] = mapped_column(JSON, nullable=True)
    conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)
    edge_change_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="scenarios")
    parent: Mapped["Scenario | None"] = relationship(
        remote_side=[id], foreign_keys=[parent_scenario_id]
    )


# --------------------------------------------------------------------------
# Three-Layer Causal Analysis Models
# --------------------------------------------------------------------------

# DEAD-CODE-CANDIDATE DC-30 [table]: written only by the deprecated DC-24 endpoints. Dropping it needs a migration. See docs/DEAD_CODE_REPORT.md
class MultiLayerEvidence(Base):
    """Multi-layer causal evidence. Each row is one piece of evidence for a
    causal relationship produced by a specific layer/algorithm."""

    __tablename__ = "multi_layer_evidence"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), nullable=True
    )
    source_claim_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("claim.id", ondelete="SET NULL"), nullable=True
    )
    target_claim_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("claim.id", ondelete="SET NULL"), nullable=True
    )
    source_label: Mapped[str] = mapped_column(String(500))
    target_label: Mapped[str] = mapped_column(String(500))

    # Which layer / algorithm
    layer: Mapped[int] = mapped_column(Integer)  # 1=LLM, 2=monitoring, 3=statistical
    algorithm: Mapped[str] = mapped_column(String(50))  # "llm", "granger", "pc", "fci", "pcmci"

    # Edge semantics
    edge_type: Mapped[str] = mapped_column(String(30), default="directed")
    lag: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Confidence & statistics
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    p_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    effect_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Context
    data_type: Mapped[str] = mapped_column(String(30), default="unknown")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    source_claim: Mapped["Claim | None"] = relationship(foreign_keys=[source_claim_id])
    target_claim: Mapped["Claim | None"] = relationship(foreign_keys=[target_claim_id])


class EventTimeline(Base):
    """PM intervention or external events for causal timeline tracking."""

    __tablename__ = "event_timeline"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_type: Mapped[str] = mapped_column(String(30))  # pricing, feature, campaign, external, bug, other
    event_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual, chat_extracted, api_detected
    affected_metrics: Mapped[list | None] = mapped_column(JSON, nullable=True)
    evidence_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AdvisorSession(Base):
    """A conversation session within the Strategic Advisor."""

    __tablename__ = "advisor_session"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(500), default="New conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    messages: Mapped[list["AdvisorMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan",
        order_by="AdvisorMessage.created_at",
    )


class AdvisorMessage(Base):
    """Persisted advisor conversation messages."""

    __tablename__ = "advisor_message"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("advisor_session.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(20))  # "user" or "assistant"
    content: Mapped[str] = mapped_column(Text)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["AdvisorSession"] = relationship(back_populates="messages")


# DEAD-CODE-CANDIDATE DC-30 [table]: written only by the deprecated DC-24 endpoints (the pipeline's statistical validator receives metric data in memory). Dropping it needs a migration. See docs/DEAD_CODE_REPORT.md
class MetricSeries(Base):
    """Time-series metric data from CSV/Excel/screenshot uploads."""

    __tablename__ = "metric_series"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(500))
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    frequency: Mapped[str | None] = mapped_column(String(20), nullable=True)
    data_points: Mapped[dict] = mapped_column(JSON)
    source_file: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --------------------------------------------------------------------------
# Decision Reasoning Models
#
# ARCHITECTURE NOTE — revision strategy
# -------------------------------------
# Decision Studio already had two mutation mechanisms: `Scenario.edge_overrides`
# (hypothetical what-if forks, JSON blob, non-authoritative) and the
# `GraphOperations` service (expand/trace-back/challenge, which append to the
# graph but keep no audit trail). Neither can represent *authoritative human
# review* of individual nodes and edges, so neither was a safe host for it:
# overloading Scenario would have made human corrections look like hypotheses.
#
# We therefore use the "current-state fields + immutable audit table" strategy
# (option 3 of the three offered): review state lives on `claim` / `causal_edge`
# (cheap reads, no join in the hot graph path, matches the repo's existing
# convention of adding columns to the entity — cf. `is_feedback`,
# `statistical_validation`), and every mutation appends an immutable
# `GraphOperation` row carrying before/after snapshots. `Project.graph_revision`
# is bumped by each operation, which gives us:
#   * undo/restore              -> replay `before_state` of an operation
#   * reproducible theories     -> a theory pins the graph_revision it used
#   * theory comparison         -> theory versions keyed by `theory_key`
#   * stale detection           -> theory.graph_revision < project.graph_revision
# --------------------------------------------------------------------------


class GraphOperation(Base):
    """Immutable audit record of a single human review operation on the graph.

    Rows are never updated except to mark them undone, so the table doubles as
    the undo log and the provenance trail for every reasoning element.
    """

    __tablename__ = "graph_operation"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), index=True
    )
    operation_type: Mapped[str] = mapped_column(
        String(40),
        comment="set_review_status, disable, restore, set_note, override_strength, "
                "clear_strength_override, edit_mechanism, reverse_edge",
    )
    target_type: Mapped[str] = mapped_column(String(10), comment="claim or edge")
    claim_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("claim.id", ondelete="CASCADE"), nullable=True
    )
    edge_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causal_edge.id", ondelete="CASCADE"), nullable=True
    )
    before_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    revision_before: Mapped[int] = mapped_column(Integer)
    revision_after: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(
        String(20), default="user", server_default="user", comment="user, ai or system"
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    undone_by_operation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("graph_operation.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TheoryRevision(Base):
    """One theory-generation run for a project.

    Holds the change summary comparing this run against the previous one, plus
    the generation metadata needed to audit what the LLM actually saw.
    """

    __tablename__ = "theory_revision"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer, comment="1-based, per project")
    graph_revision: Mapped[int] = mapped_column(Integer)
    generation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), default=uuid.uuid4)
    trigger: Mapped[str] = mapped_column(
        String(20), default="generate", comment="generate or regenerate"
    )
    change_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    generation_metadata: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="provider/model, snapshot sizes, "
                "validation outcome. Never contains prompts or secrets.",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Theory(Base):
    """A decision-relevant causal explanation derived from the reviewed graph.

    Theories are versioned: `theory_key` is stable across regenerations while
    `id` identifies one concrete version. Only one version per key has
    ``is_current = True``.
    """

    __tablename__ = "theory"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), index=True
    )
    theory_key: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), default=uuid.uuid4, index=True,
        comment="Stable identity across versions; used for change comparison.",
    )
    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(30), default="hypothesis",
        comment="hypothesis, supported, contested, insufficient_evidence, superseded",
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.5, comment="0.0 to 1.0")
    business_impact: Mapped[str] = mapped_column(
        String(20), default="medium", comment="low, medium, high, critical"
    )
    recommendation: Mapped[str] = mapped_column(Text, default="")
    weak_assumptions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    connected_links: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0",
        comment="Edges in the causal chain whose endpoints match their "
                "neighbours. Kept beside cited_links rather than folded into "
                "the score: weighting chain integrity inside adjusted_score "
                "would be another uncalibrated constant, and a reader shown "
                "'1 of 3 links verified' can judge for themselves.",
    )
    cited_links: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0",
        comment="Edges the model placed in the chain, connected or not.",
    )
    causal_chain: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="Ordered narrative chain: [{claim_id,label} | {edge_id,source_claim_id,target_claim_id}]",
    )

    graph_revision: Mapped[int] = mapped_column(Integer)
    theory_revision: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    stale_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    change_kind: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="new, changed, unchanged or superseded"
    )
    change_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("theory.id", ondelete="SET NULL"), nullable=True
    )
    generation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # --- Adversarial review (see TheoryObjection) ---
    objection_load: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0",
        comment="Mean severity of live objections, 0-1. Discounts adjusted_score, "
                "so a critique that finds nothing costs nothing and one that "
                "lands does.",
    )
    contested: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false",
        comment="True when objection_load crosses the threshold. Sortable and "
                "filterable, so a contested theory cannot quietly top the list.",
    )
    outside_view_delta: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        comment="confidence minus the base rate of the matching reference class. "
                "Positive means this theory is more optimistic than the user's own "
                "experience of comparable cases -- the classic inside-view error.",
    )
    outside_view_note: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Which reference class was matched, and why."
    )
    outside_view_case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reference_case.id", ondelete="SET NULL"),
        nullable=True, comment="The reference case this theory was matched to.",
    )
    outside_view_polarity: Mapped[str | None] = mapped_column(
        String(10), nullable=True,
        comment="same: the theory predicts the reference case's outcome; "
                "opposite: it predicts that outcome does not happen.",
    )
    adjusted_score: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        comment="confidence discounted by objection_load. This is what the panel "
                "orders by; raw confidence remains visible.",
    )
    # --- Theory of value (see reasoning/theory_value.py) ---
    option_key: Mapped[str | None] = mapped_column(
        String(10), nullable=True,
        comment="The anchor option this is a theory of (O1..), or null when it "
                "explains the situation rather than a choice.",
    )
    predicted_effect: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="achieves or threatens: what the chain predicts for the outcome "
                "under that option.",
    )
    outcome_keys: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="Anchor outcome keys (Y1..) the theory bears on.",
    )
    reaches_outcome: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false",
        comment="Whether the validated causal chain contains an outcome node. "
                "Computed from the graph, never taken from the model.",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    claim_links: Mapped[list["TheoryClaim"]] = relationship(
        back_populates="theory", cascade="all, delete-orphan"
    )
    #: Loaded with the theory so the comparison can be recomputed against the
    #: decider's current conviction (reasoning/outside_view.current_comparison).
    outside_view_case: Mapped["ReferenceCase | None"] = relationship(lazy="selectin")
    edge_links: Mapped[list["TheoryEdge"]] = relationship(
        back_populates="theory", cascade="all, delete-orphan"
    )
    evidence_links: Mapped[list["TheoryEvidence"]] = relationship(
        back_populates="theory", cascade="all, delete-orphan"
    )


class TheoryClaim(Base):
    """Normalized theory -> claim provenance link."""

    __tablename__ = "theory_claim"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    theory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("theory.id", ondelete="CASCADE"), index=True
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("claim.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20), default="supporting")
    position: Mapped[int] = mapped_column(Integer, default=0)

    theory: Mapped["Theory"] = relationship(back_populates="claim_links")


class TheoryEdge(Base):
    """Normalized theory -> causal edge provenance link."""

    __tablename__ = "theory_edge"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    theory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("theory.id", ondelete="CASCADE"), index=True
    )
    edge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causal_edge.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20), default="supporting")
    position: Mapped[int] = mapped_column(Integer, default=0)

    theory: Mapped["Theory"] = relationship(back_populates="edge_links")


class TheoryEvidence(Base):
    """Normalized theory -> evidence link, split by supporting/contradicting."""

    __tablename__ = "theory_evidence"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    theory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("theory.id", ondelete="CASCADE"), index=True
    )
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(
        String(20), default="supporting", comment="supporting or contradicting"
    )

    theory: Mapped["Theory"] = relationship(back_populates="evidence_links")










class TheoryTripwire(Base):
    """An observation that would confirm or falsify a theory, agreed in advance.

    Strategic decisions cannot be tested by experiment, so the nearest available
    discipline is committing beforehand to what would change your mind — and
    then actually looking. A theory with no tripwire is an assertion about an
    unknowable future; a theory with one is a bet that can be lost.
    """

    __tablename__ = "theory_tripwire"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    theory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("theory.id", ondelete="CASCADE"), index=True
    )
    observable: Mapped[str] = mapped_column(
        Text, comment="A concrete, checkable observation -- not a feeling or a trend."
    )
    direction: Mapped[str] = mapped_column(
        String(20), default="falsifies",
        comment="falsifies or confirms: which way this observation cuts.",
    )
    horizon_days: Mapped[int] = mapped_column(
        Integer, default=90, comment="Within how many days this should be observable."
    )
    check_by: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Concrete date derived from the horizon."
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending",
        comment="pending, observed, not_observed or expired",
    )
    decisiveness: Mapped[str | None] = mapped_column(
        String(10), nullable=True,
        comment="weak, moderate or decisive: how much the decider said in advance "
                "this observation would count. Null reads as moderate.",
    )
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observed_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TheoryBelief(Base):
    """The user's conviction in a theory: a stated prior, then evidence.

    Conviction is the decider's own degree of belief, kept apart from the
    model's confidence. It moves only through things observed in the world —
    a tripwire, a field experiment, a tested link — each entered as a
    likelihood ratio, so the arithmetic is Bayes' rule in odds form and the
    history can be replayed. Never moved by a simulated experiment.

    Keyed by ``theory_key``: a conviction is about the theory, and survives the
    theory being regenerated into a new row.
    """

    __tablename__ = "theory_belief"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE")
    )
    theory_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(20), comment="prior or evidence")
    value: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="The stated probability, for a prior."
    )
    likelihood_ratio: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        comment="P(observation | theory true) / P(observation | theory false), "
                "for evidence.",
    )
    source: Mapped[str] = mapped_column(
        String(30), comment="elicited, tripwire, field_experiment or link_hypothesis"
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    method: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="lottery or direct, for a prior."
    )
    event: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
        comment="The real-world event this observation came from. Observations "
                "sharing an event count once: see theory_value.replay.",
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LinkHypothesis(Base):
    """A falsifiable hypothesis about one causal link in a theory's chain.

    Links are ranked by value of information — how much the outcome's belief
    depends on the link, times how unsure the graph is about it — so the test
    proposed first is the one that would tell the most.
    """

    __tablename__ = "link_hypothesis"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE")
    )
    theory_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    theory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("theory.id", ondelete="SET NULL"), nullable=True
    )
    edge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causal_edge.id", ondelete="CASCADE")
    )
    statement: Mapped[str] = mapped_column(Text)
    refuted_if: Mapped[str] = mapped_column(Text, comment="What would prove the link wrong.")
    cheapest_test: Mapped[str] = mapped_column(Text, default="", server_default="")
    priority: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    leverage: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    uncertainty: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    status: Mapped[str] = mapped_column(
        String(20), default="open", server_default="open",
        comment="open, held, refuted or inconclusive",
    )
    decisiveness: Mapped[str | None] = mapped_column(
        String(10), nullable=True,
        comment="weak, moderate or decisive, stated before the test. Null reads as moderate.",
    )
    observed_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TheoryObjection(Base):
    """An adversarial critique of a theory, written without seeing its case-for.

    Kept separate from ``Theory.weak_assumptions`` on purpose: those are written
    by the call that is arguing *for* the theory, which is self-critique from
    counsel for the defence. These come from a call briefed to demolish it.
    """

    __tablename__ = "theory_objection"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    theory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("theory.id", ondelete="CASCADE"), index=True
    )
    objection: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(
        String(30), default="other",
        comment="common_cause, single_source, reversal, scope, timing, "
                "incentive or other",
    )
    severity: Mapped[float] = mapped_column(
        Float, default=0.5,
        comment="0-1. Feeds Theory.objection_load, which discounts the theory's rank.",
    )
    dismissed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false",
        comment="The user judged this objection unfounded; it stops costing rank.",
    )
    pre_connectivity_check: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false",
        comment="Generated before causal chains were checked for connectivity, "
                "so the adversary was shown a chain whose mechanisms did not "
                "describe the graph. Marked rather than deleted or regenerated: "
                "the objection may still be sound, deleting destroys work, and "
                "its provenance is what a reader needs in order to weigh it.",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReferenceCase(Base):
    """A base rate extracted from the user's own experience of similar decisions.

    The outside view: a one-off strategic decision has no statistics of its own,
    but the decider has usually seen the same *kind* of decision before. "The
    last two integrations both slipped a quarter" is a base rate of 2/2, and it
    is the only empirical anchor available. Kahneman's finding is that people
    reliably ignore it in favour of the inside view -- the specifics of this
    case, which always feel exceptional.

    Stored separately from the free-text answer so the numbers can be compared
    against generated confidences rather than merely sitting in a prompt.
    """

    __tablename__ = "reference_case"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), index=True
    )
    outcome: Mapped[str] = mapped_column(
        Text, comment="The outcome whose frequency this records, e.g. 'the schedule slipped'."
    )
    cases_total: Mapped[int] = mapped_column(Integer, comment="Comparable cases recalled.")
    cases_with_outcome: Mapped[int] = mapped_column(
        Integer, comment="How many of them produced the outcome."
    )
    base_rate: Mapped[float] = mapped_column(
        Float, comment="cases_with_outcome / cases_total, 0-1."
    )
    basis: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="The user's own words this was derived from."
    )
    source: Mapped[str] = mapped_column(
        String(20), default="user_recall",
        comment="user_recall or documented. Recall is weaker but is what exists.",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --------------------------------------------------------------------------
# Synthetic experiments
#
# EPISTEMIC NOTE -- read before extending this
# --------------------------------------------------------------------------
# A simulated stakeholder is NOT evidence about the world. It is evidence about
# what a language model predicts a person in that role would say. Treating the
# two as equivalent would be the most dangerous thing in this codebase: it would
# manufacture the appearance of empirical validation for a decision that has
# none, which is precisely the failure mode every other guardrail here exists to
# prevent.
#
# So a synthetic experiment answers a narrower question than "is this theory
# true". It answers "will this survive the room, and what will they object to" --
# which for a decision that must be sold is genuinely decision-relevant, and is
# honest about what it is.
#
# Consequently: an experiment NEVER moves a theory's `confidence`. It surfaces
# objections (which route through the adversarial machinery, where the user can
# judge them) and records anticipated stakeholder positions. The one thing that
# does earn a confidence change is a FIELD experiment -- a real test the user
# actually runs -- and that is recorded separately.
# --------------------------------------------------------------------------


class Experiment(Base):
    """A test of a theory: synthetic (simulated stakeholders) or field (real)."""

    __tablename__ = "experiment"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), index=True
    )
    theory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("theory.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(
        String(20), default="synthetic",
        comment="synthetic (simulated stakeholders, answers 'will this survive the "
                "room') or field (a real test the user runs, answers 'is it true')",
    )
    hypothesis: Mapped[str] = mapped_column(
        Text, comment="The specific, falsifiable statement under test."
    )
    design: Mapped[str] = mapped_column(
        Text, default="", comment="What is presented, to whom, and what counts as a result."
    )
    #: Field experiments only: what to measure, cost, and how long.
    measure: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_estimate: Mapped[str | None] = mapped_column(String(200), nullable=True)
    duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), default="designed",
        comment="designed, executed or abandoned",
    )
    #: Synthetic results: how the simulated room split.
    support_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    oppose_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    neutral_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    personas: Mapped[list["ExperimentPersona"]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )
    responses: Mapped[list["ExperimentResponse"]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )


class ExperimentPersona(Base):
    """A stakeholder whose reaction is simulated.

    Grounded in the decision frame where possible: the user has already said who
    must be convinced and what they believe. Inventing personas from nothing
    would simulate a room that does not exist.
    """

    __tablename__ = "experiment_persona"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("experiment.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), comment="Role label, not a real person.")
    role: Mapped[str] = mapped_column(Text)
    stake: Mapped[str] = mapped_column(
        Text, comment="What this person gains or loses by the decision going either way."
    )
    prior_position: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="What they are believed to think already."
    )
    grounded_in_frame: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false",
        comment="True when derived from the user's stated audience rather than invented.",
    )

    experiment: Mapped["Experiment"] = relationship(back_populates="personas")


class ExperimentResponse(Base):
    """One simulated stakeholder's reaction."""

    __tablename__ = "experiment_response"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("experiment.id", ondelete="CASCADE"), index=True
    )
    persona_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("experiment_persona.id", ondelete="CASCADE")
    )
    verdict: Mapped[str] = mapped_column(
        String(20), comment="supports, opposes or neutral"
    )
    reaction: Mapped[str] = mapped_column(Text)
    key_objection: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="The single thing this stakeholder would push back on. Promoted "
                "into a TheoryObjection when it is substantive.",
    )
    would_need: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="What would change this stakeholder's mind."
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    experiment: Mapped["Experiment"] = relationship(back_populates="responses")


class TheoryDebate(Base):
    """A structural comparison of two theories, plus what would separate them.

    NOT a transcript. There is deliberately no field for one: two agents arguing
    are the same model twice, so the exchange measures which side got the better
    prompt rather than which theory holds. What is decision-relevant is narrower
    and harder — where exactly they part company, and what observation would
    resolve it.

    The structural fields are computed from the normalized theory links, not
    generated: overlap is a fact about the graph, and a model asked to estimate
    it could get it wrong. Only `crux`, `discriminator` and `evidence_favours`
    come from the model, and when `relation` is `same_story` the model is not
    called at all.
    """

    __tablename__ = "theory_debate"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), index=True
    )
    theory_a_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("theory.id", ondelete="CASCADE"), index=True
    )
    theory_b_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("theory.id", ondelete="CASCADE"), index=True
    )

    # --- Computed, not generated ---
    overlap_jaccard: Mapped[float] = mapped_column(
        Float, comment="Jaccard overlap of the two supporting edge sets, 0-1."
    )
    relation: Mapped[str] = mapped_column(
        String(20),
        comment="same_story (one theory, two wordings), competing (real "
                "disagreement) or orthogonal (different things, both may hold)",
    )
    shared_claim_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    shared_edge_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    divergent_claim_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    divergent_edge_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # --- Generated ---
    crux: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Where exactly the two chains part company."
    )
    discriminator: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="An observation whose outcome differs depending on which theory "
                "holds. Already in tripwire shape.",
    )
    discriminator_feasible: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false",
        comment="False means the distinction cannot be resolved before the "
                "decision is due -- which is itself a finding: pick the option "
                "that survives both.",
    )
    discriminator_horizon_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_favours: Mapped[str | None] = mapped_column(
        String(10), nullable=True, comment="a, b or neither"
    )
    both_possible: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false",
        comment="The two are not mutually exclusive. A ranked list hides this, "
                "and if both hold the risk exceeds either one alone.",
    )

    graph_revision: Mapped[int] = mapped_column(Integer, default=1)
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    promoted_tripwire_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="When the discriminator was turned into a tripwire on both theories.",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Document(Base):
    """An uploaded source document, kept rather than consumed.

    Previously an upload was extracted straight into the prompt box: the text
    replaced whatever the user had typed, the file itself was discarded, and a
    hundred-page PDF became a wall of characters in a textarea. Three things
    were lost with it — the ability to upload more than one file, any record of
    which document a claim came from, and the original bytes, so re-extracting
    with a better parser meant asking the user to find the file again.

    Documents are stored first and read second. Extraction failures are recorded
    on the row (``extraction_error``) instead of rejecting the upload, because a
    file that cannot be parsed today is still the file the user meant to use.
    """

    __tablename__ = "document"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"),
        nullable=True, index=True,
        comment="Null until analysis starts: a document is uploaded before the "
                "project it will belong to exists.",
    )
    filename: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    extracted_text: Mapped[str] = mapped_column(
        Text, default="", comment="Text pulled out of the file, or empty on failure."
    )
    extraction_error: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Why extraction failed. The document is kept either way.",
    )
    #: Original bytes, so a better parser can be run later without asking the
    #: user for the file again. Null for anything large enough that storing it
    #: in a row is the wrong call.
    raw_content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())




class DecisionRecommendation(Base):
    """What to do, weighed across every theory at once.

    The theories are separate explanations. Reading them one after another
    leaves the reader to do the synthesis themselves — which is the hard part
    and the one they came for. Two theories can point the same way, or opposite
    ways, or be about different things, and only after weighing all of them can
    anyone say what to actually do.

    One row per project, replaced on regeneration: a recommendation is about the
    current set of theories, and keeping older ones would invite reading advice
    derived from explanations that no longer exist.
    """

    __tablename__ = "decision_recommendation"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"),
        unique=True, index=True,
    )
    recommendation: Mapped[str] = mapped_column(Text)
    reasoning: Mapped[str] = mapped_column(Text, default="")
    depends_on: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="What would have to be true for this to be right."
    )
    against_it: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="The strongest case for doing something else. Kept beside the "
                "recommendation rather than below it: an argument nobody has "
                "attacked has not been tested.",
    )
    next_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str] = mapped_column(
        String(20), default="moderate",
        comment="low, moderate or high. 'low' is a legitimate answer — a hedge "
                "stated clearly beats confidence that is not warranted.",
    )
    #: Theories this was derived from. A recommendation whose theories have been
    #: regenerated is describing a set that no longer exists.
    theory_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    graph_revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalysisUsage(Base):
    """What one analysis cost, in tokens and in money.

    Kept per project rather than aggregated, because the question people
    actually ask is "why was *that* one expensive" — and answering it needs the
    per-stage breakdown, not a running total.

    Costs are computed from a hard-coded price table and are advisory: they make
    one run comparable to another, and will not reconcile with an invoice.
    ``price_table_date`` records when the prices were last checked so a stale
    figure is visible rather than silently wrong. Token counts come from the
    provider's own usage field and are exact.
    """

    __tablename__ = "analysis_usage"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"),
        index=True,
    )
    calls: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    #: Calls whose model had no price entry. A gap made visible, so an unpriced
    #: model does not read as a suspiciously cheap run.
    unpriced_calls: Mapped[int] = mapped_column(Integer, default=0)
    price_table_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    by_stage: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="Per-stage calls, tokens and cost."
    )
    #: One row per run, not per project: re-running after a failure is a real
    #: second cost and hiding it would understate what a project consumed.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IntakeQuestion(Base):
    """A question asked about the material before any of it was analysed.

    Three earlier question systems were built here and all three removed
    (migration 016). Each stood between the user and the analysis: the framing
    form blocked theory generation, and the first intake paused a twenty-minute
    run halfway through. This one runs *before* the pipeline starts, so there is
    nothing to pause and nothing to block — and it holds one table where the
    three of them held six.

    An unanswered question is not an error state. It is omitted when the answers
    are rendered, which is what lets the screen be skipped entirely without
    leaving a hole in the context the model reads.
    """

    __tablename__ = "intake_question"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(
        Integer, default=0,
        comment="Display order. Authority questions sort first, so truncation "
                "to the cap drops the least useful rather than the last.",
    )
    kind: Mapped[str] = mapped_column(
        String(20), comment="authority, ambiguity, scope, absence or frame."
    )
    question: Mapped[str] = mapped_column(Text)
    quoted_source: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="The sentence the question is about, verbatim from the input. "
                "Dropped when it does not literally appear there: a quotation "
                "the user cannot find in their own document is worse than none.",
    )
    rationale: Mapped[str] = mapped_column(
        Text, default="", comment="What answering would change."
    )
    options: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="0 to 3 clickable answers. Free text is always available "
                "alongside them, so an empty list is still a usable question.",
    )
    options_rejected: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false",
        comment="Set when generated options were too near-identical to be a "
                "choice. Recorded rather than silently discarded: it is the "
                "signal that the prompt needs work.",
    )

    # --- Answer ---
    answer_choice: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="Index into options."
    )
    answer_text: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Free text. Takes precedence over a choice."
    )
    answered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
