"""Pydantic schemas for scenario endpoints."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from decision_studio.api.models.graph import GraphResponse


class ForkRequest(BaseModel):
    """Request body for forking a new scenario from a project."""

    project_id: UUID
    name: str
    description: str | None = None
    edge_overrides: dict[str, float] = {}  # {edge_id: new_strength}
    injected_events: list[str] = []


class ScenarioResponse(BaseModel):
    """A scenario record."""

    id: UUID
    project_id: UUID
    name: str
    description: str | None = None
    parent_scenario_id: UUID | None = None
    narrative: str | None = None
    key_insights: list[str] = []
    conclusion: str | None = None
    edge_change_reasons: list[dict] = []


class ScenarioListResponse(BaseModel):
    """Response for listing scenarios of a project."""

    scenarios: list[ScenarioResponse]


class ForkWithGraphResponse(BaseModel):
    """Fork response including the computed scenario graph."""

    scenario: ScenarioResponse
    graph: GraphResponse
    narrative: str | None = None
    key_insights: list[str] = []
    conclusion: str | None = None
    edge_change_reasons: list[dict] = []


class ReportItem(BaseModel):
    """A scenario report with its project context."""

    id: UUID
    project_id: UUID
    project_title: str
    name: str
    description: str | None = None
    narrative: str | None = None
    key_insights: list[str] = []
    conclusion: str | None = None
    edge_change_reasons: list[dict] = []
    created_at: str | None = None


class ReportsListResponse(BaseModel):
    """Response for listing all scenario reports."""

    reports: list[ReportItem]


class NodeDivergenceStability(BaseModel):
    """Whether a node's divergence survives noise on the inputs."""

    node_id: UUID
    belief_a: float
    belief_b: float
    delta: float
    agreement: float = Field(
        ..., description="Share of simulations where the difference kept its sign."
    )
    material_rate: float = Field(
        ..., description="Share of simulations where the difference stayed material."
    )
    robust: bool = Field(
        ..., description="False means this divergence is an artefact of input noise."
    )


class ScenarioComparison(BaseModel):
    """Result of comparing two scenarios."""

    scenario_a: GraphResponse
    scenario_b: GraphResponse
    divergent_nodes: list[UUID]
    convergent_nodes: list[UUID]
    stability: list[NodeDivergenceStability] = Field(
        default_factory=list,
        description="Per-node robustness of the divergence under perturbed inputs.",
    )
    robust_divergent_nodes: list[UUID] = Field(
        default_factory=list,
        description="Divergent nodes whose difference survived the simulation. "
                    "Reporting the difference between the two lists is the honest "
                    "way to present a comparison.",
    )
    simulation_runs: int = 0
