"""Reading and writing the decision frame."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_studio.db.models import DecisionFrame, DecisionProfile, Project
from decision_studio.llm.client import LLMClient, get_llm_client
from decision_studio.llm.prompts.domain_questions import (
    DOMAIN_QUESTIONS_SCHEMA,
    DOMAIN_QUESTIONS_SYSTEM,
)
from decision_studio.reasoning.domains import (
    DOMAIN_OTHER,
    all_questions,
    is_valid_domain,
)
from decision_studio.reasoning.framing import (
    FRAMING_QUESTIONS,
    PROFILE_IDS,
    QUESTIONS_BY_ID,
    FramingQuestion,
    answer_value,
    is_complete,
    missing_required,
)

logger = logging.getLogger(__name__)


class FramingError(ValueError):
    """Raised when a framing answer is invalid."""


async def get_frame(session: AsyncSession, project_id: UUID) -> DecisionFrame | None:
    result = await session.execute(
        select(DecisionFrame).where(DecisionFrame.project_id == project_id)
    )
    return result.scalars().first()


async def get_profile(session: AsyncSession) -> DecisionProfile:
    """The deployment's profile, created empty on first access."""
    profile = (await session.execute(select(DecisionProfile).limit(1))).scalars().first()
    if profile is None:
        profile = DecisionProfile(answers={})
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
    return profile


async def save_profile(
    session: AsyncSession, answers: dict[str, Any]
) -> DecisionProfile:
    """Save the answers that hold across analyses.

    Only profile-scoped questions are accepted here. A decision-specific answer
    saved to the profile would be copied into every later analysis as though it
    were true of them too.

    Existing frames are left alone on purpose: a frame records what was known
    when that analysis ran, and changing your stated risk appetite must not
    rewrite the basis of a decision already taken.

    Raises:
        FramingError: an answer is invalid, or not a profile question.
    """
    profile = await get_profile(session)
    merged = dict(profile.answers or {})
    now = datetime.now(timezone.utc).isoformat()

    for question_id, raw in answers.items():
        if question_id not in PROFILE_IDS:
            raise FramingError(
                f"'{question_id}' is specific to one decision and cannot be "
                f"saved to the profile."
            )
        value = raw.get("value") if isinstance(raw, dict) else raw
        if value is None:
            merged.pop(question_id, None)
            continue
        merged[question_id] = {"value": _coerce(question_id, value), "answered_at": now}

    profile.answers = merged
    await session.commit()
    await session.refresh(profile)
    logger.info("Decision profile updated: %d answer(s) stored", len(merged))
    return profile


def profile_status(profile: DecisionProfile | None) -> dict[str, Any]:
    """How much of the profile is filled in."""
    answers = profile.answers if profile else {}
    answered = [qid for qid in PROFILE_IDS if answer_value(answers, qid) not in (None, "")]
    return {
        "answered_count": len(answered),
        "total_count": len(PROFILE_IDS),
        "is_complete": len(answered) == len(PROFILE_IDS),
        "missing": [qid for qid in PROFILE_IDS if qid not in answered],
    }


async def get_or_create_frame(
    session: AsyncSession, project_id: UUID
) -> DecisionFrame:
    """Fetch the frame, creating an empty one on first access.

    Raises:
        LookupError: unknown project.
    """
    frame = await get_frame(session, project_id)
    if frame is not None:
        return frame
    if await session.get(Project, project_id) is None:
        raise LookupError(f"Project {project_id} not found")
    # Seed from the profile. Copied rather than referenced: a frame is a record
    # of what was known when that analysis ran, and a later profile edit must
    # not rewrite the basis of a decision already taken.
    profile = await get_profile(session)
    seeded = {
        qid: dict(entry)
        for qid, entry in (profile.answers or {}).items()
        if qid in PROFILE_IDS and isinstance(entry, dict)
    }
    if seeded:
        logger.info(
            "Seeded frame for project %s with %d profile answer(s)",
            project_id, len(seeded),
        )

    frame = DecisionFrame(project_id=project_id, answers=seeded)
    frame.is_complete = is_complete(seeded)
    session.add(frame)
    await session.commit()
    await session.refresh(frame)
    return frame


