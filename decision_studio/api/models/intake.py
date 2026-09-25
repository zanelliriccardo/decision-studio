"""Request and response shapes for the intake step."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class IntakeCreateRequest(BaseModel):
    """Same shape as an analyse request — the two paths start from one form."""

    title: str = Field(..., min_length=1, max_length=500)
    text: str = ""
    document_ids: list[UUID] = Field(default_factory=list)
    decision_objective: str = Field("", max_length=2000)


class IntakeResponse(BaseModel):
    """Returned the moment the project exists.

    Deliberately returned *before* any question has been generated. The client
    needs an id during the seconds the model spends reading, because that is
    exactly when the user may press "start anyway" — and without an id that
    button either waits for the reading to finish, cancelling itself, or opens a
    second project and abandons the first.
    """

    project_id: UUID
    status: Literal["awaiting_questions", "ready"] = "awaiting_questions"


class IntakeQuestionResponse(BaseModel):
    id: UUID
    kind: Literal["authority", "ambiguity", "scope", "absence", "frame"]
    question: str
    quoted_source: str | None = None
    rationale: str = ""
    options: list[str] = []
    answer_choice: int | None = None
    answer_text: str | None = None


class IntakeQuestionsResponse(BaseModel):
    """The questions, and whether the material produced any.

    An empty list is a correct outcome rather than a failure, so the client
    treats it as "nothing to ask" and forwards to the analysis.
    """

    project_id: UUID
    questions: list[IntakeQuestionResponse] = []


class IntakeAnswer(BaseModel):
    question_id: UUID
    #: Free text takes precedence: someone who typed after clicking has said
    #: something the options did not cover.
    text: str = ""
    choice: int | None = None


class IntakeStartRequest(BaseModel):
    """Answers, then start. An empty list means "start without answering"."""

    answers: list[IntakeAnswer] = Field(default_factory=list)
    #: The decision anchor as the user left it on the intake screen. Absent
    #: when they did not touch it — the pipeline then uses the stored draft, or
    #: drafts one itself.
    decision_anchor: dict | None = None
