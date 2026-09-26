# Dead code report

Nothing listed here has been deleted. Each candidate is marked in the source with
a comment carrying its ID, so you can find it, read the reason, and decide:

```bash
grep -rn "DEAD-CODE-CANDIDATE" decision_studio frontend/src      # every marker
grep -rn "DEAD-CODE-CANDIDATE DC-24" decision_studio frontend/src # one candidate
```

A marker is always the line directly above what it refers to, or the first line
of the file when the whole file is the candidate (`[module]`, `[file]`).

## How the candidates were found

1. **Backend modules**: an import graph (AST, including imports inside functions)
   walked from `decision_studio/main.py` and the `tools/` entry points. Anything
   not reached is unreachable from the running app.
2. **Backend symbols**: `vulture --min-confidence 60`, ignoring FastAPI route
   decorators and Pydantic fields (which the framework uses by name), then every
   hit checked by `grep` across backend and frontend.
3. **API endpoints**: every route of the app compared with the paths the frontend
   calls. An endpoint without a caller may still be used from outside (scripts,
   integrations), so these are listed separately.
4. **Frontend files**: an import graph walked from `src/main.tsx`.
5. **Frontend symbols and tests**: checked by `grep`.

Verification after marking: the app imports, `pytest` passes (70), `tsc` reports
no new errors, the frontend builds.

## Why it matters beyond tidiness

* **62 of the 90 pre-existing TypeScript errors** come from dead code: 58 in the
  dead frontend files (DC-31 to DC-39) and 4 in stale tests (DC-41). Deleting them
  makes `npm run build` (which runs `tsc -b`) nearly usable as a signal again; the
  remaining 28 are in live files (25 in `StrategicAdvisorPanel.tsx`).
* **11 of the 16 pre-existing failing frontend tests** test dead code (DC-35, DC-36,
  DC-41). The other 6 were stale tests of the live intake screen and are fixed in
  this change (see `docs/LOGIC_REVIEW.md`).
* **DC-01 cannot even be imported**: it references a model deleted in migration 016.

## Candidates

Confidence: **high** = nothing in the repository reaches it; **medium** =
reachable only through an endpoint no frontend calls (external callers possible);
**decide** = works, but a feature is orphaned and wiring it may be the better fix.

### Backend: whole modules (about 3,100 lines)

| ID | File | Lines | Why | Confidence |
|---|---|---|---|---|
| DC-01 | `reasoning/frame_service.py` | 419 | Imports `DecisionFrame`, removed in migration 016: the module raises on import. Nothing imports it | high |
| DC-02 | `reasoning/framing.py` | 364 | 15-question framing catalogue (removed). Imported only by DC-01, DC-03 | high |
| DC-03 | `reasoning/domains.py` | 410 | Domain templates for the removed framing. Imported only by DC-01 | high |
| DC-04 | `llm/prompts/domain_questions.py` | 99 | Prompt for DC-01 | high |
| DC-05 | `reasoning/clarifications.py` | 465 | Clarification system, removed (HANDOVER §4.9) | high |
| DC-06 | `llm/prompts/clarification.py` | 119 | Prompt for DC-05 | high |
| DC-07 | `pipeline/intake_questions.py` | 247 | First intake (paused the run), replaced by `reasoning/intake.py` | high |
| DC-08 | `llm/prompts/intake_questions.py` | 108 | Prompt for DC-07 | high |
| DC-09 | `pipeline/stage_context.py` | 171 | Never wired. Stage cost attribution now happens in `CausalPipeline._emit` | high |
| DC-10 | `pipeline/deprecated_stage_context.py` | 193 | Older copy of DC-09 | high |
| DC-11 | `llm/prompts/deprecated_evidence_search.py` | 119 | Prompt of an earlier grounder | high |
| DC-12 | `llm/prompts/evidence_search.py` | 107 | Not imported; the grounder builds queries in code | high |

When removing DC-01 to DC-08, the `alembic/versions` files that mention those
tables must stay: migrations are history.

### Backend: symbols

