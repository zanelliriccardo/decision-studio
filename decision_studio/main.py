import logging
import os
import sys
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from decision_studio.config import settings
from decision_studio.db.session import engine

# Configure logging so pipeline INFO messages are visible
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    stream=sys.stderr,
)
# Quiet noisy libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("watchfiles").setLevel(logging.WARNING)
logging.getLogger("transformers").setLevel(logging.WARNING)
logging.getLogger("torch").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: preload NLI model in a background thread so it doesn't
    # block the event loop or the first evidence grounding request.
    """Warm what is expensive to load, and report schema drift, once at startup."""
    import asyncio
    from decision_studio.evidence.nli_scorer import preload_model
    asyncio.get_event_loop().run_in_executor(None, preload_model)
    # Say plainly when the database is behind the code. Otherwise the first
    # symptom is a missing relation deep inside an unrelated request.
    from decision_studio.db.schema_check import check_schema, report

    report(await check_schema(engine))


    yield
    # Shutdown: dispose of the engine connection pool
    await engine.dispose()


logger = logging.getLogger(__name__)

app = FastAPI(
    title="Decision Studio",
    description="Causal Intelligence for Better Decisions",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api")
async def root():
    """Service identity.

    Moved off `/` when the frontend started being served from this process:
    a person opening the deployed URL should land on the application, not on a
    JSON blob. Kept because deployment checks and humans probing the API both
    expect something at a bare path.
    """
    return {
        "name": "Decision Studio",
        "description": "Causal Intelligence for Better Decisions",
        "version": "0.1.0",
    }


@app.get("/health")
async def health():
    """Liveness probe. Deliberately touches nothing."""
    return {"status": "ok"}


# API routers
from decision_studio.api.routes import analysis, graph, scenarios, export, operations, causal_analysis, events, reasoning, intake, theory_value, decision_workspace  # noqa: E402

app.include_router(analysis.router)
app.include_router(graph.router)
app.include_router(scenarios.router)
app.include_router(export.router)
app.include_router(operations.router)
app.include_router(causal_analysis.router)
app.include_router(events.router)
app.include_router(reasoning.router)
app.include_router(intake.router)
app.include_router(theory_value.router)
app.include_router(decision_workspace.router)


# --- Frontend ---------------------------------------------------------------
# Serving the built bundle from the API process keeps deployment to a single
# unit. Mounted last, so every API route is matched first and only unmatched
# paths reach the SPA fallback.
#
# Absent in development: `vite dev` serves the frontend on its own port and
# proxies /api here, so there is no dist/ to mount and none should be expected.
# Overridable via DECISION_STUDIO_FRONTEND_DIST. The default is right for both the
# repository layout and the container; the override exists so a deployment can
# put the bundle elsewhere without patching code.
_FRONTEND_DIST = Path(
    os.environ.get(
        "DECISION_STUDIO_FRONTEND_DIST",
        Path(__file__).resolve().parent.parent / "frontend" / "dist",
    )
).resolve()

if _FRONTEND_DIST.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=_FRONTEND_DIST / "assets"),
        name="assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """Serve the SPA for any path the API did not claim.

        A client-side router owns /projects/<id> and friends, so a hard refresh
        or a shared link must return index.html rather than 404 — the router
        then reads the URL and renders the right view.

        Unknown /api paths are excluded deliberately: returning index.html for a
        mistyped endpoint would turn a clear 404 into an HTML body that fails to
        parse as JSON somewhere far from the cause.
        """
        if full_path.startswith("api/") or full_path.startswith("ws/"):
            raise HTTPException(status_code=404, detail="Not found")

        candidate = (_FRONTEND_DIST / full_path).resolve()
        # Only serve real files inside dist/. Without this check a path such as
        # ../../etc/passwd would escape the directory.
        if (
            full_path
            and candidate.is_file()
            and _FRONTEND_DIST in candidate.parents
        ):
            return FileResponse(candidate)

        return FileResponse(_FRONTEND_DIST / "index.html")

else:
    logger.info(
        "No frontend bundle at %s — API-only mode (expected in development)",
        _FRONTEND_DIST,
    )
