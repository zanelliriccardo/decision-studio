[**中文**](./README.zh-CN.md) | English

<p align="center">
  <img src="frontend/public/DecisionStudio-Logo.png" alt="Decision Studio" width="120" />
</p>

<h1 align="center">Decision Studio</h1>

<p align="center">
  <em>"Make the reasoning explicit, then decide."</em>
</p>

<p align="center"><strong>Causal Reasoning Engine for Evidence-Based Decisions</strong></p>

---

Decision Studio is an AI-powered decision intelligence tool that makes causal reasoning visible and actionable. Feed it any unstructured text — a policy brief, startup pitch, news event, or strategic hypothesis — and it decomposes the information into atomic claims, traces the hidden cause-and-effect chains between them, grounds each causal link with real-world evidence, and presents the result as an interactive, explorable causal graph.

Instead of trusting black-box predictions, you see *why* one thing leads to another, *how strong* the evidence is, and *what happens if* your assumptions change. Every link in the reasoning chain is transparent, adjustable, and backed by sources — turning information overload into structured insight for better decisions.

## Screenshots

![Main Screen](static/screenshot/decision_studio_en_main.png)
![Causal Graph](static/screenshot/decision_studio_en_graph_basic.png)
![Focus Mode](static/screenshot/decision_studio_en_graph_focus.png)

## How It Works

Decision Studio processes input through a multi-layer pipeline:

**Initial Analysis** — extract claims from user text and build the seed graph:

0. **Decision Anchor** — when a decision is stated, the model drafts its options and the outcomes that define success (editable, never required). Outcomes become nodes in the graph, so inference has a destination; see [HANDOVER §4.10](HANDOVER.md#410-the-decision-anchor)
1. **Claim Decomposition** — LLM extracts atomic claims (FACT / ASSUMPTION / PREDICTION / OPINION) with confidence scores and source sentence provenance for audit trails. With an anchor, each claim is also scored — never filtered — for its role (lever, contingency, mechanism, background), its relevance to the decision, and the options and outcomes it bears on
2. **Causal Link Inference** — Embedding similarity filters candidate pairs, then LLM judges causal direction, mechanism, and strength. Post-LLM validation gates reject edges with empty mechanisms, restated claims, or extreme strength values
3. **Bias Audit** — Detects 8 cognitive bias types and penalizes causal strength accordingly
4. **Evidence Grounding** — Adversarial dual search (supporting + contradicting) via Brave Search, scored for relevance, source credibility, and cross-domain diversity

**Discovery Layers** — iteratively expand the graph with facts the original text didn't mention:

5. **Fact Discovery** — LLM reads the evidence snippets collected above and extracts new claims not in the original text. New claims are deduplicated (0.95 cosine similarity) against existing ones and web-verified before admission
6. **Incremental Inference + Audit + Grounding** — Only claim pairs involving at least one new claim are checked (no re-checking old↔old pairs). New edges go through the same bias audit and evidence search as the seed layer

Discovery repeats (up to 3 layers by default) until convergence: fewer than 2 new claims and fewer than 1 new edge, or the layer budget is exhausted.

**Statistical Validation** (when numeric data is available):

7. **Statistical Validation** — If the user uploads CSV/Excel metric data alongside text, Decision Studio runs Granger causality tests against the LLM-inferred edges. Each edge is tagged as `confirmed` (statistical test agrees, p<0.05), `unsupported` (no significant relationship found), or `contradicted` (reverse direction is stronger). Confirmed edges receive an evidence score boost; unsupported/contradicted edges are penalised

**Finalization:**

8. **DAG Construction** — Builds a directed acyclic graph with cycle detection/breaking and weak-edge pruning
9. **Belief Propagation** — Noisy-OR algorithm propagates beliefs along topological order, modulated by evidence quality. Computes uncertainty intervals via perturbation analysis

## Decision Reasoning

The causal graph is the traceable foundation, not the output. On top of it sits a
workflow for decisions that have no data to appeal to — n = 1, no base rates, no
repeatable trial — where the quality of the answer is bounded by the quality of
the question and validation has to come from process rather than evidence.

**1. Decision frame (required).** Fifteen questions in five sections; ten are
required and *block* theory generation. What is being decided, by whom, by when,
how reversible, what would change your mind, who wrote your sources and whether
they benefit from being believed. Generating before this is answered produces a
summary of the documents wearing a recommendation.

**2. Human review is authoritative.** Reject a claim or a link and it disappears
from every subsequent inference — while staying visible on screen, dimmed, with
an immutable audit log and undo. You can also *add* what the documents missed:
in strategy the factors that matter are frequently not written down anywhere.

**3. Theories with provenance.** Each cites the exact claims, edges and evidence
it rests on, and highlights that subgraph on demand. The model cites short
reference tokens rather than UUIDs, so an invented citation fails to resolve
instead of being persisted.

**4. An adversary that costs something.** A separate call, at higher temperature,
which never sees the theory's own persuasive text — given the prose it would
critique the writing. Its objections reduce the theory's rank; you can judge one
unfounded and it stops counting. An objection that changes no ranking is
decoration.

**5. The outside view.** Your recollection of comparable cases is turned into
explicit base rates, and theories are checked against them. A theory implying 30%
in a project whose owner remembers two out of two integrations slipping is
flagged — not overruled. This case may genuinely differ; you should have to say
why.

**6. Comparisons between theories.** Overlap is computed from the graph, not
judged, so pairs that turn out to be one theory in two wordings never reach the
model. What you get is the crux — where two explanations part company — and a
discriminating observation whose outcome differs depending on which holds. When
nothing separates them before the deadline, that is the finding: pick the option
that survives both.

**7. Tripwires.** You cannot run an experiment on a strategic decision. You can
commit in advance to what would prove you wrong, with a date. When a tripwire
fires, its theory goes stale. This is the only point in the system where new
information about the world enters.

**8. Synthetic and field experiments.** A synthetic run simulates the
stakeholders who must be convinced and answers *"will this survive the room, and
what will they object to"*. It never raises a theory's confidence — five
simulated people agreeing measures the model's agreeableness, not the world — but
their objections route into the adversarial log where they do cost rank. A field
experiment is a real test, and only that moves confidence.

**9. Honest uncertainty.** Monte Carlo re-runs propagation 200 times with every
edge perturbed, scaled by how uncertain that link is, and reports how often each
answer wins rather than which answer wins once. Confidence is shown as a verbal
band: nothing here has ever been calibrated, so a percentage would assert a
resolution the pipeline does not have.

See [COME_FUNZIONA.md](COME_FUNZIONA.md) for how each stage works step by step,
**including every hand-chosen threshold and the assumptions it rests on**.

## Anti-Hallucination Pipeline

Decision Studio is hardened against common LLM hallucination pathways with multiple validation layers:

| Layer | What It Does |
|-------|-------------|
| **Output Validation Gates** | Rejects causal links with empty/restated mechanisms or extreme strength values — prevents false causality from LLM confabulation |
| **Evidence Modulation** | Zero-evidence edges contribute zero belief (not 50%) — ungrounded claims can't propagate through the graph |
| **Bias Severity Penalties** | 8 cognitive bias types detected (correlation≠causation, survivorship, narrative fallacy, anchoring, reverse causality, selection bias, ecological fallacy, confirmation bias) with automatic strength reduction: low→5%, medium→20%, high→40% penalty |
| **Source Diversity Scoring** | Evidence from a single domain scores up to 30% lower — prevents over-reliance on one source |
| **Discovery Verification** | New claims discovered from evidence snippets are web-verified before entering the graph — blocks circular inference |
| **Claim Provenance** | Every claim stores the verbatim source sentence it was extracted from — full audit trail back to original text |
| **Belief Intervals** | Perturbation-based uncertainty bands on every node — see how sensitive each belief is to input variations |
| **Statistical Cross-Check** | When numeric data is available, Granger causality tests independently verify LLM-inferred edges. Confirmed edges are boosted; contradicted edges are penalised — LLM intuition meets statistical rigour |

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Frontend (React + D3.js + Tailwind)                │
│  ┌─────────┐  ┌──────────┐  ┌────────────────────┐  │
│  │  Input   │→│Processing│→│  Radial Tree View   │  │
│  │  Screen  │  │  (SSE)   │  │  (D3 imperative)   │  │
│  └─────────┘  └──────────┘  └────────────────────┘  │
│                               ┌──────┐ ┌──────────┐ │
│                               │Scenar│ │  Export   │ │
│                               │Forge │ │  Panel    │ │
│                               └──────┘ └──────────┘ │
└───────────────────┬─────────────────────────────────┘
                    │ REST / SSE / WebSocket
┌───────────────────┴─────────────────────────────────┐
│  Backend (FastAPI + SQLAlchemy)                      │
│  ┌──────────────────────────────────────────────┐   │
│  │  Pipeline Orchestrator                        │   │
│  │  ClaimExtractor → CausalInferrer →           │   │
│  │  EvidenceGrounder → StatisticalValidator →   │   │
│  │  DAGBuilder → BeliefPropagation              │   │
│  └──────────────────────────────────────────────┘   │
│  ┌─────────┐  ┌───────────┐  ┌─────────────────┐   │
│  │ LLM     │  │  Graph    │  │  Evidence        │   │
│  │ Client  │  │  Algos    │  │  Search/Score    │   │
│  └─────────┘  └───────────┘  └─────────────────┘   │
└───────────────────┬─────────────────────────────────┘
                    │
        ┌───────────┴───────────┐
        │  PostgreSQL + pgvector │
        └───────────────────────┘
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19, TypeScript, D3.js v7, Tailwind CSS 4, Framer Motion |
| Backend | FastAPI, SQLAlchemy 2.0 (async), Pydantic v2 |
| Database | PostgreSQL 16 + pgvector |
| LLM | OpenAI / Anthropic (switchable) |
| Search | Brave Search API |
| Graph | NetworkX, Noisy-OR belief propagation |
| Statistics | SciPy (Granger causality, partial correlation, PC algorithm) |
| Infra | Docker Compose, Alembic migrations |
| Real-time | Server-Sent Events, WebSocket |

## Quick Start

### Prerequisites

- **Docker Desktop** — for PostgreSQL. Nothing else needs it.
- **Node.js 20+** — [nodejs.org](https://nodejs.org)
- **Python 3.12+** — [python.org](https://www.python.org/downloads/). On
  Windows, tick **"Add python.exe to PATH"** in the installer.

`pip` ships with Python and is all you need. [uv](https://docs.astral.sh/uv/) is
faster but is a separate tool: the instructions below use `pip` so they work on
a clean machine.

### 1. Clone and configure environment

```bash
cd decision-studio
cp .env.example .env
```

Edit `.env` and fill in the required values:

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string. Default works with the bundled Docker container: `postgresql+asyncpg://decision_studio:decision_studio@localhost:5432/decision_studio` |
| `OPENAI_API_KEY` | Yes* | Your OpenAI API key (`sk-...`). Required when `LLM_PROVIDER=openai` (default) |
| `ANTHROPIC_API_KEY` | Yes* | Your Anthropic API key (`sk-ant-...`). Required when `LLM_PROVIDER=anthropic` |
| `BRAVE_SEARCH_API_KEY` | Yes | Brave Search API key for evidence grounding. Get one free at [brave.com/search/api](https://brave.com/search/api/) |
| `LLM_PROVIDER` | No | `openai` (default) or `anthropic` |
| `LLM_MODEL` | No | Model name. Default: `gpt-4o` |
| `EMBEDDING_MODEL` | No | Embedding model. Default: `text-embedding-3-small` |
| `SERVER_HOST` | No | Default: `0.0.0.0` |
| `SERVER_PORT` | No | Default: `8000` |
| `CORS_ORIGINS` | No | JSON array of allowed origins. Default: `["http://localhost:5173"]` |

> \* You need at least one of `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`, depending on which provider you choose.

### 2. Start the database

Decision Studio uses PostgreSQL 16 with the [pgvector](https://github.com/pgvector/pgvector) extension. The easiest way is via Docker:

```bash
docker compose up -d postgres
```

This starts a `pgvector/pgvector:pg16` container on port 5432 with automatic health checks. Data is persisted in a Docker volume (`pgdata`).

> **Already have PostgreSQL?** Install the `pgvector` extension, create a database named `decision_studio`, and update `DATABASE_URL` in your `.env` accordingly.

### 3. Set up and start the backend

<details open>
<summary><strong>Windows (PowerShell)</strong></summary>

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1

pip install -e ".[dev]"

alembic upgrade head
uvicorn decision_studio.main:app --reload
```

If `Activate.ps1` is blocked by the execution policy — the usual first
obstacle — allow it for this session only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Your prompt should then start with `(.venv)`. Without it, `alembic` and
`uvicorn` are not on the PATH and PowerShell reports them as unrecognised
commands, which is the same symptom as not having installed anything.

</details>

<details>
<summary><strong>macOS / Linux</strong></summary>

```bash
python3 -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"

alembic upgrade head
uvicorn decision_studio.main:app --reload
```

Or, with [uv](https://docs.astral.sh/uv/) if you have it — `uv sync` replaces
the venv and install steps. It is a separate tool, not bundled with Python, so
skip it unless you already use it.

</details>

The backend is now on [http://localhost:8000](http://localhost:8000).
`http://localhost:8000/health` should return `{"status":"ok"}`.

> **Optional: local evidence scoring.** `pip install -e ".[nli]"` adds a
> transformer model that scores how well each retrieved source supports a
> causal link. It is around 2 GB. Without it everything still runs, but
> retrieved evidence stays at relevance 0 — the log says so once at startup.
> Install it before running a real analysis; skip it on a first run.

### 4. Start the frontend

In a separate terminal:

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

The Vite dev server proxies `/api/*` and `/ws/*` to the backend, so there is
nothing else to configure.

> **`npm run build` currently fails.** It runs `tsc -b` first, and the
> repository carries pre-existing type errors in files unrelated to the
> features documented here. `npm run dev` and `npx vite build` both work —
> the Docker image uses the latter for exactly this reason.

### 5. Load demo data (optional)

A pre-built example project ("Will AI Replace Programmers? — Causal Chain Analysis") is included so you can explore the graph immediately without spending API tokens:

```bash
psql postgresql://decision_studio:decision_studio@localhost:5432/decision_studio \
  -f seed_ai_replace_programmers.sql
```

On Windows, `psql` is usually not installed — run it inside the container
instead, which already has it:

```powershell
docker compose exec -T postgres psql -U decision_studio -d decision_studio < seed_ai_replace_programmers.sql
```

This loads 77 claims, 1,717 causal edges, and 1,485 evidence records. After loading, visit [http://localhost:5173/history](http://localhost:5173/history) and click the project to explore.

> A Chinese version of the same dataset is also available: `seed_ai_replace_programmers_zh.sql`

> **After pulling changes, run `alembic upgrade head` again.** New tables arrive
> with new features, and a missing one surfaces as
> `relation "..." does not exist` in the middle of an unrelated request rather
> than as anything that names the cause.

### 6. Run the tests

The test suite needs its own database — it drops and recreates the schema, so
pointing it at your working one would wipe it.

**macOS / Linux:**

```bash
createdb decision_studio_test
psql decision_studio_test -c 'CREATE EXTENSION IF NOT EXISTS vector;'

TEST_DATABASE_URL=postgresql+asyncpg://decision_studio:decision_studio@localhost:5432/decision_studio_test \
  pytest
```

**Windows (PowerShell)** — `VAR=value command` is Unix shell syntax and does
nothing here; set the variable first:

```powershell
docker compose exec postgres createdb -U decision_studio decision_studio_test
docker compose exec postgres psql -U decision_studio -d decision_studio_test `
  -c "CREATE EXTENSION IF NOT EXISTS vector;"

$env:TEST_DATABASE_URL = "postgresql+asyncpg://decision_studio:decision_studio@localhost:5432/decision_studio_test"
pytest
```

Then, either platform:

```
cd frontend
npm test
```

509 backend tests and 171 frontend tests. No test contacts an LLM or a search
provider: `FakeLLMClient` replays canned structured output, so the suite runs
without credentials and without spending anything.

Without a reachable database the 234 database-backed tests skip and the rest
still run, which is enough to check most logic.

### Alternative: Docker Compose (full stack)

To run the database and backend together in Docker:

```bash
docker compose up --build
```

This starts PostgreSQL + the backend API. You still need to run the frontend separately with `npm run dev` (see step 4).

### Running it the way it is deployed

The two-process setup above is for development: Vite gives hot reload, which is
worth having. Production runs a single container that serves both halves from
one origin.

To reproduce that locally — worth doing once before deploying, since it is the
only way to catch a bundling problem before Azure does:

```bash
docker build -t decision-studio .
docker run -p 8000:8000 --env-file .env \
  --add-host=host.docker.internal:host-gateway \
  decision-studio
```

Open [http://localhost:8000](http://localhost:8000) — the whole app, no second
port. The container runs migrations on startup, so the database must be
reachable from inside it: on Linux the `--add-host` flag above, and on macOS or
Windows point `DATABASE_URL` at `host.docker.internal` instead of `localhost`.

## Deploying to Azure

One Web App serves both halves. The frontend is a static bundle, so FastAPI
serves it from the same origin — no CORS to configure, one deployment target,
and no possibility of the API and the UI running different versions of the same
feature.

```
┌──────────────────────────────────────┐
│  Azure Web App (Linux container)     │
│    /api/*  → FastAPI                 │
│    /*      → the frontend            │
└──────────────┬───────────────────────┘
               │
   ┌───────────┴─────────────────────┐
   │ Azure Database for PostgreSQL   │
   │ Flexible Server + pgvector      │
   └─────────────────────────────────┘
```

### Before you start

| | |
|---|---|
| An Azure subscription | with permission to create resources |
| An OpenAI or Anthropic key | required |
| A Brave Search key | optional — evidence grounding degrades gracefully without it |

Budget about 40 minutes the first time. Two of the steps involve waiting for
Azure rather than doing anything.

---

### Step 1 — Resource group

**Portal → Resource groups → Create**

| Field | Value |
|---|---|
| Name | `decision-studio-rg` |
| Region | Pick one near you and **use the same one throughout** |

Review + create.

---

### Step 2 — PostgreSQL Flexible Server

**Portal → "Azure Database for PostgreSQL" → Create → Flexible server**

*Basics:*

| Field | Value |
|---|---|
| Resource group | `decision-studio-rg` |
| Server name | `decision-studio-pg` (must be globally unique — add digits if taken) |
| Region | the same one |
| PostgreSQL version | **16** |
| Workload type | Development |
| Compute + storage | Burstable **B1ms**, 32 GiB |
| Authentication | PostgreSQL authentication only |
| Admin username | `dsadmin` |
| Password | choose a strong one — **you will need it in step 5** |

*Networking:*

- Connectivity: **Public access**
- Tick **"Allow public access from any Azure service within Azure to this server"**

That last tick is what lets the Web App reach the database. It permits Azure
services, not the open internet — but for anything holding real strategy
documents, switch to Private access with a VNet once it works.

Review + create. **This takes 5–10 minutes.** Continue to step 3 while it runs.

---

### Step 3 — Enable pgvector

Embeddings are stored in a `vector` column, and the extension is not on by
default. Skip this and the first migration fails with `type "vector" does not
exist`, which is a confusing way to discover it.

**Your server → Settings → Server parameters**

1. Search for `azure.extensions`
2. Tick **VECTOR** in the list
3. **Save** (the server restarts, ~1 minute)

Then create it in the database:

**Your server → Databases → Connect** (or the Cloud Shell / any psql client):

```sql
CREATE DATABASE decision_studio;
\c decision_studio
CREATE EXTENSION IF NOT EXISTS vector;
```

---

### Step 4 — Container registry, and build the image

**Portal → Container registries → Create**

| Field | Value |
|---|---|
| Registry name | `decisionstudioacr` + a few digits (globally unique, letters and numbers only) |
| Resource group | `decision-studio-rg` |
| SKU | Basic |

After it deploys: **Settings → Access keys → enable Admin user**. Note the
username and one password; step 5 needs them.

**Now build the image.** Building in Azure avoids installing Docker and avoids
an architecture mismatch if you are on an Apple Silicon Mac.

**Portal → Cloud Shell** (the `>_` icon in the top bar), then:

```bash
git clone <your-repository-url> decision-studio
cd decision-studio
az acr build -r <your-registry-name> -t decision-studio:latest .
```

**This takes 5–10 minutes** — it installs the frontend dependencies, bundles
them, and installs the Python ones. Wait for `Run ID ... succeeded`.

---

### Step 5 — Web App

**Portal → App Services → Create → Web App**

*Basics:*

| Field | Value |
|---|---|
| Name | `decision-studio` + digits (becomes `<name>.azurewebsites.net`) |
| Publish | **Container** |
| Operating System | **Linux** |
| Region | the same one |
| Pricing plan | **B1 Basic** |

B1 is the smallest tier that stays warm. Below it the container is evicted
between requests, and every cold start re-runs the migrations.

*Container:*

| Field | Value |
|---|---|
| Image source | **Azure Container Registry** |
| Registry | the one from step 4 |
| Image | `decision-studio` |
| Tag | `latest` |

Review + create.

---

### Step 6 — Configuration

**Your Web App → Settings → Environment variables → App settings**

Add each of these with **+ Add**:

| Name | Value |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://dsadmin:<PASSWORD>@decision-studio-pg.postgres.database.azure.com:5432/decision_studio?ssl=require` |
| `OPENAI_API_KEY` | your key |
| `EMBEDDING_API_KEY` | the same key |
| `LLM_PROVIDER` | `openai` |
| `LLM_MODEL` | `gpt-4o` |
| `BRAVE_SEARCH_API_KEY` | your key, or leave it out |
| `CORS_ORIGINS` | `["https://<your-app-name>.azurewebsites.net"]` |
| `WEBSITES_PORT` | `8000` |
| `WEBSITES_CONTAINER_START_TIME_LIMIT` | `600` |

**Apply**, and confirm the restart.

Three of those are easy to get wrong and fail in ways that do not point at the
cause:

- **`?ssl=require`**, not `sslmode=require`. The driver is asyncpg, which uses a
  different spelling; the libpq one fails with an opaque parse error.
- **`WEBSITES_PORT`**. App Service ignores the container's `EXPOSE` and would
  probe port 80, reporting a perfectly healthy container as failed.
- **`WEBSITES_CONTAINER_START_TIME_LIMIT`**. The first boot runs twelve
  migrations, which exceeds the 230-second default.

Then **Settings → Configuration → General settings**:

- **Always on**: On — otherwise a long generation is cut by the idle timeout
- **Web sockets**: On — the pipeline streams progress over WebSocket

---

### Step 7 — Check it

**Your Web App → Monitoring → Log stream.** You should see alembic apply
migrations 001 to 012, then uvicorn start. Give it 2–3 minutes.

Then open `https://<your-app-name>.azurewebsites.net`.

If the page loads, everything downstream of it works: the frontend is served by
the same process as the API, so there is no second thing to verify.

---

### Redeploying after a change

**Cloud Shell:**

```bash
cd decision-studio && git pull
az acr build -r <your-registry-name> -t decision-studio:latest .
```

Then **Web App → Overview → Restart**.

Migrations run at startup and are idempotent, so a restart with nothing pending
is a no-op.

---

### When something goes wrong

| Symptom | Cause |
|---|---|
| Container never starts | `WEBSITES_PORT=8000` missing |
| `type "vector" does not exist` in the log | pgvector not enabled — step 3, both halves |
| `invalid dsn` at startup | `sslmode=require` instead of `?ssl=require` |
| Startup times out during migrations | `WEBSITES_CONTAINER_START_TIME_LIMIT=600` missing |
| Cannot reach the database | The "allow Azure services" tick in step 2 |
| Analysis stops halfway, no error | **Always on** is off |
| No progress shown during analysis | **Web sockets** is off |
| Slow first request after idle | Below B1 the container is evicted; use B1 or higher |
| `column ... does not exist` on a fresh database | Migrations behind the models — `tests/test_schema_drift.py` catches this before you deploy |

### Once it works

Move the keys out of app settings:

**Key Vault → Secrets**, then reference them:

```
@Microsoft.KeyVault(SecretUri=https://<vault>.vault.azure.net/secrets/openai-key/)
```

The Web App needs a system-assigned managed identity with **Get** permission on
the vault.

### Running cost

| | Monthly |
|---|---|
| App Service B1 | ~€13 |
| PostgreSQL B1ms, 32 GiB | ~€15 |
| Container registry, Basic | ~€5 |
| **Infrastructure** | **~€33** |

The model is the larger figure. One analysis of a substantial document runs to
several dollars, and theory generation, the adversary, debates and experiments
each add more. Budget for the LLM, not the hosting.

### Scaling, and what breaks first

The app is stateless, so **Scale out** works. Two things to know before relying
on it:

- **Simultaneous starts both run migrations.** Alembic takes a lock, so the
  second waits rather than corrupting anything — but a slow migration delays
  every instance.
- **Concurrent editing is optimistic.** Review operations carry
  `expected_graph_revision` and return 409 when the graph has moved on. Two
  people editing the same project get conflicts, not a merge. Multi-user
  editing was out of scope.

The database is the first real constraint: B1ms is a single vCPU. Belief
propagation and Monte Carlo run in the app, but claim extraction writes heavily
— move to a General Purpose tier before adding instances.

### Doing this from the command line instead

`deploy-azure.sh` performs all of the above and is idempotent, so a re-run after
a failure continues rather than starting over:

```bash
export PG_PASSWORD='...' OPENAI_KEY='...'
./deploy-azure.sh
```

## Three-Layer Causal Analysis

Decision Studio also provides a standalone causal analysis mode (`/causal`) for quick, data-driven analysis:

| Input | What Happens |
|-------|-------------|
| **Text** | LLM-only causal reasoning — instant hypotheses with confidence tiers |
| **CSV/Excel** | Granger causality + PC algorithm (Layer 3) combined with LLM reasoning (Layer 1). Edges are tagged with statistical p-values and cross-validated |
| **Screenshot** | Claude Vision extracts data from charts/dashboards, then runs the same statistical + LLM pipeline |

Results show fused edges with four confidence tiers:

| Tier | Visual | Meaning |
|------|--------|---------|
| **Confirmed** | ━━━━▶ solid thick green + glow | Statistically significant (p<0.05) and LLM agrees |
| **Supported** | ────▶ solid blue | Multi-layer consensus |
| **Hypothesis** | - - -▶ dashed amber | LLM inference only, no statistical data |
| **Unverified** | · · ·▶ dotted grey | Insufficient evidence |

Two view modes: **Conclusion** (default, for PMs — shows fused verdicts) and **Layer** (for analysts — side-by-side comparison of what statistics found vs what LLM inferred).

## Usage

1. **Enter text** — Paste a scenario, article, or hypothesis (or pick a demo scenario)
2. **Watch the pipeline** — Claims stream in live as the engine decomposes and traces causal chains
3. **Explore the graph** — Interactive force-directed graph with zoom, click to expand/collapse nodes
4. **Inspect evidence** — Click edges to see supporting/contradicting evidence with source links
5. **Check statistical validation** — Edges with numeric data show p-values and Granger test results alongside LLM evidence
6. **Stress-test assumptions** — Right-click edges to modify causal strength; beliefs re-propagate in real-time
7. **Fork scenarios** — Create what-if branches, compare side-by-side or as overlay
8. **Quick causal analysis** — Use the `/causal` page to upload CSV or screenshots for instant three-layer analysis
9. **Export** — Download as JSON, Markdown report, or interactive HTML

## Project Structure

```
decision_studio/
├── api/
│   ├── models/          # Request/response schemas (analysis, graph, scenarios)
│   └── routes/          # analysis, graph, scenarios, export, operations
├── db/                  # SQLAlchemy models and session
├── evidence/            # Brave Search client, source credibility scoring
├── graph/               # Belief propagation, sensitivity, critical path, scenario diff, focus, path finder
├── llm/
│   ├── prompts/         # Structured prompts (claim extraction, causal inference, evidence, bias, discovery, strategic advisor)
│   ├── client.py        # LLM client abstraction (OpenAI/Anthropic)
│   └── embeddings.py    # Embedding generation
├── statistical/         # Granger causality, PC algorithm (CPU-based, no GPU required)
├── pipeline/            # Orchestrator + stages: extract → infer → ground → validate → build → propagate, bias audit, discovery
├── config.py            # Pydantic Settings
├── exceptions.py        # Custom error classes
└── main.py              # FastAPI app entry point

frontend/src/
├── components/
│   ├── input/           # InputScreen, DemoScenarios, CausalAnalysisScreen
│   ├── processing/      # ProcessingScreen, PipelineStream, ClaimStream, EdgeStream, EvidenceStream, StageTimeline
│   ├── tree/            # ForceGraph, GraphScreen, GraphListScreen, EvidencePanel, NodeDetailPanel, EdgeBundlePanel,
│   │                    # ClaimsBrowser, MiniMap, GraphTooltip, StrategicAdvisorPanel, TimelineView, TimeScrubber,
│   │                    # CausalAnalysisGraph (three-layer visualization)
│   ├── scenario/        # ScenarioForge, ComparisonView, MergeOverlay
│   ├── export/          # ExportPanel
│   ├── layout/          # AppLayout
│   └── ui/              # Button, Card, Badge, Slider, Progress, Textarea, Tooltip, LoadingSpinner, ResizablePanel, ErrorBoundary
├── context/             # AnalysisContext (useReducer state management)
├── hooks/               # useForceLayout, useSSEStream, useGraphWebSocket, useGraphOperations,
│                        # useKeyboardNavigation, useResizablePanel, useScenario, useTemporalBeliefs, useTheme
├── i18n/                # Internationalization (en, zh)
├── lib/
│   ├── api/             # HTTP client, SSE helper, WebSocket helper
│   ├── graphUtils.ts    # Graph layout utilities
│   └── visualConstants.ts
└── types/               # TypeScript interfaces (api, graph)
```

## License

MIT