def effective_questions(frame: DecisionFrame | None) -> list[FramingQuestion]:
    """The questions this project is actually being asked.

    Core catalogue, then the domain pack, then any custom questions the user
    accepted. Custom ones are reconstructed from stored JSON rather than kept in
    a registry: they belong to one project and would otherwise leak into others.
    """
    if frame is None:
        return list(FRAMING_QUESTIONS)

    questions = list(all_questions(frame.domain))
    for raw in frame.custom_questions or []:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        questions.append(
            FramingQuestion(
                id=raw["id"],
                section=raw.get("section", "decision"),
                question=raw.get("question", ""),
                why=raw.get("why", ""),
                answer_type=raw.get("answer_type", "free_text"),
                feeds=raw.get("feeds", "Domain-specific context for generation."),
                # Never required: a proposed question must not gate anything.
                required=False,
                options=tuple(raw.get("options") or ()),
            )
        )
    return questions


def _question_for(frame: DecisionFrame | None, question_id: str) -> FramingQuestion | None:
    if question_id in QUESTIONS_BY_ID:
        return QUESTIONS_BY_ID[question_id]
    return next(
        (q for q in effective_questions(frame) if q.id == question_id), None
    )


def _coerce(question_id: str, value: Any, frame: DecisionFrame | None = None) -> Any:
    """Validate one answer against its question's declared type."""
    question = _question_for(frame, question_id)
    if question is None:
        raise FramingError(f"Unknown framing question '{question_id}'")

    if question.answer_type == "single_choice":
        if value not in question.options:
            raise FramingError(
                f"'{value}' is not one of the offered options for {question_id}"
            )
        return value

    if question.answer_type == "multi_choice":
        if not isinstance(value, list) or not value:
            raise FramingError(f"{question_id} expects a non-empty list")
        invalid = [v for v in value if v not in question.options]
        if invalid:
            raise FramingError(f"'{invalid[0]}' is not an offered option")
        return list(value)

    if question.answer_type == "yes_no":
        if isinstance(value, bool):
            return value
        raise FramingError(f"{question_id} expects yes or no")

    if question.answer_type == "number":
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise FramingError(f"{question_id} expects a number") from exc

    if question.answer_type == "date":
        try:
            return datetime.fromisoformat(str(value)).date().isoformat()
        except ValueError as exc:
            raise FramingError(f"{question_id} expects an ISO-8601 date") from exc

    text = str(value).strip()
    if not text:
        raise FramingError(f"{question_id} cannot be empty")
    return text


async def save_answers(
    session: AsyncSession,
    project_id: UUID,
    answers: dict[str, Any],
) -> DecisionFrame:
    """Merge answers into the frame, recomputing completeness.

    Partial submission is allowed: the questionnaire is long, and forcing it to
    be completed in one sitting would push users to type anything to get past
    it, which defeats the point.

    Raises:
        LookupError: unknown project.
        FramingError: an answer does not fit its question.
    """
    frame = await get_or_create_frame(session, project_id)
    merged = dict(frame.answers or {})
    now = datetime.now(timezone.utc).isoformat()

    for question_id, raw in answers.items():
        value = raw.get("value") if isinstance(raw, dict) else raw
        if value is None:
            merged.pop(question_id, None)
            continue
        merged[question_id] = {
            "value": _coerce(question_id, value, frame),
            "answered_at": now,
        }

    frame.answers = merged
    complete = is_complete(merged)
    if complete and not frame.is_complete:
        frame.completed_at = datetime.now(timezone.utc)
    frame.is_complete = complete

    # The stated decision is the objective the whole system reasons towards.
    decision = answer_value(merged, "decision")
    if decision:
        project = await session.get(Project, project_id)
        if project is not None:
            project.decision_objective = decision

    await session.commit()
    await session.refresh(frame)
    return frame


def frame_status(frame: DecisionFrame | None) -> dict[str, Any]:
    """Progress summary for the UI and for gating.

    Only the core questions can be missing: domain and custom questions are
    never required, so a mis-picked domain cannot block a project.
    """
    answers = frame.answers if frame else {}
    questions = effective_questions(frame)
    missing = missing_required(answers)
    answered = sum(
        1 for q in questions if answer_value(answers, q.id) not in (None, "")
    )
    return {
        "is_complete": not missing,
        "missing_required": missing,
        "answered_count": answered,
        "total_count": len(questions),
        "domain": frame.domain if frame else "generic",
    }


