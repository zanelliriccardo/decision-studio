"""Questions asked before the pipeline starts, and what their answers become.

The answers are rendered into a block of text that is prepended to the claim
extraction and causal inference prompts. That is the whole mechanism — there is
no second graph, no separate store of user beliefs, no node type. The answers
change **how the material is read** and nothing else.

Why before rather than during: correcting a misread claim after extraction means
re-inferring its links and re-propagating everything downstream, while the same
answer arriving beforehand means the claim is never split the wrong way. The
earlier attempt got this right and then paused a running pipeline to collect the
answers, which cost more than it saved. Running before the orchestrator is called
keeps the benefit and removes the cost.

Every failure path here starts the analysis anyway. This step improves a run that
is perfectly capable of proceeding without it; raising would invert its purpose.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_studio.config import settings
from decision_studio.db.models import IntakeQuestion, Project
from decision_studio.llm.client import LLMClient, get_llm_client
from decision_studio.llm.prompts.intake import INTAKE_SCHEMA, INTAKE_SYSTEM

logger = logging.getLogger(__name__)

#: Some latitude — the useful questions are not always the obvious ones — but
#: well short of the adversary's, because this is reading comprehension.
TEMPERATURE = 0.4

#: Material sent to the model. Beyond this the prompt is long, slow and the
#: questions get vaguer: everything looks ambiguous in bulk.
MAX_MATERIAL_CHARS = 24_000

#: Sort order. `authority` first because who decides is almost never in the
#: material — it is absent by nature rather than by oversight — and because
#: sorting happens *before* truncation to the cap, so it is never the one cut.
KIND_ORDER = ("authority", "ambiguity", "scope", "absence", "frame")

#: Cosine similarity above which two options are not a choice. Deliberately
#: below the claim-dedup threshold: options are short, and two short strings
#: meaning the same thing score lower than two sentences doing so.
OPTION_SIMILARITY_LIMIT = 0.85


def _normalise(text: str) -> str:
    """Collapse whitespace only.

    Punctuation and case are left alone on purpose: a quotation that differs
    from the source in more than spacing is not a quotation.
    """
    return re.sub(r"\s+", " ", (text or "")).strip()


def verify_quotation(quoted: str, material: str) -> str | None:
    """The quotation if it really appears in the material, otherwise None.

    A citation the user cannot find in their own document makes them doubt the
    document rather than answer the question, so an unverifiable one is dropped
    and the question shown without it.
    """
    candidate = _normalise(quoted)
    if len(candidate) < 8:
        return None
    return candidate if candidate in _normalise(material) else None


async def _options_are_distinct(options: list[str]) -> bool:
    """Whether the options represent genuinely different readings.

    **Fails open.** If the embedding service is unreachable the options are
    kept: losing valid options to a service being down is worse than showing two
    that read similarly.
    """
    if len(options) < 2:
        return True

    try:
        from decision_studio.llm.embeddings import EmbeddingService
        from decision_studio.pipeline.claim_dedup import cosine

        vectors = await EmbeddingService().embed_batch(options)
    except Exception as exc:
        logger.debug("Could not check option distinctness, keeping them: %s", exc)
        return True

    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            if cosine(vectors[i], vectors[j]) >= OPTION_SIMILARITY_LIMIT:
                return False
    return True


async def generate_questions(
    session: AsyncSession,
    project_id: UUID,
    material: str,
    *,
    llm: LLMClient | None = None,
) -> list[IntakeQuestion]:
    """Read the material once and ask about what it left unclear.

    Returns the stored questions, newest generation replacing any earlier one.
    An empty list is a correct outcome, not a failure: it means the material was
    clear enough to proceed.

    Never raises. Every failure path returns an empty list, because this step
    exists to improve a run that can proceed without it.
    """
    if not settings.intake_enabled:
        # The deployment-wide off switch. Returning empty rather than raising
        # means the client needs no support for it: its own "no questions" path
        # already forwards to the analysis.
        logger.info("Intake disabled by configuration; asking nothing")
        return []

    if len(material.strip()) < 200:
        # Too little to have left anything ambiguous, and a model asked to find
        # ambiguity in three sentences will invent some.
        return []

    project = await session.get(Project, project_id)
    objective = (getattr(project, "decision_objective", None) or "").strip()

    try:
        client = llm or get_llm_client(enable_cache=False)
        payload = await client.complete_json(
            system=INTAKE_SYSTEM,
            user="\n\n".join(
                part for part in (
                    # The stated decision leads, where there is one: a question
                    # is only worth asking if its answer would change how the
                    # material bears on *this* choice.
                    f"THE DECISION BEING MADE: {objective}" if objective else "",
                    f"THE MATERIAL:\n\n{material[:MAX_MATERIAL_CHARS]}",
                    "Ask only where an answer would change how you read this. "
                    "Returning no questions is correct if it is clear.",
                ) if part
            ),
            schema=INTAKE_SCHEMA,
            max_tokens=2048,
            temperature=TEMPERATURE,
        )
    except Exception as exc:
        logger.warning("Intake questions unavailable, continuing without: %s", exc)
        return []

    raw = payload.get("questions")
    if not isinstance(raw, list):
        # A malformed payload is not worth a failed run.
        logger.warning("Intake returned %s rather than a list; asking nothing",
                       type(raw).__name__)
        return []

    candidates = [q for q in raw if isinstance(q, dict) and (q.get("question") or "").strip()]

    # Sorted before truncation, so the cap never drops the authority question.
    candidates.sort(key=lambda q: KIND_ORDER.index(q["kind"])
                    if q.get("kind") in KIND_ORDER else len(KIND_ORDER))
    candidates = candidates[: settings.intake_max_questions]

    # Replace any earlier generation rather than accumulate: the questions are
    # about this material, and two generations would be asked side by side.
    await _clear_questions(session, project_id)

    created: list[IntakeQuestion] = []
    for position, item in enumerate(candidates):
        options = [
            str(o).strip() for o in (item.get("options") or []) if str(o).strip()
        ][:3]
        rejected = False
        if options and not await _options_are_distinct(options):
            # Recorded rather than silently discarded: near-identical options
            # are the signal that the prompt needs work.
            logger.info(
                "Discarded near-identical options for intake question: %s",
                item["question"][:80],
            )
            options, rejected = [], True

        question = IntakeQuestion(
            project_id=project_id,
            position=position,
            kind=item.get("kind") if item.get("kind") in KIND_ORDER else "frame",
            question=item["question"].strip(),
            quoted_source=verify_quotation(item.get("quoted_source", ""), material),
            rationale=(item.get("rationale") or "").strip(),
            options=options or None,
            options_rejected=rejected,
        )
        session.add(question)
        created.append(question)

    await session.commit()
    for question in created:
        await session.refresh(question)

    logger.info(
        "Intake: %d question(s) for project %s%s",
        len(created), project_id,
        "" if created else " — the material was clear enough to proceed",
    )
    return created


async def _clear_questions(session: AsyncSession, project_id: UUID) -> None:
    """Drop an earlier generation, so two are never asked side by side."""
    from sqlalchemy import delete

    await session.execute(
        delete(IntakeQuestion).where(IntakeQuestion.project_id == project_id)
    )


async def list_questions(
    session: AsyncSession, project_id: UUID
) -> list[IntakeQuestion]:
    """Questions for a project, in display order, with any answers given."""
    result = await session.execute(
        select(IntakeQuestion)
        .where(IntakeQuestion.project_id == project_id)
        .order_by(IntakeQuestion.position)
    )
    return list(result.scalars().all())


async def save_answers(
    session: AsyncSession,
    project_id: UUID,
    answers: list[dict[str, Any]],
) -> list[IntakeQuestion]:
    """Record answers. Unanswered questions stay unanswered, which is fine."""
    from datetime import datetime, timezone

    questions = {str(q.id): q for q in await list_questions(session, project_id)}
    now = datetime.now(timezone.utc)

    for answer in answers:
        question = questions.get(str(answer.get("question_id")))
        if question is None:
            continue
        text = (answer.get("text") or "").strip()
        choice = answer.get("choice")

        # Free text wins over a choice: someone who typed after clicking has
        # said something the options did not cover.
        if text:
            question.answer_text = text
            question.answer_choice = None
            question.answered_at = now
        elif isinstance(choice, int) and question.options and 0 <= choice < len(question.options):
            question.answer_choice = choice
            question.answer_text = None
            question.answered_at = now

    await session.commit()
    return await list_questions(session, project_id)


def render_answers(questions: list[IntakeQuestion]) -> str:
    """The answers as a block for the extraction and inference prompts.

    Unanswered questions are **omitted entirely** — no "unknown", no
    placeholder. This block is prepended to every inference call and a run
    evaluates hundreds of pairs, so an invented premise here is repeated
    hundreds of times.

    Returns an empty string when nothing was answered, which must be
    indistinguishable from no context at all: that is what makes the skip path
    the same run it claims to be.
    """
    answered = [
        q for q in questions
        if q.answered_at is not None and (q.answer_text or q.answer_choice is not None)
    ]
    if not answered:
        return ""

    lines = [
        "# How to read this material (stated by the user, authoritative)",
        "Where this contradicts your reading, the user is right.",
        "",
    ]
    for question in answered:
        if question.answer_text:
            value = question.answer_text
        else:
            value = question.options[question.answer_choice]  # type: ignore[index]
        lines.append(f"- {question.question}")
        lines.append(f"  -> {value}")

    rendered = "\n".join(lines) + "\n"

    if len(rendered) > settings.intake_context_max_chars:
        # Truncation is visible in the text itself. A silently cut premise reads
        # as a complete one, and the model would treat a half-sentence as the
        # user's whole position.
        rendered = (
            rendered[: settings.intake_context_max_chars]
            + "\n[context truncated]\n"
        )
        logger.warning(
            "Intake context exceeded %d characters and was truncated",
            settings.intake_context_max_chars,
        )

    return rendered
