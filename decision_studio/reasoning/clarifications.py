# DEAD-CODE-CANDIDATE DC-05 [module]: clarification-question system removed in migration 016 (HANDOVER 4.9); nothing imports it. See docs/DEAD_CODE_REPORT.md
"""AI clarification questions: generation, lifecycle and application.

A clarification question exists to move a decision, so the service is built
around three guarantees:

* **No repeats.** Questions are deduplicated against everything ever asked in
  the project — by exact fingerprint and by token overlap — before they are
  stored.
* **No silent graph edits.** Answering a question never mutates claims or
  edges. An answer that implies a graph change is surfaced as a *proposal* the
  user applies through the normal review endpoints.
* **Visible consequences.** ``preview_impact`` reports which theories an answer
  would affect before the user commits to it.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from decision_studio.config import settings
from decision_studio.db.models import (
    ClarificationQuestion,
    QuestionClaim,
    QuestionEdge,
    QuestionTheory,
    Theory,
)
from decision_studio.llm.client import LLMClient, get_llm_client
from decision_studio.llm.prompts import language_instruction
from decision_studio.llm.prompts.clarification import CLARIFICATION_SCHEMA, CLARIFICATION_SYSTEM
from decision_studio.reasoning.context_builder import build_generation_context
from decision_studio.reasoning.effective_graph import load_effective_snapshot
from decision_studio.reasoning.theories import list_current_theories, mark_stale_if_answers_changed
from decision_studio.reasoning.validation import (
    QUESTION_STATUSES,
    is_duplicate_question,
    validate_answer,
    validate_questions,
)

logger = logging.getLogger(__name__)

PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
GAIN_RANK = {"high": 0, "medium": 1, "low": 2}


class ClarificationError(ValueError):
    """Raised when a clarification request is invalid."""


@dataclass
class ClarificationGenerationResult:
    """Questions created by one generation run, plus what was suppressed."""

    questions: list[ClarificationQuestion]
    validation: dict[str, Any] = field(default_factory=dict)
    duplicates_suppressed: int = 0


def _question_options() -> list[Any]:
    return [
        selectinload(ClarificationQuestion.theory_links),
        selectinload(ClarificationQuestion.claim_links),
        selectinload(ClarificationQuestion.edge_links),
    ]


async def list_questions(
    session: AsyncSession,
    project_id: UUID,
    *,
    statuses: tuple[str, ...] | None = None,
) -> list[ClarificationQuestion]:
    """Questions for a project, most decision-relevant first."""
    stmt = (
        select(ClarificationQuestion)
        .where(ClarificationQuestion.project_id == project_id)
        .options(*_question_options())
    )
    if statuses:
        stmt = stmt.where(ClarificationQuestion.status.in_(statuses))
    result = await session.execute(stmt)
    questions = list(result.scalars().all())
    questions.sort(
        key=lambda q: (
            0 if q.status == "open" else 1,
            PRIORITY_RANK.get(q.priority, 4),
            GAIN_RANK.get(q.expected_information_gain, 3),
        )
    )
    return questions


async def get_question(
    session: AsyncSession, project_id: UUID, question_id: UUID
) -> ClarificationQuestion | None:
    """Fetch one question, verifying project ownership."""
    result = await session.execute(
        select(ClarificationQuestion)
        .where(
            ClarificationQuestion.id == question_id,
            ClarificationQuestion.project_id == project_id,
        )
        .options(*_question_options())
    )
    return result.scalars().first()


async def generate_questions(
    session: AsyncSession,
    project_id: UUID,
    *,
    llm: LLMClient | None = None,
) -> ClarificationGenerationResult:
    """Ask the model what it still needs to know.

    Raises:
        LookupError: unknown project.
        ClarificationError: the graph is empty.
    """
    snapshot = await load_effective_snapshot(project_id, session)
    if snapshot.is_empty:
        raise ClarificationError(
            "The reviewed graph has no active claims to ask questions about."
        )

    theories = await list_current_theories(session, project_id)
    existing = await list_questions(session, project_id)
    answered = [q for q in existing if q.status == "answered"]
    unanswered = [q for q in existing if q.status != "answered"]

    context = build_generation_context(
        snapshot,
        clarification_answers=answered,
        previous_theories=theories,
        open_questions=unanswered,
        purpose="clarifications",
    )
    user_prompt = context.user_prompt + language_instruction(context.language_sample)

    generation_id = uuid.uuid4()
    logger.info(
        "Clarification generation %s: project=%s graph_revision=%s theories=%d "
        "provider=%s model=%s",
        generation_id,
        project_id,
        snapshot.graph_revision,
        len(theories),
        settings.llm_provider,
        settings.llm_model,
    )

    # Cache disabled for the same reason as theory generation: a near-identical
    # prompt on a changed graph must not return the previous answer set.
    client = llm or get_llm_client(enable_cache=False)
    payload = await client.complete_json(
        system=CLARIFICATION_SYSTEM,
        user=user_prompt,
        schema=CLARIFICATION_SCHEMA,
        max_tokens=4096,
        temperature=0.4,
    )

    known_keys = {str(t.theory_key) for t in theories}
    candidates, report = validate_questions(
        payload,
        context.refs,
        snapshot,
        existing_questions=[q.question for q in existing],
        known_theory_keys=known_keys,
    )
    logger.info(
        "Clarification generation %s validation: accepted=%d dropped=%d unknown_refs=%d",
        generation_id,
        report.accepted,
        len(report.dropped),
        len(set(report.unknown_refs)),
    )

    existing_fingerprints = {q.fingerprint for q in existing}
    existing_texts = [q.question for q in existing]
    theory_by_key = {str(t.theory_key): t for t in theories}

    created: list[ClarificationQuestion] = []
    suppressed = 0
    for candidate in candidates:
        # Belt and braces: the validator already deduplicated within the batch,
        # this catches collisions against questions stored earlier.
        if candidate.fingerprint in existing_fingerprints or is_duplicate_question(
            candidate.question, existing_texts
        ):
            suppressed += 1
            continue

        question = ClarificationQuestion(
            project_id=project_id,
            question=candidate.question,
            reason=candidate.reason,
            expected_information_gain=candidate.expected_information_gain,
            priority=candidate.priority,
            answer_type=candidate.answer_type,
            options=candidate.options or None,
            status="open",
            fingerprint=candidate.fingerprint,
            graph_revision=snapshot.graph_revision,
            generation_id=generation_id,
        )
        session.add(question)
        question.claim_links = [
            QuestionClaim(claim_id=uuid.UUID(cid)) for cid in candidate.linked_claim_ids
        ]
        question.edge_links = [
            QuestionEdge(edge_id=uuid.UUID(eid)) for eid in candidate.linked_edge_ids
        ]
        question.theory_links = [
            QuestionTheory(
                theory_id=theory_by_key[key].id,
                theory_key=theory_by_key[key].theory_key,
            )
            for key in candidate.linked_theory_keys
            if key in theory_by_key
        ]
        created.append(question)
        existing_fingerprints.add(candidate.fingerprint)
        existing_texts.append(candidate.question)

    await session.commit()

    # Re-load with links eagerly attached. refresh() would expire the
    # relationship collections, and the API serializes them immediately —
    # a lazy load at that point is an N+1 outside the async context.
    created_ids = [question.id for question in created]
    if created_ids:
        reloaded = await session.execute(
            select(ClarificationQuestion)
            .where(ClarificationQuestion.id.in_(created_ids))
            .options(*_question_options())
        )
        by_id = {question.id: question for question in reloaded.scalars().all()}
        created = [by_id[qid] for qid in created_ids if qid in by_id]

    return ClarificationGenerationResult(
        questions=created,
        validation=report.as_dict(),
        duplicates_suppressed=suppressed,
    )


async def preview_impact(
    session: AsyncSession, project_id: UUID, question_id: UUID
) -> list[Theory]:
    """Theories that answering this question would put in question.

    Shown before the answer is saved, so the user can see the blast radius.
    """
    question = await get_question(session, project_id, question_id)
    if question is None:
        raise LookupError(f"Question {question_id} not found in project")

    keys = {str(link.theory_key) for link in question.theory_links}
    if not keys:
        return []
    theories = await list_current_theories(session, project_id)
    return [t for t in theories if str(t.theory_key) in keys]


async def answer_question(
    session: AsyncSession,
    project_id: UUID,
    question_id: UUID,
    value: Any,
    *,
    note: str | None = None,
) -> tuple[ClarificationQuestion, list[Theory]]:
    """Record an answer and report which theories it makes stale.

    The graph itself is never touched here. If the answer implies the graph is
    wrong, the user makes that edit explicitly through the review endpoints.

    Raises:
        LookupError: unknown question.
        ClarificationError: the answer does not fit the declared answer type.
    """
    question = await get_question(session, project_id, question_id)
    if question is None:
        raise LookupError(f"Question {question_id} not found in project")

    try:
        coerced = validate_answer(question.answer_type, value, question.options or [])
    except ValueError as exc:
        raise ClarificationError(str(exc)) from exc

    affected = await preview_impact(session, project_id, question_id)

    question.answer = {"value": coerced}
    question.answer_note = (note or "").strip() or None
    question.status = "answered"
    question.answered_at = datetime.now(timezone.utc)
    question.dismissed_at = None

    await mark_stale_if_answers_changed(
        session,
        project_id,
        reason="A clarification question was answered after these theories were generated",
    )

    await session.commit()
    refreshed = await get_question(session, project_id, question_id)
    return refreshed or question, affected


async def set_status(
    session: AsyncSession,
    project_id: UUID,
    question_id: UUID,
    status: str,
) -> ClarificationQuestion:
    """Dismiss, skip or reopen a question.

    Raises:
        LookupError: unknown question.
        ClarificationError: unsupported status transition.
    """
    if status not in QUESTION_STATUSES:
        raise ClarificationError(
            f"Unknown status '{status}'. Expected one of: " + ", ".join(QUESTION_STATUSES)
        )
    question = await get_question(session, project_id, question_id)
    if question is None:
        raise LookupError(f"Question {question_id} not found in project")

    if status == "answered" and not question.answer:
        raise ClarificationError(
            "Use the answer endpoint to answer a question; status alone is not enough"
        )

    now = datetime.now(timezone.utc)
    question.status = status
    if status == "dismissed":
        question.dismissed_at = now
    elif status == "open":
        # Reopening clears the previous verdict but keeps the recorded answer
        # visible for provenance.
        question.dismissed_at = None
    question.updated_at = now

    await session.commit()
    return await get_question(session, project_id, question_id) or question


async def apply_answers(
    session: AsyncSession, project_id: UUID
) -> dict[str, Any]:
    """Accept every answered question into the reasoning context.

    Marks answers as applied and reports any that read like a request to change
    the graph, so the UI can offer those as explicit review actions rather than
    editing anything on the user's behalf.
    """
    result = await session.execute(
        select(ClarificationQuestion)
        .where(
            ClarificationQuestion.project_id == project_id,
            ClarificationQuestion.status == "answered",
        )
        .options(*_question_options())
    )
    answered = list(result.scalars().all())

    now = datetime.now(timezone.utc)
    applied: list[str] = []
    proposals: list[dict[str, Any]] = []

    for question in answered:
        if question.applied_at is None:
            question.applied_at = now
            applied.append(str(question.id))
        proposals.extend(_graph_change_proposals(question))

    if applied:
        await mark_stale_if_answers_changed(
            session,
            project_id,
            reason="Clarification answers were applied after these theories were generated",
        )

    await session.commit()

    return {
        "applied_question_ids": applied,
        "answered_count": len(answered),
        "proposed_graph_changes": proposals,
    }


_NEGATION_MARKERS = (
    "not true",
    "incorrect",
    "wrong",
    "no longer",
    "isn't",
    "is not",
    "false",
    "不正确",
    "错误",
    "不成立",
)


def _graph_change_proposals(question: ClarificationQuestion) -> list[dict[str, Any]]:
    """Surface graph edits an answer *suggests*, without performing any.

    This is intentionally conservative: it only proposes reviewing the elements
    the question was already linked to, and never invents new ones.
    """
    payload = question.answer or {}
    value = payload.get("value") if isinstance(payload, dict) else payload
    text = " ".join(
        part
        for part in (
            str(value) if not isinstance(value, list) else " ".join(str(v) for v in value),
            question.answer_note or "",
        )
        if part
    ).lower()

    if value is False or any(marker in text for marker in _NEGATION_MARKERS):
        proposals: list[dict[str, Any]] = []
        for link in question.edge_links:
            proposals.append(
                {
                    "target_type": "edge",
                    "target_id": str(link.edge_id),
                    "suggested_review_status": "uncertain",
                    "rationale": (
                        f'The answer to "{question.question}" appears to contradict '
                        "this causal link. Review it before regenerating."
                    ),
                    "question_id": str(question.id),
                }
            )
        for link in question.claim_links:
            proposals.append(
                {
                    "target_type": "claim",
                    "target_id": str(link.claim_id),
                    "suggested_review_status": "uncertain",
                    "rationale": (
                        f'The answer to "{question.question}" appears to contradict '
                        "this claim. Review it before regenerating."
                    ),
                    "question_id": str(question.id),
                }
            )
        return proposals
    return []
