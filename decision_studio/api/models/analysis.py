"""Pydantic schemas for analysis endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    """Request body for starting a new causal analysis."""

    title: str = Field(..., min_length=1, max_length=500)
    text: str = Field("", description="Typed context. May be empty when documents are attached.")
    document_ids: list[UUID] = Field(
        default_factory=list,
        description="Uploaded documents to analyse. Their extracted text is "
                    "combined with `text`, in upload order.",
    )
    decision_objective: str = Field(
        "",
        max_length=2000,
        description="What is being decided, in one sentence. Optional, but "
                    "everything downstream of the graph reads it: without one, "
                    "theories describe the situation rather than bearing on a "
                    "choice, and the recommendation has no question to answer. "
                    "Can also be set later via PATCH /decision-objective.",
    )


class AnalyzeFileResponse(BaseModel):
    """An uploaded document, kept rather than consumed.

    `text` is a short preview, not the whole document: the full text stays on
    the server and is read when analysis starts. Returning all of it was how a
    hundred-page PDF ended up as a wall of characters in a textarea.
    """

    document_id: UUID
    title: str
    filename: str
    size_bytes: int
    char_count: int
    text: str = Field("", description="First few hundred characters, for display only.")
    extraction_error: str | None = None


class AnalyzeResponse(BaseModel):
    """Response returned when an analysis is kicked off."""

    project_id: UUID
    status: str


class PipelineStageStatus(BaseModel):
    """Status of an individual pipeline stage."""

    stage: str
    status: str  # started, progress, completed, error
    progress: float = 0.0
    data: dict | None = None
    timestamp: datetime


class ProjectSummary(BaseModel):
    """Lightweight project summary for list views."""

    id: UUID
    title: str
    status: str
    created_at: datetime


class ProjectListResponse(BaseModel):
    """Response for listing all projects."""

    projects: list[ProjectSummary]


class ProjectStatus(BaseModel):
    """Full project status with per-stage breakdown."""

    project_id: UUID
    title: str
    status: str
    created_at: datetime
    stages: list[PipelineStageStatus] = []
    claim_count: int = 0
