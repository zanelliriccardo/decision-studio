# Decision Studio Decision Reasoning — Implementation Summary

Decision Studio now runs the full loop: **documents → causal graph → theories → clarification
questions → human review → regeneration → decision**. The graph remains the traceable
foundation; it is no longer the final output.

---

## 1. Architecture summary

### Revision strategy: current-state fields + immutable audit table

Decision Studio already had two mutation mechanisms, and neither could host authoritative
human review:

| Existing mechanism | Why it wasn't reused for review |
|---|---|
| `Scenario.edge_overrides` (JSON) | Hypothetical what-if forks. Storing human corrections here would make them look like speculation. |
| `GraphOperations` service (expand / trace-back / challenge) | Appends new claims and edges; keeps no audit trail and has no concept of rejecting an element. |

So review state lives on the entities (matching the repo's own convention — `is_feedback`,
`statistical_validation` are columns on `causal_edge`), and every mutation appends an
immutable `graph_operation` row carrying before/after snapshots:

```
claim.review_status, .is_active, .user_note, .reviewed_at
causal_edge.review_status, .is_active, .user_note, .strength_override, .reviewed_at
project.graph_revision   ← bumped by every review operation
graph_operation          ← immutable audit + undo log
```

This buys all four required properties: **undo** (replay `before_state`), **reproducibility**
(a theory pins the `graph_revision` it used), **comparison** (theory versions keyed by
`theory_key`), and **staleness** (`theory.graph_revision < project.graph_revision`).
Documented in a comment block in `decision_studio/db/models.py`.

### The effective graph

`decision_studio/reasoning/effective_graph.py` is the single definition of "the reviewed graph":

- an element must be active and not `rejected` / `not_relevant`;
- an edge additionally requires both endpoints to survive — a dangling edge is not a causal link;
- `strength_override` beats `strength`.

**Reasoning** sees only the effective graph. **The screen** still shows everything, dimmed and
badged — rejecting a claim must never erase the evidence of why it was there.

### Reference tokens instead of UUIDs

The LLM cites graph elements as `C3`, `E7`, `V2` rather than 36-character UUIDs. This cuts
prompt size substantially and, more importantly, makes fabrication *structurally* detectable:
an invented token simply fails to resolve in `ReferenceMap`, so hallucinated provenance cannot
reach the database. Validation drops unresolvable references, and drops any theory left with
no claims *and* no edges.

Queries in `load_effective_snapshot` are explicitly ordered because token assignment is
positional — an unordered result set would give the same graph different tokens on different
runs, making a generation impossible to reproduce from its recorded revision.

### Generation caching is deliberately off

`get_llm_client(enable_cache=False)` for both generators. The semantic cache matches on prompt
*similarity* at 0.92, and a one-edge review edit barely moves a large prompt — a cache hit
would silently return theories built on the pre-edit graph. That is the exact failure the
feature exists to prevent.

---

## 2. Reused Decision Studio components

| Component | How it is reused |
|---|---|
| `LLMClient` / `complete_json` + `get_llm_client` | Both generators go through the existing provider abstraction. No provider-specific code was added. |
| Prompt module convention (`*_SYSTEM` + `*_SCHEMA`) | `theory_generation.py` and `clarification.py` follow it exactly. |
| `language_instruction()` | Appended to every generation prompt, so output stays in the project language. |
| `find_critical_path()` | Drives subgraph selection for large graphs. |
| `_load_project_graph` / `_assemble_graph_response` | Extended in place with review fields; existing callers (scenarios, operations) unaffected. |
| Focus mode (`SET_FOCUS`, `focusVisibleIds`, `focusPaths`) | Theory path highlighting reuses it wholesale — highlighting is view state, never a graph mutation. No new highlight system, no `ForceGraph` rewrite. |
| `ResizablePanel`, `Slider`, `Progress`, `Badge` | Used unchanged by the new panels. |
| `useGraphOperations` transformer + `apiGet/apiPost/apiPatch` | Extended; the new API client layers on top. |
| `NodeDetailPanel` / `EvidencePanel` | Extended with an optional `onReview` prop rather than replaced. |
| i18n (`en` / `zh`) | New keys added to both locales. |

**Not touched, as required:** the scenario engine, Strategic Advisor, belief propagation,
bias audit, evidence grounding, the pipeline, and the graph visualization's layout logic.

---

## 3. Files changed and created

