"""Assembling the analysable text from a request.

Extracted from ``/analyze`` so that ``/intake`` and ``/analyze`` produce
**byte-identical text** from the same request. The intake step verifies each
generated question's quotation against this text; if the two endpoints assembled
it differently — a different separator, a different document order — a quotation
verified on one side would not be findable on the other, and every question would
lose its citation for no visible reason.

Behaviour is unchanged from the inline version this replaces. The extraction is
the point, not a rewrite.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_studio.db.models import Document

logger = logging.getLogger(__name__)

#: Below this there is nothing worth analysing, and the pipeline would spend a
#: model call discovering that.
MIN_ANALYSABLE_CHARS = 10


async def combine_input(
    session: AsyncSession,
    text: str,
    document_ids: list[UUID] | None,
) -> str:
    """Typed context plus the stored text of each attached document.

    Documents are read from the database rather than from anything the client
    sent back: the file is the source, and round-tripping its contents through
    the browser is how a large upload became unusable.

    Raises:
        HTTPException: 404 when a document id does not exist.
    """
    combined = (text or "").strip()
    if not document_ids:
        return combined

    documents = (
        await session.execute(select(Document).where(Document.id.in_(document_ids)))
    ).scalars().all()
    by_id = {d.id: d for d in documents}

    missing = [str(i) for i in document_ids if i not in by_id]
    if missing:
        raise HTTPException(
            status_code=404, detail=f"Unknown document(s): {', '.join(missing)}"
        )

    # Upload order, not database order, and each part labelled: a claim's
    # provenance is only traceable if the source is identifiable in the text.
    parts = [combined] if combined else []
    for doc_id in document_ids:
        doc = by_id[doc_id]
        if doc.extracted_text:
            parts.append(f"--- {doc.filename} ---\n{doc.extracted_text}")

    return "\n\n".join(parts)


def require_analysable(combined: str) -> None:
    """Refuse a request with nothing in it.

    Raises:
        HTTPException: 422 with a message saying what to do about it.
    """
    if len(combined.strip()) < MIN_ANALYSABLE_CHARS:
        raise HTTPException(
            status_code=422,
            detail="Nothing to analyse. Type some context or attach a document "
                   "whose text could be extracted.",
        )


async def attach_documents(
    session: AsyncSession,
    project_id: UUID,
    document_ids: list[UUID],
) -> None:
    """Point the uploaded documents at the project that now exists.

    Documents are uploaded before the project, so this closes the link once
    there is something to link to — which keeps the sources inspectable
    alongside the graph they produced.
    """
    for doc_id in document_ids:
        document = await session.get(Document, doc_id)
        if document is not None:
            document.project_id = project_id
    await session.commit()
