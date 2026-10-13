# DEAD-CODE-CANDIDATE DC-07 [module]: first intake system (paused the pipeline), replaced by reasoning/intake.py; nothing imports it. See docs/DEAD_CODE_REPORT.md
"""Asking about ambiguity before the causal graph is built.

The pipeline pauses here rather than after it finishes. The reason is cost
asymmetry: correcting a misread claim before inference means editing one row,
and after inference means re-inferring its links, re-grounding its evidence and
re-propagating every belief downstream of it. The same question is an order of
magnitude cheaper asked now.

**The pipeline does not wait.** It used to, and the argument for waiting was
real: an answer that arrives before causal inference shapes the graph, while one
that arrives afterwards means re-inferring the affected links. But that trades a
cheap correction for an expensive stall — an analysis held open on someone who
has stepped away — and the correction path already exists. Answering an intake
question proposes graph changes through the same machinery as a post-theory
clarification.

Questions are stored as ``ClarificationQuestion`` rows with ``stage='intake'``
so they share the answering, deduplication and lifecycle code with the
post-theory ones. What differs is when they are asked and what they are about.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_studio.db.models import ClarificationQuestion
from decision_studio.llm.client import LLMClient
from decision_studio.llm.prompts import language_instruction
from decision_studio.llm.prompts.intake_questions import (
    INTAKE_QUESTIONS_SCHEMA,
    INTAKE_QUESTIONS_SYSTEM,
)
from decision_studio.reasoning.validation import question_fingerprint

logger = logging.getLogger(__name__)

#: Some range: the ambiguities worth asking about are not always the obvious ones.
TEMPERATURE = 0.4

#: Claims sent to the model. Beyond this the prompt is long and the questions
#: get vaguer, because everything looks ambiguous in bulk.
MAX_CLAIMS = 80

#: Hard cap on questions. Every one of these is a person waiting.
MAX_QUESTIONS = 5

VALID_KINDS = (
    "ambiguous_referent",
    "direction",
    "contradiction",
    "missing_context",
    "scope",
)


async def generate_intake_questions(
    session: AsyncSession,
    project_id: UUID,
    claims: list[dict[str, Any]],
    *,
    llm: LLMClient,
) -> list[ClarificationQuestion]:
    """Ask about ambiguity in the extracted claims.

    Returns the stored questions. An empty list means the documents were clear
    enough to proceed, which is a good outcome rather than a failure — the
    pipeline continues without pausing.
    """
    if len(claims) < 2:
        # One claim cannot be ambiguous relative to anything.
        return []

    try:
        return await _generate(session, project_id, claims, llm=llm)
    except Exception as exc:
        # Nothing here is worth failing a run for: questions improve the graph,
        # and their absence is a worse graph rather than a broken one.
        #
        # The rollback is the important part. An exception mid-transaction —
        # a schema not yet migrated, most likely — leaves the session poisoned,
        # and every later statement in the pipeline then fails with
        # "current transaction is aborted", far from anything that names the
        # cause. Rolling back here means the pipeline continues and reports its
        # own errors rather than this one.
        logger.warning(
            "Intake questions unavailable, continuing without them: %s", exc
        )
        await session.rollback()
        return []


async def _generate(
    session: AsyncSession,
    project_id: UUID,
    claims: list[dict[str, Any]],
    *,
    llm: LLMClient,
) -> list[ClarificationQuestion]:
    """The work, wrapped by the caller so no failure escapes into the pipeline."""
    listed = "\n".join(
        f"[{i}] ({c.get('type', 'CLAIM')}) {c['text']}"
        for i, c in enumerate(claims[:MAX_CLAIMS])
    )
    sample = " ".join(c.get("text", "") for c in claims[:5])

    payload = await llm.complete_json(
        system=INTAKE_QUESTIONS_SYSTEM,
        user=f"CLAIMS EXTRACTED FROM THE DOCUMENTS:\n{listed}\n\n"
             "Ask about anything genuinely ambiguous, or return nothing."
             + language_instruction(sample),
        schema=INTAKE_QUESTIONS_SCHEMA,
        max_tokens=2048,
        temperature=TEMPERATURE,
    )

    existing = {
        row.fingerprint
        for row in (
            await session.execute(
                select(ClarificationQuestion).where(
                    ClarificationQuestion.project_id == project_id
                )
            )
        ).scalars().all()
    }

    generation_id = uuid.uuid4()
    created: list[ClarificationQuestion] = []

    for raw in (payload.get("questions") or [])[:MAX_QUESTIONS]:
        if not isinstance(raw, dict):
            continue
        text = (raw.get("question") or "").strip()
        if not text:
            continue
        fingerprint = question_fingerprint(text)
        if fingerprint in existing:
            continue

        answer_type = raw.get("answer_type", "free_text")
        options = [str(o).strip() for o in (raw.get("options") or []) if str(o).strip()]
        if answer_type == "single_choice" and len(options) < 2:
            # A choice with no choices is unanswerable; degrade rather than
            # invent readings the model did not offer.
            answer_type, options = "free_text", []
        if answer_type != "single_choice":
            options = []

        kind = raw.get("kind")
        reason_parts = [p for p in (
            f'About: "{(raw.get("about_claim") or "").strip()}"'
            if raw.get("about_claim") else "",
            (raw.get("what_changes") or "").strip(),
        ) if p]

        question = ClarificationQuestion(
            project_id=project_id,
            question=text,
            reason=" — ".join(reason_parts),
            # Everything asked here is high gain by construction: the bar for
            # asking at all is that the answer changes the graph's structure.
            expected_information_gain="high",
            priority="high" if kind in ("contradiction", "direction") else "medium",
            answer_type=answer_type,
            options=options or None,
            status="open",
            stage="intake",
            fingerprint=fingerprint,
            graph_revision=1,
            generation_id=generation_id,
        )
        session.add(question)
        created.append(question)
        existing.add(fingerprint)

    await session.commit()
    for question in created:
        await session.refresh(question)

    logger.info(
        "Intake: %d question(s) about ambiguity in %d claims (project %s)",
        len(created), len(claims), project_id,
    )
    return created


async def unanswered_intake_questions(
    session: AsyncSession, project_id: UUID
) -> list[ClarificationQuestion]:
    """Intake questions still open.

    Informational only. The pipeline no longer waits for these: holding an
    expensive run open on a person who may have stepped away costs more than
    correcting the graph afterwards, and the correction path already exists.
    """
    result = await session.execute(
        select(ClarificationQuestion).where(
            ClarificationQuestion.project_id == project_id,
            ClarificationQuestion.stage == "intake",
            ClarificationQuestion.status == "open",
        )
    )
    return list(result.scalars().all())

async def all_intake_questions(
    session: AsyncSession, project_id: UUID
) -> list[ClarificationQuestion]:
    """Every intake question for a project, answered or not."""
    result = await session.execute(
        select(ClarificationQuestion).where(
            ClarificationQuestion.project_id == project_id,
            ClarificationQuestion.stage == "intake",
        )
    )
    return list(result.scalars().all())


def render_intake_answers(questions: list[ClarificationQuestion]) -> str:
    """Answered intake questions, for the causal inference prompt.

    These are the user's own corrections to how their documents were read, so
    they outrank anything the model inferred from the text.
    """
    answered = [q for q in questions if q.status == "answered" and q.answer]
    if not answered:
        return ""

    lines = [
        "# The user clarified these ambiguities (authoritative)",
        "Where this contradicts your reading of a claim, the user is right.",
    ]
    for question in answered:
        payload = question.answer or {}
        value = payload.get("value") if isinstance(payload, dict) else payload
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        lines.append(f"- {question.question}")
        lines.append(f"  -> {value}")
        if question.answer_note:
            lines.append(f"  note: {question.answer_note}")
    return "\n".join(lines) + "\n"