### Backend — created
```
alembic/versions/004_decision_reasoning.py    reversible migration
decision_studio/reasoning/__init__.py
decision_studio/reasoning/effective_graph.py         what review left standing
decision_studio/reasoning/review.py                  reversible ops + audit + staleness
decision_studio/reasoning/context_builder.py         compact prompt, ref tokens, selection
decision_studio/reasoning/validation.py              pure validation/repair of LLM output
decision_studio/reasoning/theories.py                generation, versioning, diffing
decision_studio/reasoning/clarifications.py          questions, lifecycle, apply
decision_studio/llm/prompts/theory_generation.py
decision_studio/llm/prompts/clarification.py
decision_studio/api/models/reasoning.py
decision_studio/api/routes/reasoning.py              18 endpoints
```

### Backend — modified
```
decision_studio/db/models.py         review columns + 10 new models
decision_studio/api/models/graph.py  review fields on claim/edge responses
decision_studio/api/routes/graph.py  populate review fields, effective_strength, graph_revision
decision_studio/main.py              register the reasoning router
pyproject.toml                document TEST_DATABASE_URL
```

### Frontend — created
```
src/types/reasoning.ts                          types + wire formats
src/lib/api/reasoning.ts                        API client + transformers
src/hooks/useReasoning.ts                       reasoning state
src/components/tree/TheoryPanel.tsx
src/components/tree/ClarificationPanel.tsx
src/components/tree/ReviewControls.tsx          shared by both detail panels
src/test/setup.ts, src/test/fixtures.ts
vitest.config.ts
```

### Frontend — modified
```
src/types/graph.ts            review fields on nodes/edges, graphRevision
src/components/tree/GraphScreen.tsx     toolbar, panels, theory highlighting, transformers
src/components/tree/NodeDetailPanel.tsx review controls + status badge
src/components/tree/EvidencePanel.tsx   review controls + status badge
src/components/tree/ForceGraph.tsx      review visual semantics
src/hooks/useGraphOperations.ts         transformer fields
src/i18n/en.ts, src/i18n/zh.ts          new strings, both locales
package.json                            test scripts + vitest devDependencies
```

### Tests — created
```
tests/conftest.py                fixtures, FakeLLMClient
tests/test_effective_graph.py    18 pure tests
tests/test_validation.py         37 pure tests
tests/test_review.py             39 DB tests
tests/test_theories.py           21 DB + mocked-LLM tests
tests/test_clarifications.py     30 DB + mocked-LLM tests
tests/test_api_reasoning.py      38 HTTP tests
frontend/src/components/tree/__tests__/{TheoryPanel,ClarificationPanel,ReviewControls}.test.tsx
frontend/src/lib/api/__tests__/reasoning.test.ts
```

---

## 4. API surface (18 endpoints, existing `/api/v1/graph/{project_id}` convention)

**Review** — `PATCH .../claims/{id}/review`, `PATCH .../edges/{id}/review`,
`GET .../graph-operations`, `POST .../graph-operations/{id}/undo`,
`GET .../graph-revision`, `PATCH .../decision-objective`

**Theories** — `POST .../theories/generate`, `POST .../theories/regenerate`,
`GET .../theories`, `GET .../theories/{id}`, `GET .../theories/{id}/versions`,
`GET .../theory-revisions`

**Clarifications** — `POST .../clarifications/generate`, `GET .../clarifications`,
`PATCH .../clarifications/{id}`, `POST .../clarifications/{id}/answer`,
`GET .../clarifications/{id}/impact`, `POST .../clarifications/apply`

Review endpoints accept `expected_graph_revision` and return **409** when the graph has moved on.

---

## 5. Commands

```bash
# Database (needs PostgreSQL with pgvector)
createdb decision_studio && psql -d decision_studio -c 'CREATE EXTENSION IF NOT EXISTS vector'
uv run alembic upgrade head            # 003 -> 004
uv run alembic downgrade 003           # fully reversible

# Backend
uv run uvicorn decision_studio.main:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev

# Tests
createdb decision_studio_test && psql -d decision_studio_test -c 'CREATE EXTENSION IF NOT EXISTS vector'
TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/decision_studio_test uv run pytest
cd frontend && npm test
```

**Results:** 183 backend tests pass, 89 frontend tests pass. No test contacts an LLM or search
provider. Without a database the 121 DB-backed tests skip and the 62 pure-logic tests still run.

---

## 6. Design decisions where the spec met the repository

1. **Single `review_status` field.** The spec's TypeScript type is a single union, so
   `business_critical` and `needs_evidence` are statuses rather than independent flags. An
   element can't be both business-critical and uncertain at once — a limitation, noted below.

