# Logic review

A quality check of the reasoning chain against its goal, which is Aristotle's
(Bocconi IMSL): help a manager state a **decision**, build a **theory** of why an
option would or would not reach the outcome (a causal map with conviction), and
**test** the weakest links before committing.

Part 1 lists what was wrong and has been fixed, with the file and the test that
guards it. Part 2 lists what is still weak, ranked by how much it matters to
that goal, with a proposed fix. Dead code is in `docs/DEAD_CODE_REPORT.md`.

## Part 1: bugs found and fixed

| # | What was wrong | Effect on the user | Fix | Test |
|---|---|---|---|---|
| F1 | `has_contradiction` was set on edges but never read by propagation | A link contradicted by evidence scored the same as a link nobody had searched for: contradicting evidence did not lower belief | `graph/belief_propagation.py` (OR and AND gates) and `graph/stability.py` pass the flag to `_evidence_modulation` | `test_review_fixes.py::TestContradictionReachesPropagation` |
| F2 | The graph endpoint built the network from **all** claims and edges, with the model's strength | Rejected claims and links still moved beliefs on screen; the user's strength overrides and link confidence were ignored. The graph the user saw disagreed with the theories and the brief (which used the reviewed graph) | `api/routes/graph.py::_build_nx_graph` goes through `filter_effective` and `effective_strength`, and carries `link_confidence` | `TestDisplayedGraphHonoursReview::test_rejected_elements_and_overrides` |
| F3 | A scenario's strength lost to a stored override | "What if this link were 0.9?" showed nothing when the user had overridden the link earlier | `api/routes/scenarios.py::_apply_overrides` clears the override on the patched copy (the stored edge is untouched) | `test_scenario_value_beats_override` |
| F4 | Observing a tripwire twice added its likelihood ratio twice | Conviction moved twice for one observation (e.g. an edit of the observed value) | `reasoning/theory_value.py::record_evidence` replaces the previous belief row from the same source | `test_theory_value_db.py` (re-record tripwire once) |
| F5 | On regeneration a theory matched its predecessor by shared links only | "Q3 **achieves** Y1" could inherit the conviction stated for "Q3 **threatens** Y1", or for another option, because both read the same links | `reasoning/theories.py::_same_claim`, used by `match_previous`: option and predicted effect must agree (unknown on either side still matches, for older theories) | `TestTheoryMatching` |
| F6 | Regeneration orphaned commitments | Pending tripwires and designed field tests stayed attached to the superseded theory and disappeared from the panel and the brief | `reasoning/theories.py` re-points pending `TheoryTripwire` and field `Experiment` rows to the successor | `test_theory_value_db.py` (tripwires/field carried on regeneration) |
| F7 | Saving the anchor unchanged (e.g. only the status moved from draft to confirmed) re-scored every claim | A slow, paid re-run of outcome pairing that changed nothing | `reasoning/anchor_service.py::_content` compares without `status` | `test_anchor_pipeline_db.py` (re-save no rescore) |
| F8 | `llm/usage.py` had lost the `def` lines of `current_ledger` and `set_stage`, and nothing set the stage | Every model call was booked under "other": the per-stage cost view was meaningless | Restored both; `pipeline/orchestrator.py::_emit` sets the stage when a stage starts | `test_usage_is_attributed_to_the_running_stage` |
| F9 | The adversary (objections) and tripwires existed but never ran, and the UI had no trigger | Theories reached the user with no case against them and no dated test: the "try to prove it wrong" half of the method was missing | `api/routes/analysis.py::_generate_downstream` runs both after theory generation (each in its own session, failure is non-fatal); `GraphScreen` wires Challenge / Generate tripwires / Dismiss objection / Observe tripwire in the theory panel | backend suite + manual run |
| F10 | The theory prompt asked for 3 to 7 theories with no link to the options | With two or three options it rarely produced a case for **and** against each, so options went unexamined | `llm/prompts/theory_generation.py`: 3 to 8, "enough for a case for and against each option" | the brief now warns when an option is not examined |
| F11 | Intake: a mis-clicked option could not be cleared, and every answer was sent with an empty `text` beside the `choice` | An empty string reached every prompt as if the user had answered; a mis-click could only be fixed by typing over it | `IntakeScreen.tsx`: clicking the selected option clears it; only the answered field is sent | `IntakeScreen.test.tsx` (20/20) |

