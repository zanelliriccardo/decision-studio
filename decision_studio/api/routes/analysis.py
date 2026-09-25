"""Analysis API routes.

Provides endpoints to start a causal analysis pipeline, stream progress
via Server-Sent Events, and poll for status.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from sqlalchemy import select

from decision_studio.api.models.analysis import (
    AnalyzeFileResponse,
    AnalyzeRequest,
    AnalyzeResponse,
    PipelineStageStatus,
    ProjectListResponse,
    ProjectStatus,
    ProjectSummary,
)
from decision_studio.config import settings
from decision_studio.api.sources import (
    attach_documents,
    combine_input,
    require_analysable,
)
from decision_studio.db.models import Document, Claim, Project
from decision_studio.db.session import async_session, get_session
from decision_studio.evidence.web_search import BraveSearchClient, DuckDuckGoSearchClient
from decision_studio.llm.client import get_llm_client
from decision_studio.llm.embeddings import EmbeddingService
from decision_studio.pipeline.orchestrator import CausalPipeline, PipelineEvent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["analysis"])

# ---------------------------------------------------------------------------
# Replay-able event log: SSE consumers can reconnect and replay all events.
# This avoids losing events when React StrictMode double-invokes effects.
# ---------------------------------------------------------------------------

class _PipelineEventLog:
    """Append-only event log with notification for SSE consumers."""

    def __init__(self) -> None:
        """Start an empty replay log for one pipeline run."""
        self.events: list[PipelineEvent | None] = []
        self.notify = asyncio.Event()
        self.stage_history: list[PipelineStageStatus] = []

    def append(self, event: PipelineEvent | None) -> None:
        """Record an event and wake anyone waiting on the stream."""
        self.events.append(event)
        self.notify.set()

    def append_stage(self, stage: PipelineStageStatus) -> None:
        """Record a stage transition, for clients that connect late."""
        self.stage_history.append(stage)


_pipeline_logs: dict[str, _PipelineEventLog] = {}


async def _run_pipeline(
    project_id: str, text: str, extra_context: str | None = None
) -> None:
    """Background coroutine that executes the full causal pipeline.

    Appends PipelineEvent objects to the replay-able event log so that
    SSE stream consumers can read them (including on reconnection).
    A ``None`` sentinel signals completion.

    ``extra_context`` carries the intake answers. It is prepended to the
    extraction and inference prompts so the disambiguation the user gave shapes
    the graph as it is built, rather than having to be applied to a graph that
    was built without it.
    """
    log = _pipeline_logs.get(project_id)
    if log is None:
        log = _PipelineEventLog()
        _pipeline_logs[project_id] = log

    async with async_session() as session:
        try:
            llm_client = get_llm_client()
            embedding_service = EmbeddingService()

            # Default to DuckDuckGo (free, no API key needed).
            # Falls back to Brave Search if a Brave API key is configured.
            search_client: DuckDuckGoSearchClient | BraveSearchClient
            if settings.brave_search_api_key:
                search_client = BraveSearchClient(settings.brave_search_api_key)
            else:
                search_client = DuckDuckGoSearchClient()

            pipeline = CausalPipeline(
                session=session,
                llm_client=llm_client,
                embedding_service=embedding_service,
                search_client=search_client,
            )

            async def event_callback(event: PipelineEvent) -> None:
                """Forward one pipeline event to the replay log and the stream."""
                stage_status = PipelineStageStatus(
                    stage=event.stage,
                    status=event.status,
                    progress=event.progress,
                    data=event.data if isinstance(event.data, dict) else None,
                    timestamp=datetime.now(timezone.utc),
                )
                log.append_stage(stage_status)
                log.append(event)

            await pipeline.run(
                project_id, text, event_callback, extra_context=extra_context
            )
            await session.commit()

            # Theories and comparisons, immediately. A finished graph is not the
            # answer to anything — it is the material the answer is made from,
            # and leaving the user to press two more buttons meant most runs
            # stopped at a picture nobody could act on.
            #
            # Failures here are reported and swallowed: the graph is real work
            # already committed, and losing it because a later LLM call timed out
            # would be the worst possible trade.
            await _generate_downstream(project_id, event_callback, log)

        except Exception as exc:
            logger.exception("Pipeline failed for project %s: %s", project_id, exc)
            error_event = PipelineEvent(
                stage="pipeline",
                status="error",
                data={"error": str(exc)},
                progress=0.0,
            )
            error_stage = PipelineStageStatus(
                stage="pipeline",
                status="error",
                data={"error": str(exc)},
                timestamp=datetime.now(timezone.utc),
            )
            log.append_stage(error_stage)
            log.append(error_event)

        finally:
            # Signal completion
            log.append(None)

            if search_client is not None:
                await search_client.close()


async def _extract_text(filename: str, content: bytes) -> str:
    """Pull text out of an uploaded file.

    Separated from the upload endpoint so that storing the document and reading
    it are two steps: the file is kept whatever happens here, and a parser that
    fails today can be re-run over the stored bytes tomorrow.
    """
    filename_lower = filename.lower()

    # --- Plain text files ---
    if filename_lower.endswith((".txt", ".md", ".csv", ".json")):
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1")
        return text

    # --- PDF ---
    if filename_lower.endswith(".pdf"):
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(content))
            pages_text = [page.extract_text() or "" for page in reader.pages]
            text = "\n\n".join(pages_text).strip()
        except ImportError:
            raise HTTPException(
                status_code=501,
                detail="PDF support requires pypdf. Install with: pip install pypdf",
            )
        if not text:
            raise HTTPException(status_code=422, detail="Could not extract text from PDF")
        return text

    # --- Images (via OpenAI Vision) ---
    if filename_lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        import base64
        from decision_studio.config import settings

        if not settings.openai_api_key:
            raise HTTPException(
                status_code=501,
                detail="Image analysis requires OPENAI_API_KEY for Vision API",
            )

        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.openai_api_key)

        # Determine MIME type
        ext = filename.rsplit(".", 1)[-1]
        mime_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}
        mime_type = mime_map.get(ext, "image/png")

        b64_image = base64.b64encode(content).decode("utf-8")

        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Analyze this image in detail. Extract all factual claims, "
                                "assertions, data points, relationships, and causal statements "
                                "visible in the image. If it's a chart/graph/diagram, describe "
                                "the data and trends. If it's a document/screenshot, transcribe "
                                "the key content. If it's a photo/scene, describe what's happening "
                                "and any causal relationships you can identify. "
                                "Write your analysis as structured prose paragraphs."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{b64_image}"},
                        },
                    ],
                }
            ],
            max_tokens=4096,
        )

        text = response.choices[0].message.content or ""
        if not text:
            raise HTTPException(status_code=422, detail="Could not extract content from image")

        return text
    raise HTTPException(
        status_code=415,
        detail="Unsupported file type. Supported: .txt, .md, .csv, .json, .pdf, .png, .jpg, .jpeg, .webp",
    )


@router.post("/upload", response_model=AnalyzeFileResponse)
async def upload_file(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> AnalyzeFileResponse:
    """Store an uploaded document and extract its text.

    Store first, read second. The document survives an extraction failure,
    which matters because a file the parser cannot handle today is still the
    file the user meant to use.

    Only a preview is returned. The full text stays here and is read when
    analysis starts — returning all of it was how a hundred-page PDF became a
    wall of characters in a textarea, overwriting whatever the user had typed.
    """
    if file.filename is None:
        raise HTTPException(status_code=400, detail="No filename provided")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The file is empty")

    text, error = "", None
    try:
        text = await _extract_text(file.filename, content)
    except HTTPException:
        # An unsupported type is worth refusing outright: keeping a file nothing
        # can read only defers the same message to analysis time.
        raise
    except Exception as exc:
        logger.warning("Extraction failed for %s: %s", file.filename, exc)
        error = str(exc)

    document = Document(
        filename=file.filename,
        content_type=file.content_type,
        size_bytes=len(content),
        extracted_text=text,
        extraction_error=error,
        # Keep the original only when it is small enough that a row is a
        # reasonable place for it. Above that the text is what matters.
        raw_content=content if len(content) <= 5_000_000 else None,
    )
    session.add(document)
    await session.commit()
    await session.refresh(document)

    return AnalyzeFileResponse(
        document_id=document.id,
        title=file.filename.rsplit(".", 1)[0],
        filename=file.filename,
        size_bytes=len(content),
        char_count=len(text),
        text=text[:400],
        extraction_error=error,
    )


async def _generate_downstream(
    project_id: str,
    event_callback: Any,
    log: "_PipelineEventLog",
) -> None:
    """Generate theories, then compare them, once the graph exists.

    Runs in its own session: the pipeline's has just been committed and reusing
    it would tie the graph's fate to these calls.
    """
    from decision_studio.db.session import async_session
    from decision_studio.reasoning import debate_service
    from decision_studio.reasoning import recommendation
    from decision_studio.reasoning import theories as theory_service

    async def emit(stage: str, status: str, data: dict[str, Any] | None = None) -> None:
        """Report a downstream stage to the log and the SSE stream."""
        event = PipelineEvent(stage=stage, status=status, data=data, progress=1.0)
        log.append_stage(
            PipelineStageStatus(
                stage=stage, status=status, data=data,
                timestamp=datetime.now(timezone.utc),
            )
        )
        log.append(event)
        if event_callback is not None:
            await event_callback(event)

    uuid_id = UUID(project_id)

    async with async_session() as session:
        try:
            await emit("theory_generation", "started")
            result = await theory_service.generate_theories(session, uuid_id)
            await emit(
                "theory_generation", "completed",
                {
                    "count": len(result.theories),
                    # Reported so the summary page can say which it is showing:
                    # without a stated decision the theories describe the
                    # situation rather than bearing on a choice.
                    "objective_missing": result.objective_missing,
                },
            )
        except Exception as exc:
            logger.warning("Automatic theory generation failed for %s: %s", project_id, exc)
            await emit("theory_generation", "error", {"error": str(exc)})
            return

    # A separate session again: a failed comparison must not roll back theories.
    async with async_session() as session:
        try:
            await emit("theory_debate", "started")
            report = await debate_service.run_debates(session, uuid_id)
            await emit("theory_debate", "completed", report)
        except debate_service.DebateError as exc:
            # Fewer than two theories is the usual reason, and it is not a fault.
            logger.info("Comparisons skipped for %s: %s", project_id, exc)
            await emit("theory_debate", "completed", {"skipped": str(exc)})
        except Exception as exc:
            logger.warning("Automatic comparison failed for %s: %s", project_id, exc)
            await emit("theory_debate", "error", {"error": str(exc)})

    # Last, because it weighs everything above: the theories, their objections
    # and what would disprove them. Running it earlier would synthesise from an
    # incomplete picture.
    async with async_session() as session:
        try:
            await emit("recommendation", "started")
            row = await recommendation.generate_recommendation(session, uuid_id)
            await emit("recommendation", "completed", {"confidence": row.confidence})
        except recommendation.RecommendationError as exc:
            logger.info("No recommendation for %s: %s", project_id, exc)
            await emit("recommendation", "completed", {"skipped": str(exc)})
        except Exception as exc:
            logger.warning("Recommendation failed for %s: %s", project_id, exc)
            await emit("recommendation", "error", {"error": str(exc)})


@router.post("/analyze", response_model=AnalyzeResponse)
async def start_analysis(
    req: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> AnalyzeResponse:
    """Start a new causal analysis pipeline.

    Creates a project record in the database and kicks off the 5-stage
    pipeline as a background task.  Returns immediately with the
    ``project_id`` so the client can subscribe to the SSE stream.
    """
    # Shared with /intake so the two paths cannot assemble the same request
    # differently: a quotation the intake step verified against this text has to
    # be findable in the text the pipeline is then given.
    combined = await combine_input(session, req.text, req.document_ids)
    require_analysable(combined)

    project = Project(
        title=req.title,
        input_text=combined,
        # Stated up front so the stages after the graph — theories, the
        # adversary, the recommendation — have it from the first run rather
        # than needing a regeneration once it is filled in.
        decision_objective=(req.decision_objective or "").strip() or None,
        status="processing",
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)

    project_id_str = str(project.id)

    # Create the event log *before* scheduling the background task
    _pipeline_logs[project_id_str] = _PipelineEventLog()

    if req.document_ids:
        await attach_documents(session, project.id, req.document_ids)

    background_tasks.add_task(_run_pipeline, project_id_str, combined)

    return AnalyzeResponse(project_id=project.id, status="processing")


@router.post("/analyze/{project_id}/resume", response_model=AnalyzeResponse)
async def resume_analysis(
    project_id: UUID,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> AnalyzeResponse:
    """Resume a pipeline from its last checkpoint.

    Completed stages are skipped and existing claims are loaded from the
    database. The intake context is read back from the project rather than
    dropped: a resumed run must see what the first attempt saw, or the stages
    after the checkpoint would read different prompts from the ones before it.
    """
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.status == "processing":
        raise HTTPException(status_code=409, detail="Pipeline is already running")

    if project.status == "completed" and project.last_completed_stage == "belief_propagation":
        raise HTTPException(status_code=409, detail="Pipeline already completed")

    # Reset status to processing
    project.status = "processing"
    await session.commit()

    project_id_str = str(project_id)
    _pipeline_logs[project_id_str] = _PipelineEventLog()

    background_tasks.add_task(
        _run_pipeline, project_id_str, project.input_text, project.intake_context
    )

    return AnalyzeResponse(project_id=project.id, status="processing")


@router.get("/analyze/{project_id}/stream")
async def stream_analysis(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> EventSourceResponse:
    """Stream pipeline progress via Server-Sent Events.

    Each event has:
    - ``event``: the pipeline stage name
    - ``data``: JSON with ``status``, ``progress``, and optional ``data``

    The stream terminates when the pipeline finishes (a ``None`` sentinel
    is received from the internal queue) or when the client disconnects.
    """
    # Verify the project exists
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    project_id_str = str(project_id)
    log = _pipeline_logs.get(project_id_str)

    if log is None:
        # Pipeline already finished or was never started
        if project.status in ("completed", "failed"):
            async def _completed_stream():
                """A single completion event, for a run that finished before the client asked."""
                yield {
                    "event": "complete",
                    "data": json.dumps({
                        "status": "complete",
                        "progress": 1.0 if project.status == "completed" else 0.0,
                    }),
                }

            return EventSourceResponse(_completed_stream())

        # Pipeline might not have started yet; create a log
        log = _PipelineEventLog()
        _pipeline_logs[project_id_str] = log

    async def _event_generator():
        # Replay-able: start from index 0 and read all events, including
        # those already appended before this SSE connection opened.
        # This is critical for React StrictMode which disconnects/reconnects.
        """Replay what has happened, then stream what happens next.

        Replay first so a client connecting mid-run sees the whole story rather
        than joining at the current stage.
        """
        index = 0
        try:
            while True:
                # Yield all events available so far
                while index < len(log.events):
                    event = log.events[index]
                    index += 1

                    if event is None:
                        # Sentinel: pipeline finished
                        yield {
                            "event": "complete",
                            "data": json.dumps({"status": "complete", "progress": 1.0}),
                        }
                        return

                    yield _serialize_event(event)

                # No more events yet — wait for notification
                log.notify.clear()
                try:
                    await asyncio.wait_for(log.notify.wait(), timeout=300.0)
                except asyncio.TimeoutError:
                    yield {"comment": "keep-alive"}
        except asyncio.CancelledError:
            pass

    return EventSourceResponse(_event_generator())


def _serialize_event(event: PipelineEvent) -> dict[str, str]:
    """Serialize a PipelineEvent into an SSE-compatible dict."""
    payload: dict[str, Any] = {
        "status": event.status,
        "progress": event.progress,
        "stage": event.stage,
        "layer": getattr(event, "layer", 0),
    }
    if isinstance(event.data, dict):
        payload.update(event.data)

    event_name = event.stage
    if event.status == "error":
        payload["message"] = payload.get("error", "Pipeline error")
        event_name = "error_event"

    return {"event": event_name, "data": json.dumps(payload)}


@router.get("/projects", response_model=ProjectListResponse)
async def list_projects(
    session: AsyncSession = Depends(get_session),
) -> ProjectListResponse:
    """List all projects, ordered by creation date descending."""
    result = await session.execute(
        select(Project).order_by(Project.created_at.desc())
    )
    projects = result.scalars().all()

    return ProjectListResponse(
        projects=[
            ProjectSummary(
                id=p.id,
                title=p.title,
                status=p.status,
                created_at=p.created_at,
            )
            for p in projects
        ]
    )


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Delete a project and all associated data (cascades)."""
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await session.delete(project)
    await session.commit()
    return {"ok": True}


#: A project left in this state by the version of the pipeline that paused for
#: questions. Nothing produces it any more, so anything found in it is stranded
#: mid-run: claims extracted, no causal links, no evidence.
LEGACY_PAUSED_STATUS = "awaiting_input"


@router.get("/status/{project_id}", response_model=ProjectStatus)
async def get_status(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ProjectStatus:
    """Polling fallback: return current project status with stage history."""
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    log = _pipeline_logs.get(str(project_id))
    stages = log.stage_history if log else []

    # Count persisted claims (non-zero means partial results exist)
    from sqlalchemy import func
    claim_count_result = await session.execute(
        select(func.count()).where(Claim.project_id == project_id)
    )
    claim_count = claim_count_result.scalar() or 0

    return ProjectStatus(
        project_id=project.id,
        title=project.title,
        status=project.status,
        created_at=project.created_at,
        stages=stages,
        claim_count=claim_count,
    )
