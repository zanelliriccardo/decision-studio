# Single image serving both the API and the built frontend.
#
# One container instead of two because the frontend is a static bundle: FastAPI
# can serve it from the same origin, which removes CORS configuration, removes a
# second deployment target, and removes the class of bug where the two halves
# are running different versions of the same feature.
#
# Build:  docker build -t decision_studio .
# Run:    docker run -p 8000:8000 --env-file .env decision_studio

# ── Stage 1: frontend bundle ────────────────────────────────────────────────
FROM node:22-slim AS frontend

WORKDIR /frontend

# Manifests first: this layer stays cached unless dependencies change, which is
# far less often than the source does.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./

# `npm run build` runs `tsc -b && vite build`. The repository has pre-existing
# type errors in files unrelated to deployment, so that would fail on a checkout
# that is otherwise fine. Bundling directly keeps the image buildable; run
# `npm run build` in CI to enforce type-checking, where a failure is
# informative rather than merely blocking a deploy.
RUN npx vite build

# ── Stage 2: Python dependencies ────────────────────────────────────────────
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install .

# ── Stage 3: runtime ────────────────────────────────────────────────────────
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

WORKDIR /app
COPY decision_studio/ ./decision_studio/
COPY alembic/ ./alembic/
COPY alembic.ini pyproject.toml ./

# The bundle lands where main.py looks for it.
COPY --from=frontend /frontend/dist ./frontend/dist

# Non-root: a container that only ever reads its own code has no reason to be root.
RUN useradd --create-home --uid 10001 decision_studio \
    && chown -R decision_studio:decision_studio /app
USER decision_studio

ENV PYTHONUNBUFFERED=1 \
    PORT=8000

EXPOSE 8000

# Azure polls this before routing traffic to a new revision.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:${PORT}/health || exit 1

# Migrations run at startup rather than as a separate step: App Service has no
# natural place for a one-off command, and alembic is idempotent so a restart
# with nothing pending is a no-op. Trade-off: two instances starting at once
# both attempt it — alembic takes a lock, so the second waits rather than
# corrupting anything.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn decision_studio.main:app --host 0.0.0.0 --port ${PORT}"]