| ID | Where | Why | Confidence |
|---|---|---|---|
| DC-13 | `evidence/nli_scorer.py` `score_evidence_nli` | No callers | high |
| DC-14 | `exceptions.py` `ValidationError` | Never raised or caught | high |
| DC-15 | `graph/belief_propagation.py` `compute_belief_intervals` | Docstring says DEPRECATED; replaced by `graph/stability.py` | high |
| DC-16 | `graph/stability.py` `rank_stability` | No callers | high |
| DC-17 | `llm/cache.py` `cache_stats` | No callers | high |
| DC-18 | `llm/model_params.py` `reset_cache` | No callers (likely a helper for tests not in the repo) | medium |
| DC-19 | `reasoning/calibration.py` `band_range`, `round_for_display`, `interval_is_informative` | No callers | high |
| DC-20 | `reasoning/authoring.py` `undo_addition` | No route or caller; undo uses `review.undo_operation` | high |
| DC-21 | `reasoning/effective_graph.py` `_Reviewable` | Typing protocol referenced nowhere | high |
| DC-22 | `api/models/reasoning.py` `AnswerResponse`, `QuestionStatusRequest`, `ProposedGraphChange` | Clarification-system models; no route uses them | high |
| DC-23 | `reasoning/authoring.py` `recompute_beliefs` (+ `POST /recompute`, + frontend `api.recompute`) | **Runs but has no effect**: it propagates and discards the result. Beliefs are recomputed on every graph read | high |

### Backend: API surface with no frontend caller

| ID | Endpoint / file | Why | Confidence |
|---|---|---|---|
| DC-24 | `api/routes/causal_analysis.py` (3 `deprecated_*` endpoints) and `pipeline/three_layer_engine.py` | Screen removed; the URL was kept on purpose as a public contract (HANDOVER §6). Remove once you know nothing external calls it | medium |
| DC-25 | `POST /analyze/{id}/resume` | Checkpoint resume is not reachable from the UI | medium |
| DC-26 | `PATCH /edge/{edge_id}` | No caller, and it **bypasses the review audit log**: strength edits should go through `PATCH …/edges/{id}/review` | medium (worth removing: it's an unaudited write path) |
| DC-27 | `api/routes/events.py` (whole `/api/v1/events` router) | No caller | medium |
| DC-28 | `POST …/experiments/synthetic`, `POST …/experiments/{id}/execute` | Synthetic stakeholder experiments have no UI | decide: wire into the theory panel or remove |
| DC-29 | `POST/GET …/outside-view` | **Orphaned feature**: needs the user's recollection of comparable cases, and no screen collects it | decide: recommend wiring (one text box) |
| DC-30 | tables `multi_layer_evidence`, `metric_series` | Written only by DC-24. Dropping needs a migration | medium |

### Frontend: files unreachable from `main.tsx` (about 3,360 lines)

| ID | File | Lines | Note |
|---|---|---|---|
| DC-31 | `components/input/CausalAnalysisScreen.tsx` | 679 | No route renders it |
| DC-32 | `components/tree/CausalAnalysisGraph.tsx` | 520 | Used only by DC-31 |
| DC-33 | `components/processing/IntakeQuestions.tsx` | 191 | First intake UI |
| DC-34 | `components/processing/QuestionsScreen.tsx` | 85 | |
| DC-35 | `components/processing/QuestionsStep.tsx` (+ its test) | 473 | Test failing |
| DC-36 | `components/tree/ClarificationPanel.tsx` (+ its test) | 593 | Test failing |
| DC-37 | `components/tree/FramingPanel.tsx` | 345 | |
| DC-38 | `components/settings/ProfileScreen.tsx` | 215 | Decision profile removed in migration 016 |
| DC-39 | `components/scenario/ReportsScreen.tsx` | 259 | No route renders it |

### Frontend: symbols and tests

| ID | Where | Why |
|---|---|---|
| DC-40 | `lib/api/client.ts` `deprecatedAnalyzeText/CSV/Screenshot` | No callers (wrappers for DC-24) |
| DC-41 | `lib/api/__tests__/reasoning.test.ts`: `transformQuestion`, `clarification endpoints` blocks | Test functions that no longer exist; 5 of the pre-existing failures and 4 of the TS errors |

After removing DC-05/06/22/35/36/41, the `clarifications` and `questions`
sections of `i18n/en.ts` and `i18n/zh.ts` become unused too. They're not marked,
because a comment inside a translation object would be noise.

## Suggested order

1. **DC-01 to DC-12, DC-31 to DC-39, DC-41**: nothing reaches them. Removing them
   clears most of the TS errors and failing tests. Lowest risk, largest gain.
2. **DC-26**: remove soon. It's an unaudited write path.
3. **DC-13 to DC-23, DC-40**: small, safe.
4. **DC-24, DC-25, DC-27, DC-30**: confirm nothing external uses them first.
5. **DC-28, DC-29**: product decisions. The review recommends wiring DC-29.