2. **Review columns on entities, not a polymorphic review table.** Normalized review rows
   would have required a join in `_load_project_graph`, which scenarios and graph operations
   also call. Columns keep the hot path untouched and match the repo's convention.

3. **Every regenerated theory gets a new row and an incremented `version`**, including
   `unchanged` ones, so each `theory_revision` is a complete, inspectable set. `change_kind`
   records whether content actually moved.

4. **Theory matching falls back to causal-path overlap** (Jaccard ≥ 0.6 on edge sets) when the
   model omits `previous_theory_key` — otherwise a forgetful model silently forks every theory.

5. **Fixed a pre-existing bug.** `GraphScreen` was PATCHing
   `/api/v1/graph/{projectId}/edges/{edgeId}`, which does not exist on the backend — strength
   edits 404'd and were lost on reload. They now route through the reviewed, audited override
   path. Also fixed the `transformNode` type error that broke `tsc -b` on the untouched baseline.

---

## 7. Known limitations

1. **Review statuses are mutually exclusive.** Marking a claim `business_critical` overwrites
   `needs_evidence`. Splitting flags from status would need a schema change; deferred because
   the spec's own type is a single union.

2. **Edge direction reversal is not implemented.** The spec asks for it "only through an
   explicit operation that validates graph consistency". Reversing an edge can create a cycle,
   which interacts with `_break_cycles`, belief propagation and feedback-edge handling — enough
   surface area to deserve its own change. Mechanism editing *is* implemented.

3. **Question deduplication is lexical, not semantic.** Fingerprint plus token-overlap (Jaccard
   ≥ 0.7) catches rewordings but not paraphrases with disjoint vocabulary. The repo has an
   `EmbeddingService`; embedding-based dedup would be the natural upgrade.

4. **Graph-change proposals from answers are keyword-based.** `_graph_change_proposals` looks
   for negation markers in English and Chinese and only ever proposes reviewing elements the
   question was already linked to. It is deliberately conservative — it never invents targets,
   and it never applies anything.

5. **Theory highlighting reuses focus mode**, which also sets the view mode. Clearing the
   highlight returns to panorama rather than the exact previous view.

6. **No streaming for generation.** Theory generation is a single request; a large graph can
   take 20–40 s with no progress indication beyond the spinner. The repo has SSE infrastructure
   (`events.py`) that could carry progress.

7. **Concurrency is optimistic and last-write-wins within a revision.** `expected_graph_revision`
   catches stale edits, but two users editing simultaneously will see 409s rather than a merge.
   Multi-user editing was explicitly out of scope.

8. **Subgraph selection thresholds are heuristic** (60 claims / 120 edges, additive weights).
   They are not tuned against real large projects, and the weights encode a judgement — human
   signals dominate structural ones — rather than a measured optimum.

9. **The frontend baseline does not typecheck.** 32 pre-existing errors remain in files this
   work did not need to touch (`StrategicAdvisorPanel`, `CausalAnalysisScreen`, `ScenarioForge`,
   `EdgeBundlePanel`). This change fixed one and introduced none, but `npm run build` still
   fails on the untouched baseline and will continue to until those are addressed.

---

## 8. Definition of Done

| # | Requirement | Covered by |
|---|---|---|
| 1–2 | Project opens, graph generates as before | `TestExistingEndpointsStillWork` |
| 3 | Generate decision-oriented theories | `TestTheoryEndpoints::test_generate_returns_theories` |
| 4 | Highlight supporting path and evidence | `TheoryPanel.test.tsx` path-highlighting suite |
| 5 | Disable, reject, annotate nodes and edges | `test_review.py` (39 tests) |
| 6 | Generate clarification questions | `test_clarifications.py::TestGeneration` |
| 7 | Answer or dismiss questions | `TestAnswering`, `TestLifecycle` |
| 8 | Theories marked stale after relevant changes | `TestStalenessPropagation`, `test_editing_the_graph_marks_theories_stale` |
| 9–10 | Explicit regeneration, new version, change summary | `TestRegeneration` (8 tests) |
| 11 | Regeneration uses only the effective graph and accepted answers | `test_a_theory_cannot_cite_a_rejected_element`, `test_answers_appear_in_the_next_generation_prompt` |
| 12 | Previous revisions remain inspectable | `test_versions_endpoint_lists_history`, `test_a_dropped_theory_is_marked_superseded_not_deleted` |
| 13 | Existing graph, scenario and advisor features still work | `TestExistingEndpointsStillWork`, unchanged scenario/advisor routes |