async def set_domain(
    session: AsyncSession, project_id: UUID, domain: str
) -> DecisionFrame:
    """Choose the kind of decision, which adds a pack of questions.

    Answers already given are kept: switching domain adds and removes questions
    but never discards what the user has written, since the core questions apply
    either way and a domain answer may still be relevant if they switch back.

    Raises:
        LookupError: unknown project.
        FramingError: unknown domain.
    """
    if not is_valid_domain(domain):
        raise FramingError(f"Unknown decision domain '{domain}'")
    frame = await get_or_create_frame(session, project_id)
    frame.domain = domain
    await session.commit()
    await session.refresh(frame)
    return frame


async def suggest_domain_questions(
    session: AsyncSession,
    project_id: UUID,
    *,
    llm: LLMClient | None = None,
) -> list[dict[str, Any]]:
    """Propose framing questions for a domain the built-in packs do not cover.

    Returns proposals; they are not stored until ``accept_domain_questions`` is
    called. The same rule as everywhere else here: the model proposes, the user
    commits.

    Raises:
        LookupError: unknown project.
        FramingError: the decision has not been described yet.
    """
    frame = await get_or_create_frame(session, project_id)
    decision = answer_value(frame.answers, "decision")
    if not decision:
        raise FramingError(
            "Describe the decision first — there is nothing to specialise for yet."
        )

    existing = "\n".join(f"- {q.question}" for q in FRAMING_QUESTIONS)
    client = llm or get_llm_client(enable_cache=False)
    payload = await client.complete_json(
        system=DOMAIN_QUESTIONS_SYSTEM,
        user=(
            f"THE DECISION: {decision}\n\n"
            f"ALREADY ASKED (do not repeat):\n{existing}\n\n"
            "Propose the questions that matter for this kind of decision."
        ),
        schema=DOMAIN_QUESTIONS_SCHEMA,
        max_tokens=2048,
        temperature=0.5,
    )

    proposals: list[dict[str, Any]] = []
    for index, raw in enumerate((payload.get("questions") or [])[:5]):
        if not isinstance(raw, dict):
            continue
        text = (raw.get("question") or "").strip()
        if not text:
            continue
        answer_type = raw.get("answer_type", "free_text")
        options = [str(o) for o in (raw.get("options") or []) if str(o).strip()]
        # A choice question with no choices is unanswerable; degrade rather than
        # invent options the model did not supply.
        if answer_type in ("single_choice", "multi_choice") and len(options) < 2:
            answer_type, options = "free_text", []
        proposals.append(
            {
                "id": f"custom_{index}",
                "section": raw.get("section", "decision"),
                "question": text,
                "why": (raw.get("why") or "").strip(),
                "answer_type": answer_type,
                "options": options,
                "feeds": (
                    "Base rate for the outside view."
                    if raw.get("is_reference_class")
                    else "Domain-specific context for generation."
                ),
                "is_reference_class": bool(raw.get("is_reference_class")),
            }
        )

    logger.info(
        "Proposed %d domain questions for project %s (%s)",
        len(proposals), project_id, payload.get("domain_label", "unlabelled"),
    )
    return proposals


async def accept_domain_questions(
    session: AsyncSession,
    project_id: UUID,
    questions: list[dict[str, Any]],
) -> DecisionFrame:
    """Store accepted proposals, so they start being asked.

    Raises:
        LookupError: unknown project.
    """
    frame = await get_or_create_frame(session, project_id)
    frame.domain = DOMAIN_OTHER
    frame.custom_questions = [
        {
            "id": q.get("id") or f"custom_{i}",
            "section": q.get("section", "decision"),
            "question": q.get("question", ""),
            "why": q.get("why", ""),
            "answer_type": q.get("answer_type", "free_text"),
            "options": q.get("options") or [],
            "feeds": q.get("feeds", "Domain-specific context for generation."),
        }
        for i, q in enumerate(questions)
        if isinstance(q, dict) and (q.get("question") or "").strip()
    ]
    await session.commit()
    await session.refresh(frame)
    return frame