## Part 2: what is still weak, and how to improve it

Ranked by distance from the Aristotle goal: the first items decide whether the
tool actually compares options; the last are cost and polish.

**Status (items 1 to 8 implemented).** Each item below keeps its original
analysis; what was built is in the table. Tests: `tests/test_improvements.py`
(unit) and `tests/test_improvements_db.py` (database). Migration `024` adds the
columns.

| Item | What was built | Where |
|---|---|---|
| 1 Options compared by the model | Each option applied as an intervention on its levers (claims tagged `lever` bearing on it: on for it, off for the others, incoming links cut), the map propagated, success criteria read; repeated with link weights varied for ranges and a win rate. Summary card, report table, "Map favours" key number | `reasoning/option_comparison.py`, `graph/stability.compare_options`, `GET …/options/compare`, `OptionForecastCard.tsx`, `brief_view.build_forecast` |
| 2 Correlated evidence | Observations can name the event they came from; per theory one event counts once (the strongest); an event already known when the prior was restated counts not at all. History shows "N observations, M independent" | `theory_value.replay`, `theory_belief.event`, `EventField.tsx`, `GET …/observation-events` |
| 3 Outside view | Summary-page box for comparable cases (saved on the project); each theory matched with a polarity, compared against the decider's conviction and recomputed on every read; kept across regeneration; re-checked after automatic generation | `outside_view.compare` / `current_comparison`, `ComparableCases.tsx`, `POST/GET …/outside-view` |
| 4 Data validation | A pasted two-column table tests one link: Granger forward and reverse when rows are in time order, else Spearman with the predicted sign. Nothing significant is inconclusive, never refuted | `reasoning/link_data.py`, `POST …/hypotheses/{id}/data`, `DataTestForm.tsx` |
| 5 Recompute | The frontend no longer calls `POST /recompute` before reloading the graph. The endpoint and function stay, marked DC-23, for you to remove | `hooks/useReasoning.ts` |
| 6 Noisy-OR independence | Where a node's causes share a driver within two hops, a second propagation combines them as one cause; the gap is carried downstream and shown in the claim panel with the shared claims named | `graph/shared_causes.py`, `ClaimResponse.belief_if_dependent`, `NodeDetailPanel.tsx` |
| 7 Ranking | One order everywhere: reaches a success criterion, current before stale, then conviction when stated, else the objection-discounted score. `business_impact` sorts nothing | `theories.rank_key` |
| 8 Weights | Tripwires and link tests take a decisiveness (a little / moderately / decisively) stated before the result and locked after it; it sets the likelihood ratio. Moderate equals the old fixed value | `theory_value.tripwire_likelihood`, `link_tests.result_likelihood`, `DecisivenessPicker.tsx` |

Item 9 (latency and cost) is not done.

One finding made along the way: the POST outside-view endpoint called
`extract_reference_cases` without the recollection it needs, so even an
external caller always got no cases. Fixed with item 3.

### 1. Options are compared by argument, not by the model (high)

Each theory says "option O1 achieves/threatens Y1", and the brief now lays out
the case for and against each option. But nothing computes **what the causal
graph predicts for Y1 if O1 is chosen versus O2**. The numbers the user sees are
beliefs in claims under the current situation, not under an option.

