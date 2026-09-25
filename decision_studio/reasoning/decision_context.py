"""The stated decision, as context for anything that reasons towards it.

The fifteen-question framing questionnaire is gone. What replaced it is the one
field it was collecting on the way to: ``project.decision_objective``, which
predates the questionnaire and already has an endpoint.

Reasoning still needs to know what is being decided — a theory generated without
it describes the situation rather than bearing on a choice — but that is one
sentence, not fifteen answers, and it can be typed once in the project header.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from decision_studio.db.models import Project


async def decision_objective(session: AsyncSession, project_id: UUID) -> str | None:
    """The decision this project is reasoning towards, if it was stated."""
    project = await session.get(Project, project_id)
    if project is None:
        return None
    stated = (project.decision_objective or "").strip()
    return stated or None


def render_objective(objective: str | None) -> str:
    """Render it for a prompt, or nothing when it was never stated.

    Returning an empty string rather than a placeholder is deliberate: a prompt
    that says "the decision is unknown" invites the model to invent one.
    """
    if not objective:
        return ""
    return f"# The decision being made (stated by the user)\n{objective}\n"