*Proposal*: treat each option as an intervention. The scenario engine already
patches strengths and the stability module already runs Monte Carlo
(`compare_stability`). For each option: set the option node to 1 (others to 0),
cut its incoming edges (a do-intervention), propagate, and report P(Y) per
outcome with its interval, plus how often O1 beats O2 across samples ("win
rate"). That becomes the first table of the brief. Cost: no model calls.
`graph/stability.py::rank_stability` (marked DC-16) already ranks several option
graphs with a win rate; keep it if this is built.

### 2. Correlated evidence is counted as independent (high)

Conviction is updated in odds form from each observation's likelihood ratio.
When a tripwire and a link test observe the same event, or two link tests share
a source, the ratio is applied twice and conviction overshoots.

*Proposal*: record the event/source each observation comes from and apply only
the strongest ratio per event per theory (or damp the second by a correlation
factor). Show "2 observations, 1 independent" in the conviction trail.

### 3. The outside view is built but unreachable (high, cheap)

`POST/GET …/outside-view` (DC-29) compares the decision with comparable cases
the user recalls, which is Aristotle's check against over-confidence. No screen
collects the recollection, so it never runs, and the brief's "comparable cases"
section is always empty.

*Proposal*: one text box on the summary page ("What similar decisions do you
remember, and how did they go?") that calls the endpoint. Also compare the
base rate with the **decider's conviction**, not with the model's confidence
(see 7).

### 4. Statistical validation cannot happen (medium)

The validation stage accepts `metric_data`, but no route or screen passes it, so
every link stays "untested" by data. Links can only be tested by observation.

*Proposal*: let a link test accept a small table (CSV paste) and run the
existing statistical check on it; record the result as evidence on the link.

### 5. `recompute_beliefs` does nothing (medium)

`POST /recompute` (DC-23) propagates and discards the result. The frontend calls
it after every added claim or link (`hooks/useReasoning.ts`), then reloads the
graph, and that reload recomputes beliefs anyway. So each addition pays for a
full graph load and propagation that nothing uses. Remove the call and the
endpoint, or make it persist a snapshot the conviction trail can reference.

### 6. Noisy-OR assumes independent causes (medium)

Two causes that share an upstream driver are combined as if independent, which
inflates the belief in the common effect. It matters most on dense graphs.

*Proposal*: flag targets whose parents share an ancestor within two hops and show
the belief as a range (stability interval) rather than a point; longer term,
let the user mark a gate as AND or "same cause".

### 7. The model's own labels rank the theories (low-medium)

When no conviction is stated, theories are ordered by the model's
`business_impact` and confidence. That is self-assessment. The brief now ranks
by stated conviction first, then by the objection-discounted score, but the
theory list (`reasoning/theories.py`, the order the graph panel shows) still
puts model impact first.

*Proposal*: rank everywhere by (reaches an outcome, leverage × uncertainty of its
weakest link, conviction), which are all things the analysis measured.

### 8. Tripwire and link-test weights are fixed (low-medium)

Evidence the decider enters by hand uses a five-step verbal scale. Tripwires and
link tests do not: a fired falsifier is always x0.25, a refuted link x0.25, a
held link x2 (`theory_value.tripwire_likelihood`, `link_tests.py`). A tripwire
the decider wrote as "if this happens I drop the plan" moves conviction as much
as one they wrote as a weak signal.

*Proposal*: ask "how decisive would this be?" (three levels) when the tripwire
or link test is written and map it to the ratio.

### 9. Latency and cost (low)

* Saving a changed anchor re-scores all claims synchronously; on large projects
  the request is slow. Move it to a background task with a progress event.
* Incremental outcome pairing costs about three model calls per new claim.
  Batch new claims per save.

## Report for managers and executives

The brief (Markdown, HTML, PDF) was re-ordered to be read answer-first
(`reasoning/brief_view.py` derives it once for all formats):

1. **Executive summary**: the decision, the recommendation and how well it is
   supported, key numbers (options examined, theories, open tests, next check),
   and "before relying on this" warnings (unexamined options, stale theories,
   no theory reaching a success criterion).
2. **Options at a glance**: one row per option: strongest case for, strongest
   case against, and a status (Contested / Only a case for / Only a case against
   / Not examined).
3. **What would change the decision**: open link tests, dated tripwires and
   designed field tests, then how the decider's conviction has moved.
4. **The theories**, grouped by option, then conditions that bear on every
   option, debates, comparable cases.
5. **Appendix: quality of the analysis**: claims and links after review, share
   of claims with a path to a success criterion, isolated claims.

Every analysis is a project: from the project list each row offers Summary,
Causal graph and Download report; the summary page has Causal graph and Download
report at the top; the graph page has Download report in its toolbar.

## Verification

* Backend: `pytest` 98 passed (Postgres running; DB tests skip otherwise).
* Frontend: `vitest` 176 passed; the 10 failures are all tests of dead code
  (DC-35, DC-36, DC-41). `tsc` reports no new errors; eslint clean on touched
  files.
* End to end (Playwright against the running app): the three Download report
  entry points download the PDF; no console errors.
