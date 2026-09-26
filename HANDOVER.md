# Decision Studio — Technical Handover

**Last updated:** 11 August 2026
**Audience:** the engineer picking this up next
**At handover:** 364 backend tests (pytest) · 133 frontend (vitest) · 77 endpoints · 21 migrations

---

## 0. Read this first

This explains what was built, how it works, and — for the close calls — why it
was built this way rather than the obvious alternative. The *why* sections are
worth your time. The code tells you what it does; it does not tell you which
three simpler approaches were tried first and what broke.

Two things before anything else:

1. **Every numeric threshold here was chosen by hand.** None has been calibrated
   against real outcomes. §10 lists them with the reasoning. Starting points,
   not measurements.
2. **The system is built to refuse to fake confidence.** Several features exist
   specifically to *reduce* how certain the output sounds. If you find one and
   think "this would be more impressive without the hedging", read §9 first.

---

## 1. What it is

Documents about a decision go in. The claims in them are extracted, the causal
links between those claims inferred, and the resulting graph reasoned over to
produce explanations and a recommendation.

The target case is **n = 1**: a specific merger, a specific delivery commitment,
a specific hire. No base rate, no repeatable trial. The quality of the answer is
bounded by the quality of the reasoning rather than by data, and everything
follows from that.

### The shape of a run

```
documents + one sentence saying what is being decided
   ↓  intake questions           optional, before anything runs — §4.9
   ↓  claim extraction          LLM, one call per 8000-char chunk
   ↓  embedding + dedup         local, cosine ≥ 0.86
   ↓  causal inference          LLM, BFS over claim pairs
   ↓  blind re-scoring          LLM, edges re-scored without their own scores
   ↓  bias audit                LLM
   ↓  evidence grounding        web search + local NLI, 180s ceiling
   ↓  statistical validation    Granger / PC where time series exist
   ↓  discovery                 additional layers, optional
   ↓  DAG construction          cycle detection, weak-edge pruning
   ↓  belief propagation        Noisy-OR over topological order
   ↓
graph ──→ theories ──→ debates ──→ recommendation
                                        ↓
                              /summary/:projectId
```

The four stages after the graph run **automatically** at the end of a pipeline
run (§4.6). They can also be triggered individually.

### Where a user actually goes

| Route | What it is |
|---|---|
| `/` | Upload, title, **the decision in one sentence** |
| `/analysis/:id` | Live pipeline progress |
| `/summary/:id` | **Where an analysis lands.** Recommendation, then explanations |
| `/graph/:id` | The graph, for checking the reasoning |
| `/compare/:id` | Scenario comparison |

`/summary` is the destination, not the graph. A graph is the *material* a
conclusion is made from.

---

## 2. Layout

```
decision_studio/
  pipeline/
    orchestrator.py      stage sequencing, checkpoints, event emission
    claim_extractor.py   documents → claims
    claim_dedup.py       semantic dedup of restated facts
    causal_inferrer.py   claims → edges, BFS
    blind_rescorer.py    re-scores edges without showing their own scores
    evidence_grounder.py web search + NLI scoring
    discovery.py         additional inference layers
  graph/
    edge_weight.py       effect × link_confidence → operative strength
    belief_propagation.py  Noisy-OR, evidence floor
    stability.py         Monte Carlo: intervals, rank stability
  reasoning/
    theories.py          explanations, with provenance
    adversary.py         objections + tripwires
    debate.py            pure structural comparison — no I/O
    debate_service.py    debate orchestration, tripwire promotion
    recommendation.py    synthesis across all theories
    experiments.py       synthetic + field experiments
    outside_view.py      base rates from recalled cases
    authoring.py         manual claim/edge addition
    review.py            human review, single staleness entry point
    effective_graph.py   what counts as active
    source_interest.py   author-interest adjustment
    calibration.py       verbal bands
    brief.py             exportable document (markdown / html / pdf)
    brief_pdf.py         one-page executive summary, then detail
    decision_context.py  the stated objective
    intake.py            questions asked before the pipeline starts
  db/
    models.py            all ORM models
    schema_check.py      startup drift detection
  llm/
    client.py            OpenAI + Anthropic
    model_params.py      per-model parameter compatibility
    prompts/             one module per prompt
  api/routes/            77 endpoints
    intake.py              the four intake endpoints
  api/sources.py         input composition, shared by /intake and /analyze
```

---

## 3. Load-bearing design decisions

The ones where the obvious approach was tried and rejected. If you change one,
change it deliberately.

### 3.1 An edge carries two numbers, not one

`graph/edge_weight.py`

- **effect** — how much gets through *if the link is real*
- **link_confidence** — how sure we are the link exists at all

Operative weight is their product, floored at 0.10 and capped at 0.95.

**Why not one number.** A weak-but-certain link (0.20 × 0.95) and a
strong-but-speculative one (0.90 × 0.20) are opposite situations: the first is
something to build on, the second something to go and investigate. Asked for a
single blended "strength", a model averages them and both land near 0.5 — at
which point they are indistinguishable.

The 0.95 cap is a statement: nothing inferred by a language model earns
certainty. The 0.10 floor exists because an edge worth storing is worth
propagating a little, and a hard zero deletes it from every downstream belief
without a trace.

**Migration note.** The back-fill set `effect = strength, link_confidence = 1.0`,
so the product was identical and no existing output changed. Deliberate — a
schema change that also changes results makes it impossible to tell which caused
what.

### 3.2 `claim.confidence` and `claim.prior` are different

- **confidence** — how firmly the source asserts it (a property of the text)
- **prior** — probability it is true (what propagation uses)

They were one field. A document that states something emphatically is not
thereby more likely to be right, and conflating them let rhetorical force leak
into belief. `_root_prior()` reads `prior`, falling back to `confidence` for
rows predating the split.

### 3.3 The evidence floor

`EVIDENCE_FLOOR = 0.30` in `belief_propagation.py`

An ungrounded edge still propagates at no less than 0.30. Only
`has_contradiction=True` may go below.

**Why.** *"We could not look"* and *"we looked and found nothing"* are different
states; only the second is evidence of absence. Without the floor, an edge
nobody searched for was indistinguishable from one actively refuted — and since
search coverage is uneven, that quietly deleted whole regions of the graph based
on which queries happened to return results.

This floor is also what makes the grounding timeout (§5.8) survivable.

### 3.4 Blind re-scoring

`pipeline/blind_rescorer.py` — fixed seed 20260725, batches of 8, temp 0.1

Every edge is scored a second time by a model that cannot see the first score.
The run reports mean inflation; on a recent large run, **0.341**.

**Why.** A model shown its own earlier estimate anchors on it and reviews its own
reasoning rather than the claim. Hiding the first score is the only way to get an
independent second opinion from the same model.

Watch that inflation figure: consistently high means the first pass is
systematically overconfident, which is a fact about the prompt.

### 3.5 Human review is authoritative and reversible

`reasoning/review.py`, `reasoning/effective_graph.py`

Effective iff `is_active AND status NOT IN (rejected, not_relevant)`. Rejected
elements stay visible, dimmed, with an immutable audit log in `graph_operation`
and an undo.

**`mark_reasoning_stale()` is the single point invalidating downstream
reasoning** — theories *and* debates. Not stylistic: it already failed once with
two call sites, when manual authoring marked theories stale and left debates
holding overlap numbers computed against a graph that no longer existed.

### 3.6 Theories cite reference tokens, not UUIDs

Generation gives the model short tokens (`C1`, `E4`), resolved afterwards.

**Why.** A model asked to reproduce a UUID produces something UUID-shaped that
does not exist, and a fabricated citation that *parses* is worse than one that
fails — it gets persisted and looks authoritative. A hallucinated `C97` in a
60-claim graph fails to resolve and is dropped.

### 3.7 The adversary never sees the theory's prose

`reasoning/adversary.py`, temperature 0.7

It receives the causal chain, claims and evidence — not the title, summary or
recommendation. **Given the prose it critiques the writing; given the structure
it attacks the argument.**

Objections cost something: `objection_load = mean(severities)`,
`adjusted_score = confidence × (1 − 0.5 × load)`. Ordering uses the adjusted
score. **An objection that changes no ranking is decoration.** Above
`CONTESTED_THRESHOLD = 0.45` a theory is flagged contested; the user can dismiss
one they judge unfounded.

`mean`, not `sum`: with sum, a theory attacked five times weakly ranks below one
attacked once devastatingly, which is backwards.

### 3.8 Synthetic experiments cannot raise confidence

`reasoning/experiments.py`

`execute_synthetic()` **never** increases confidence. Objections are promoted
into the adversarial log at severity 0.35 — below contested, so one simulated
dissenter does not by itself flag a theory.

**Why.** Five simulated people agreeing measures the model's agreeableness, not
the world. The objections are still worth having: a budget problem raised by a
simulated CFO will be raised by the real one.

Only `design_field()` produces something that can move confidence, and only once
its result is entered.

### 3.9 Debates: structure first, model second

`reasoning/debate.py` is pure — no DB, no LLM. Jaccard overlap on **edges**:

| Overlap | Relation | Meaning |
|---|---|---|
| ≥ 0.70 | `same_story` | One theory in two wordings — **never sent to the model** |
| ≤ 0.20 | `orthogonal` | Different subjects; both may hold |
| between | `competing` | Genuinely at odds — worth a model call |

Edges, not claims: two theories about the same decision share claims by
construction; the *links* differ.

Competing pairs get a **crux** and a **discriminator**, promotable to a tripwire
on **both** theories — explicitly, with confirmation, never automatically.

When nothing separates two competing theories before the deadline, that is the
finding: prefer the option robust to both. Supported outcome, not failure.

### 3.10 Monte Carlo, not point estimates

`graph/stability.py` — 200 runs, per-edge σ = 0.12 scaled by `link_confidence`.

`rank_stability()` reports `p_first` per option and a `decisive` flag: *"A wins
in 52% of simulations"* rather than *"A wins"*. **The system contradicting its
own output is the point.**

Comparisons use **selective common random numbers**: shared noise where the
scenarios share edges, independent where they differ. Fully shared understates
the difference; fully independent swamps it.

This replaced `compute_belief_intervals`, which was wrong in a specific way:
intervals *narrowed* with depth, 2.6× too narrow at four hops. Plausible-looking
and backwards.

### 3.11 Verbal confidence bands

`reasoning/calibration.py` — the float is kept and orders correctly; the
*display* refuses percentages. Nothing has been calibrated, so "72%" asserts a
resolution that does not exist. A test pins the absence of `72%`.

### 3.12 Source interest

`reasoning/source_interest.py` — asymmetric, reason recorded per adjustment:

- `against_interest` → prior **+0.15**
- `interested` → prior **−0.10**

An admission against one's own interest is stronger evidence than a self-serving
assertion is weak.

### 3.13 Semantic dedup

`pipeline/claim_dedup.py` — cosine ≥ 0.86, strongest prior kept, corroboration
bonus +0.06 per source **capped at +0.15**.

The cap matters: without it a fact repeated across ten documents from one
original source acquires the weight of ten independent confirmations. The bonus
is for corroboration; the cap is because repetition is not corroboration.

---

## 4. Recent work

### 4.1 Per-model parameter compatibility

`llm/model_params.py` · 22 tests

Reasoning models (o1, o3, gpt-5 and successors) reject `max_tokens`,
`temperature` and `logprobs` with a hard 400. One wrong parameter takes the
application down for that model entirely.

**The name list is only an initial guess.** The important half is that the module
**learns from the rejection**: the error names the parameter, that fact is
recorded, and the call is retried without it. Every later call is already
correct.

**Why not just a list.** A list goes stale the day a new model ships, and its
failure mode is total — the application stops working for exactly the model the
user just chose.

`max_tokens` is **translated, not dropped**, and multiplied by
`REASONING_BUDGET_MULTIPLIER = 4`. `max_completion_tokens` covers reasoning
tokens *and* output where `max_tokens` covered output alone; translating
unchanged silently cuts the answer budget, and the model spends the whole
allowance thinking and returns an empty string — which surfaced as a JSON parse
error at character zero, naming nothing useful.

The client distinguishes empty content from `None` and reports `finish_reason`;
`length` and `content_filter` get specific messages.

### 4.2 Documents are kept, not consumed

`db/models.Document`, migration 014

Upload used to extract text straight into the prompt box: the text replaced what
the user had typed and the file was discarded.

Now **store first, read second**. A 400-character preview is returned; the full
text stays server-side. Several documents can be attached, each labelled in the
combined text so provenance survives.

A file whose text cannot be extracted is **kept with the error recorded** — it is
still the file the user meant to use, and a better parser may handle it later.
Original bytes kept below 5 MB.

### 4.3 The stated decision

`project.decision_objective` · `reasoning/decision_context.py`

One sentence, entered on the upload page below the title, editable afterwards
from `/summary` via the pencil icon.

**Why editable.** People frequently work out what they are actually deciding
*after* seeing what the documents contain. Settable only before the run would
mean starting over to correct it — which in practice means not correcting it.

Changing it **clears the displayed recommendation**: the advice was written
against the old question and now answers something nobody asked. An empty space
with a regenerate button beats stale advice that looks current.

Everything after the graph reads this. Without it, theories describe the
situation rather than bearing on a choice.

### 4.4 Manual authoring

`reasoning/authoring.py`

Adding a claim defaults to `ASSUMPTION` with prior 0.5 — what you assert from
your own knowledge is an assumption until evidence says otherwise, and starting
it as a fact lets an unevidenced belief carry the weight of a sourced one.

Drawing an edge **requires a mechanism**. That requirement is the feature: a link
without one is a correlation with an arrow drawn on it, and authors frequently
discover the link is not causal while trying to write the sentence.

`infer_links_for_new_claims()` infers **only pairs involving the new claim** —
re-inferring everything would resurrect links already rejected.

`undo_addition()` deactivates, never deletes; incident edges go with the
withdrawn claim.

### 4.5 The recommendation

`reasoning/recommendation.py`, migration 017

A synthesis across **all** theories, distinct from `Theory.recommendation`.

**Why a separate call.** `Theory.recommendation` speaks for one explanation.
Stacking those produces contradictory advice with nothing to resolve it. Two
theories can point the same way, opposite ways, or at different things, and
weighing them is the hardest part of reading an analysis — the part the reader
came for.

The prompt sees each theory **with its objections and tripwires**: a
recommendation resting on a contested explanation is weaker than one resting on
an unattacked one, and the model cannot account for that if it never sees the
attacks.

Asked for four things: answer the decision (not describe it), say what would have
to be true, give the strongest case for doing otherwise, name one thing to do
this week. `low` confidence is explicitly legitimate — a hedge stated clearly
beats confidence that is not warranted.

One row per project, replaced on regeneration. `is_stale` compares **theory
ids**, not revision numbers: theories can be regenerated without the graph
changing, and advice derived from a superseded set describes explanations the
reader can no longer find.

### 4.6 Automatic downstream generation

`api/routes/analysis._generate_downstream()`

After belief propagation: theories → debates → recommendation, each in **its own
session**.

**Why separate sessions.** The pipeline's session has just been committed.
Reusing it ties the graph's fate to these calls, and a committed twenty-minute
run must not be lost because a later LLM call timed out.

Failures are reported through the event stream and swallowed. A debate failing
with fewer than two theories is logged as `skipped`, not an error.

### 4.7 The summary page

`components/summary/DecisionSummary.tsx`

Order: stated decision → **recommendation** → each theory in full → how to read
this → links to graph and export.

Each theory shows the causal chain step by step (the argument itself, not a claim
about it), what argues against it, weak assumptions, outside-view comparison, and
tripwires with dates.

**Objections sit beside the conclusion, not in an appendix.** Burying them is how
a qualification gets lost between the analysis and the meeting.

### 4.8 The PDF brief

`reasoning/brief_pdf.py` · `GET /graph/{id}/brief?format=pdf`

**Page one stands alone**: the decision, the recommendation with its conditions,
the case against, the next step, and a one-row-per-theory table. Plus the "how to
read this" caveats.

**Why one page.** A brief that requires four pages before the conclusion gets
skimmed to the conclusion anyway, losing the qualifications on the way. Putting
conclusion *and* caveats on the same page means the reader who reads only one
page gets both.

Pages after: explanations in full, with `KeepTogether` so a page break cannot
separate a conclusion from what undermines it.

Rendered from the gathered data, **not** from the Markdown export — parsing our
own output back in would make a formatting change silently become a content
change.

Reachable from both `/summary` and the graph toolbar.

### 4.9 Three removals, and what came back

Three question systems were built and all three removed. Recorded because the
reasoning applies to anything similar you may be tempted to add.

| System | Asked | Why it went |
|---|---|---|
| **framing** | 15 questions, 5 reusable as a profile | Stood between someone who had uploaded documents and the analysis they wanted |
| **intake** | Ambiguity in extracted claims | Paused the pipeline mid-run; held an expensive run open on someone who had stepped away |
| **clarification** | What would change a conclusion | Went with the others |

The argument for intake questions was real: an answer arriving *before* causal
inference shapes the graph, one arriving *after* means re-inferring. The cost
asymmetry was correct. **The trade was not** — a stalled twenty-minute run costs
more than a correction, and the correction path already existed.

Replaced by `project.decision_objective` (§4.3). Migration 016 drops six tables;
004 and 013 had downgrades made conditional so the chain still walks backwards.

**A fourth was then built, and it is different in one respect only: it runs
before the orchestrator is called.** There is no run to pause, so the cost that
killed the first intake does not exist, while the benefit of arriving before
causal inference is kept intact.

`reasoning/intake.py` reads the material once, asks at most four questions, and
renders the answers into a block prepended to the extraction *and* inference
prompts via `extra_context` — which was already declared on
`causal_inferrer.infer()`, documented, and had zero callers. It was the plumbing
the removed intake left behind; this is its first consumer.

Reaching extraction as well as inference matters: an answer arriving after
extraction can only correct claims already split the wrong way, whereas one
arriving before stops them being split that way at all. *"The team lost three
people"* is an event out of eight and noise out of thirty, and the difference
propagates through the whole graph.

Load-bearing properties, each with a test:

- **Zero questions is a correct outcome.** Stated twice in the prompt. A model
  that believes it owes four questions produces four, and that is how an intake
  becomes a framing form.
- **Every failure starts the analysis.** Timeout, malformed payload, non-list —
  all return no questions and proceed. This step improves a run perfectly able
  to proceed without it.
- **An empty context is indistinguishable from no context.** Which is what makes
  the skip path the same run it claims to be.
- **Answers are interpretive, never factual.** They change how the material is
  read; they never become nodes. A claim carries provenance, evidence grounding,
  a bias audit and a prior separate from its confidence — a sentence typed into a
  box passed through none of those gates. Asserting a fact goes through
  authoring, where it is recorded as a human intervention.
- **Unanswered questions render nothing** — no "unknown", no placeholder. The
  block is prepended to every inference call, so an invented premise is repeated
  hundreds of times.
- **Quotations are verified** against the material, normalising whitespace only.
  A citation the user cannot find makes them doubt the document rather than
  answer the question.
- **`authority` sorts first, before truncation to the cap.** Who decides is
  almost never in the material — absent by nature — and a recommendation aimed
  at a lever the reader cannot pull is wasted.

Creating the project and generating the questions are **two calls**, which looks
like ceremony until you see why: fused, the client has no `project_id` during
the five to ten seconds of reading — exactly when the user may press "start
anyway". Without an id that button either waits for the reading to finish,
cancelling itself, or opens a second project and abandons the first.

Three switches: a per-browser preference (default on, including when
localStorage is unreadable), a switch on the questions screen for the moment
someone has had enough, and `INTAKE_ENABLED=false` for the operator.

### 4.10 The decision anchor

`project.decision_anchor` · `reasoning/decision_anchor.py` ·
`reasoning/anchor_service.py` · `graph/anchoring.py` · migration 022

**The problem.** The graph was built without the decision. Extraction was told
to extract every claim, inference started from root causes and asked what each
one caused, and `decision_objective` was first read by theory generation — after
the graph existed. Claims described the documents; theories had to bridge from
them to a choice nobody had shown the graph.

**The shape of the fix** comes from Aristotle (Bocconi's theory-based decision
tool): fix *what success looks like, by when, under which constraints* first,
and treat a theory as a causal map from attributes to that success. The anchor
is that problem statement in the smallest form that changes the graph:

| Part | What it does |
|---|---|
| `decision` | One sentence, kept in step with `decision_objective` |
| `options` O1..O4 | Claims name the options they bear on (`bears_on`). **Not graph nodes**: a choice has no probability, and mutually exclusive options in noisy-OR would assert a belief about which one the user picks |
| `outcomes` Y1..Y3 | **Become graph nodes** (`origin='frame'`, `decision_role='outcome'`), so inference has a destination |
| `deadline`, `constraints` | Rendered into prompts; nothing enforced yet |

Drafted by the model from the objective and the material; never invented
without an objective (no objective, no anchor, and the run is the one it always
was). On the intake screen it is a pre-filled card that is drafted only when
there are questions to show, and sent only if edited — it never stands between
the user and the analysis.

**What the pipeline does with it:**

- **Extraction** sees the anchor and scores each claim: `decision_role` (lever,
  contingency, mechanism, outcome, background — the theory-based view's
  attributes), `relevance` 0-1 with a reason, and `bears_on`. **Scored, never
  filtered** (§6 explains why). It may also extract an implication the text
  clearly supports as an ASSUMPTION — the bridge claims that were missing.
- **Outcome nodes** join after dedup, so an extracted claim restating a success
  criterion is never merged into one.
- **Inference** offers every outcome to every source, bypassing the similarity
  filter: an outcome is phrased as a criterion and rarely shares vocabulary with
  what drives it. Outcomes are never roots and never sources.
- **The edge budget** sorts by strength × (0.5 + 0.5 × relevance) instead of
  strength. Unscored claims weigh 1.0, which is the old ordering.
- **Discovery** expands only edges on a path to an outcome, or between relevant
  claims — all edges when nothing is anchored yet. New claims are scored.
- **Theory context** ranks claims by relevance instead of word overlap with the
  objective, always includes the outcomes, and asks each theory to end its chain
  at one and name the option it favours.

**Relevance has two sources, and the larger wins.** The model's per-claim score,
and *structural* relevance from causal hops to the nearest outcome
(`graph/anchoring.py`: 0 → 1.0, 1 → 0.85, 2 → 0.65, 3 → 0.45, further → 0.3,
hand-chosen like everything in §10). Structure can only promote. A claim the
model read as background (< 0.4) that sits on a path to an outcome is
**peripheral** — the surprising factor the tool exists to surface — and the UI
lists these separately. The **decision lens** (default view on anchored graphs)
shows claims within three hops of an outcome, claims with relevance ≥ 0.5, and
every peripheral claim. It is a view: the claims browser lists everything.

**Editing afterwards costs a re-score, not a re-run.** `PUT
/graph/{id}/decision-anchor` renames outcome nodes in place (links kept), adds
new ones with incremental inference, deactivates removed ones (reversible), and
re-scores every claim at one call per forty. Keys are never reissued — a deleted
Y2's key would hand its node and links to a different outcome — so the service
reserves every key the project has used. The same call anchors a project built
before anchors existed.

**Measuring it.** `python -m decision_studio.tools.anchor_report <project-id>`
reports claims, components, the share that reaches an outcome, relevance
distribution, peripheral count and how many theories reach an outcome. Run it on
an old project, anchor that project from the summary page, run it again; then
compare with a fresh anchored run.

### 4.11 Theories of value

`reasoning/theory_value.py` · `reasoning/link_tests.py` ·
`graph/value_of_information.py` · `api/routes/theory_value.py` · migration 023

The theory-based view (and Aristotle) treats a theory as a causal map from the
attributes of a choice to success, held with a stated *conviction* that tests
move. Three pieces make theories here work that way.

**Option-bound theories.** Generation now asks for rival theories per option —
the strongest case for and against each, never padding an option the graph is
silent about. Each theory carries `option_key`, `predicted_effect` (achieves /
threatens / unclear) and `outcome_keys`. Validation drops option keys the anchor
does not have, and computes **`reaches_outcome` from the validated chain** — the
model saying its theory reaches the decision is not evidence that it does.
**Option coverage** (theory list, summary, recommendation prompt) shows an
option no theory examines; the recommendation is told not to argue against an
option the graph never looked at.

**Conviction, apart from confidence.** `theory_belief` rows, keyed by
`theory_key` so they survive regeneration: a *prior* the decider states, then
*evidence* as likelihood ratios. Current conviction is replayed in odds form
(`prior odds × Π LR`). Evidence counts only when recorded after the latest
prior — restating after seeing a test already includes it. The prior is
elicited by four lottery comparisons ("bet on the theory, or on a draw with a p
chance?"), never a slider. Evidence comes from exactly three places:

| Source | Default LR |
|---|---|
| Tripwire fired / not (`adversary.record_observation`) | falsifier: 0.25 / 1.5; confirmer: 4 / 0.67 |
| Field experiment result (`experiments.record_field_result`, new) | supports 2, refutes 0.25, inconclusive 1 |
| Tested link (`link_tests.record_result`) | held 2, refuted 0.25, inconclusive 1 |

A synthetic experiment has no path to conviction, and nothing touches the
model's `confidence`. Field results were previously designable but not
recordable, so the README's "only a field experiment moves confidence" had no
code behind it; it now moves conviction. A refuted link, like a fired
falsifier, marks the theory stale.

**Links worth testing.** Each chain link is scored by *leverage* (perturb its
strength ±0.20, re-propagate, measure the chain destination's belief — the
outcome node when reached) times *uncertainty* (`1 − link_confidence × (0.5 +
0.5 × evidence)`). The top three become falsifiable hypotheses with a "wrong if"
observation and the cheapest test. Leverage is typically small in absolute terms
(propagation is damped), so the UI shows rank, not the product. Re-proposing
replaces only open hypotheses; results are kept.

Tripwire and field-test prompts now receive the anchor's outcomes, deadline and
constraints — the `None` placeholders left by the removed questionnaire.

Every default LR and weight above is hand-chosen and uncalibrated, like §10.

---

## 5. Bugs found and fixed

Every one was found by **running the thing**. That is the recommendation: when
something misbehaves, reproduce it with a fake LLM and watch the stages.

### 5.1 Schema drift (migration 011)

`project.last_completed_stage` and both advisor tables were in the models and in
**no migration**. A database built purely from `alembic upgrade head` was missing
them, and `GET /api/v1/projects` failed outright — SQLAlchemy selects every
mapped column.

Invisible for a long time because a development database accumulates columns
through `create_all`. It only appears when deploying from scratch.

`tests/test_schema_drift.py` builds a database from migrations alone and diffs it
against `Base.metadata`, then walks the chain down and back up.

### 5.2 Strict-mode schema violation — the costliest

When `strength` was split into `effect` and `confidence`, `strength` was left in
`properties` but taken out of `required`. **OpenAI strict mode rejects the entire
schema** with a 400 unless `required` lists every key.

Every expansion call failed. The graph came back with claims and **zero causal
edges** — and from there no evidence (grounding skips without edges), no
discovery, no statistical validation. One line of schema.

`tests/test_schema_strictness.py` walks every `*_SCHEMA` including nested
objects. 107 checks.

### 5.3 Vector width mismatch

Model declared `Vector(1024)`; database and config said 1536. The database was
right. Anything built from `Base.metadata` got a column too narrow, failing at
insert time with *"expected 1536 dimensions, not 1024"* — naming neither the
table nor the declaration that disagreed.

### 5.4 varchar columns declared as Text — killed a 20-minute run

**Five columns** disagreed: `causal_edge.time_delay`, `temporal_window`,
`evidence.source_title`, `source_url`.

`time_delay` was declared `Text` and created `varchar(100)`. The model is asked
for "estimated time between cause and effect" and answers in prose. On a graph
with 535 edges one answer ran long — INSERT failed, transaction poisoned, twenty
minutes gone.

**A bomb with a timer set by input size.** Survives every small run, fails on the
first large one.

Migration 018 widens all four. `role` stays `varchar(20)` — fixed set of labels,
so the constraint does real work.

`db/schema_check.py` now compares **widths** as well as existence:

```
too narrow: causal_edge.time_delay is varchar(100) in the database
            but unbounded text in the model
```

### 5.5 Poisoned session on failure

Compounding 5.4: the failed INSERT poisoned the session, so
`_update_project_status` also failed and the project stayed in `processing` —
unrecoverable.

It now rolls back and retries the status write. The project is marked `failed`,
committed checkpoints survive, and `/resume` picks up from the last stage.

### 5.6 Force layout showed one node out of thirty

`hooks/useForceLayout.ts` — the one users noticed most.

Two separate faults, fixed in turn:

**First:** the effect creating the simulation had a correct guard on
`width === 0` but depended only on `[topology]`. A topology arriving before the
container was measured — the normal first render — was dropped and never
retried.

**Second, and the real one:** visible nodes were found by walking out from a
single root, `roots[0]` — the first node in *extraction order*, which has nothing
to do with connectivity. On a typical graph most claims have no incoming edge, so
there are dozens of roots and most are isolated. Reproduced: **30 nodes, 17
edges, 1 visible.**

The invariant now is that **every node is drawn** unless a depth limit or a
collapsed ancestor explicitly hides it. Traversal starts from every root;
anything unreached afterwards is added directly.

Depths still showed in the sidebar throughout, because those are computed before
this filter — which made the canvas look broken rather than empty and sent the
search in the wrong direction for a while.

`hooks/__tests__/useForceLayout.test.ts` pins it: 30/17, no edges at all, an
all-cycle graph with no root, disconnected components, and that an explicit depth
limit still works. That last test caught a bug in my own first fix, which
silently undid the depth limit.

### 5.7 Graph appeared to load several times

`hooks/useResizeObserver.ts`

`setSize` wrote state on **every** observer callback, without comparing. Several
fire in the first moments of a mount — initial measurement, scrollbar appearing,
web fonts landing, a panel settling. Each restarted the simulation from
alpha = 1, so the graph re-animated three or four times.

Identical sizes now produce no update, and sub-pixel differences are treated as
identical. On the typical sequence: **5 updates → 1**.

### 5.8 Evidence grounding hang

Two web searches per edge — 34 for a 17-edge graph — against a free backend that
rate-limits without warning. With a 30s HTTP timeout per request and **no ceiling
on the stage**, a run sat for tens of minutes looking exactly like a hang.

`EVIDENCE_GROUNDING_TIMEOUT = 180.0` with clean abandonment. Grounding is the
right stage to give up on: the evidence floor (§3.3) keeps every edge propagating
without it, so a partial result is a weaker graph rather than a broken one.

### 5.9 Toolbar overflow

Nine buttons plus search and filters, `md:flex-nowrap`, no overflow handling.
*Add claim*, *Draw links* and *Comparisons* rendered past the right edge —
present and unreachable. Wraps at all widths now.

### 5.10 Theory causal chains were disconnected

The most serious of these, and the one that undermined the product's central
claim rather than merely breaking something.

Reference validation confirmed that every token in a theory's causal chain
*resolved* to a live graph element. It never confirmed that an edge *joined* the
claim before it to the claim after it. On a fragmented graph the model picked
plausible tokens and produced chains like:

```
The contract does not specify the equalisation window.
  ↓ Poor internet disrupted data exchange onboard vessel C1.
Repeated price-reduction requests consumed time.
```

Every token real. Nothing missing. Rendered with the authority of a verified
chain — in the brief, in the API, and to the adversary, **which was therefore
generating objections against a text that did not describe the theory**.

The system noticed and continued: the theories declared it under
`weak_assumptions` — *"E78 represents the intended timing relationship even
though its description concerns internet connectivity"*. That is not a weak
assumption. It is an edge attached in the wrong place, and treating it as
uncertainty to flag meant presenting untraceable reasoning as traceable.

`_build_chain` now checks connectivity, with three outcomes rather than two:
`connected`, `reversed` and `disconnected`. A reversed citation is **not
silently corrected** — in a causal graph the direction is the assertion, so a
model that reversed it got the theory wrong rather than the transcription.

**A theory keeping no connected link is dropped**, with `reason` recorded. The
threshold is one link, not a fraction: a chain keeping even one verified
junction has real reasoning worth showing, broken where it is broken, while one
keeping none is a list of claims with prose between them. Lowering its
confidence would leave it in the ranking beside real theories. A fraction would
not discriminate anyway — on a two-edge chain "over half" and "all" coincide —
so it would add a hand-picked constant without adding a distinction.

Two consequences worth knowing:

* **The fallback had to be taught to exclude rejected edges.** It rebuilds a
  minimal chain from `edge_ids`, which contains exactly the edges whose
  connectivity just failed. Without the exclusion it re-admitted them through
  the back door, and the failure is invisible: the chain exists, has the right
  shape, and is false again.
* **Existing objections are marked `pre_connectivity_check`.** They fed
  `objection_load`, which feeds `adjusted_score`, so every already-analysed
  project has a ranking computed partly from criticism of fiction. Marked rather
  than deleted or regenerated: they may still be sound, deleting destroys work,
  and regeneration costs a model call per theory across every project.

`connected_links` / `cited_links` reach the ranking, the API and page one of the
PDF as *"1 of 3 links verified"*. Deliberately **not** folded into
`adjusted_score`: weighting integrity there would be another uncalibrated
constant, and this system exposes what it cannot calibrate.

### 5.11 Missing attribute and API shape mismatches

- `CausalPipeline` passed `llm_client` to sub-stages without keeping it on
  `self`; a new stage calling the model directly found nothing.
- The summary page typed the graph response as `CausalGraph`, but the API returns
  `claims`, not `nodes` — `graph.nodes` was `undefined` and every read crashed.

### 5.12 Near-duplicate removal pointed claims at the wrong rows

`ClaimExtractor.embed_claims` drops claims above 0.95 similarity and then
renumbered `order_index`. The orchestrator uses `order_index` to find each
claim's already-saved row, so every claim after the first dropped duplicate
received its neighbour's embedding, and the rows deleted as "duplicates" were
the wrong ones. Chunks overlap by 1000 characters by design, so on long material
a dropped duplicate is the normal case. `claim_dedup` documents the same trap and
avoids it; `embed_claims` now leaves `order_index` alone too. Regression test in
`tests/test_extraction_and_inference_anchor.py`.

### 5.13 Intake context dropped for part of the graph

Causal inference expands claims unreachable from the roots in a second pass,
which omitted `extra_context`: those links were judged without the intake
answers. Manual authoring's incremental inference passed no context at all. Both
now receive the same context as the rest of the graph (anchor, then intake).

---

## 6. Known open issues

Things I would look at, in order.

**Claim volume.** Twelve documents produced 476 claims after dedup removed 710,
many of them true but useless.

Half of this is now handled: a `DOCUMENT_METADATA` claim type covers statements
about the paperwork rather than the subject matter — who signed what and when,
revision numbers, attachment lists — and `_drop_document_metadata` removes them
in the extractor, before anything downstream pays to process them. Every dropped
claim is logged individually, and the count reaches the UI: a filter that
discards a fifth of the input silently is one nobody can check, and this one is
a model's judgement about what counts as paperwork.

The other half is now addressed by the decision anchor (§4.10): extraction sees
the decision and scores each claim for relevance — a score rather than a
filter, so nothing is lost and the threshold stays adjustable. The risk that
shaped it: in a strategic decision the deciding factor is often the one nobody
connected to the problem, so a hard relevance filter would discard exactly the
thing the tool exists to surface. Hence structural relevance and the
"peripheral" list. Whether it reduces claim *volume* is not yet measured — the
extraction prompt still extracts everything; what changes is what is shown,
expanded and budgeted. Use `tools/anchor_report.py` on real material.

**Claim dedup on contract material.** On one set of contract documents, dedup
merged 710 of 1186 claims — a very high proportion, and the threshold (0.86) has
never been checked against real material. Two clauses can be worded almost
identically and mean opposite things: a carve-out reading "except where the delay
is attributable to the Company" sits at very high cosine similarity to the same
clause without it.

`python -m decision_studio.tools.inspect_dedup <project-id> --band 0.86 0.92`
re-runs dedup over the stored claims and reports every merge with its similarity,
flagging pairs where a negation, an exception or a figure is present in only one
member. It writes nothing. If flagged merges cluster near the threshold, raise
it. Note the tool cannot see subject reversal — "A shall notify B" versus "B
shall notify A" — so the unflagged merges are still worth scanning on a contract
set.

**Graph fragmentation — now measured, not estimated.** `dag_builder` reports
connected components, the largest, and isolated nodes on every run:

```
Built DAG with 476 nodes and 535 edges — 58 connected component(s),
largest holds 398 node(s), 46 isolated
```

This was the upstream cause of §5.10: theories were stitching together
components that do not communicate. Note the density — 535 edges over 476 claims
is barely one per node, so the graph is sparse in absolute terms and not only
divided by topic.

If more connections are needed, **the lever is the candidate filter, not the
strength floor.** `_SIMILARITY_THRESHOLD = 0.30` in `causal_inferrer` decides
which pairs are judged at all; a cross-topic link cannot be pruned for weakness
if it was never a candidate. The two parameters also have very different effects
on run cost: loosening the candidate filter multiplies model calls, while
lowering the strength floor is free.

**Old note on fragmentation.** With 476 claims and 535 edges, the graph is almost
certainly in dozens of disconnected components. Now that all nodes render (§5.6),
that is visible — and probably illegible. Grouping components visually and
stating how many there are would help, and is itself information: a fragmented
graph says the documents discuss unconnected things.

**Deprecated code, marked rather than deleted.** Four things have no callers and
carry a `deprecated_` prefix instead of being removed:

| What | Why it is still here |
|---|---|
| `pipeline/deprecated_stage_context.py` | Written to instrument stages, never wired up. Wiring it into `orchestrator.run()` would remove the duplication that makes that function 660 lines *and* give progress inside long stages, which the pipeline still does not report. Either wire it up and drop the prefix, or delete it — leaving it renamed is the temporary state |
| `llm/prompts/deprecated_evidence_search.py` | Prompt-driven search from an earlier grounder. Kept so anyone reinstating it finds the previous attempt |
| `api/routes/causal_analysis.py` handlers | The screen was removed; the **URL paths are deliberately unchanged**, because a URL is a public contract and something outside this repository may call them |
| `deprecatedAnalyze*` in the frontend client | Wrappers for the same endpoints, no callers since the screen went |

**`npm run build` fails.** It runs `tsc -b` and the repository carries 28
pre-existing type errors in files unrelated to this work. `npm run dev` and
`npx vite build` both work; the Docker image uses the latter. Worth clearing so
the build is a usable signal again.

---

## 7. Deployment

Single Azure Web App serving both halves. The frontend is a static bundle served
by FastAPI from the same origin: no CORS, one deployment target, no way for API
and UI to run different versions of a feature.

`README.md` has seven Portal steps. Three settings fail confusingly if missed:

| Setting | Why |
|---|---|
| `?ssl=require` | asyncpg spells it `ssl`, not libpq's `sslmode` |
| `WEBSITES_PORT=8000` | App Service ignores `EXPOSE` and probes port 80 |
| `WEBSITES_CONTAINER_START_TIME_LIMIT=600` | First boot runs 18 migrations; default is 230s |

Enable pgvector **before** first deploy, or migration 001 fails with
`type "vector" does not exist`.

`deploy-azure.sh` does the same from the CLI and is idempotent — names derive
from a subscription hash rather than `$RANDOM`, so a re-run after a failure
continues instead of orphaning resources.

**On Cosmos DB:** not viable. 29 relational models, 47 cascading foreign keys,
review operations writing four tables in one transaction. The integrity is doing
real work. Note pgvector is *not* the obstacle — embeddings are stored in a
`Vector` column but cosine is computed in Python. And Cosmos DB for PostgreSQL is
on Microsoft's retirement path.

---

## 8. Tests

```bash
# Backend — needs its own database; it drops and recreates the schema
createdb decision_studio_test
psql decision_studio_test -c 'CREATE EXTENSION IF NOT EXISTS vector;'
TEST_DATABASE_URL=postgresql+asyncpg://decision_studio:decision_studio@localhost:5432/decision_studio_test pytest

# Frontend
cd frontend && npm test
```

`tests/` is listed in `.gitignore`, so most of the suite described here is not
in the repository. The decision-anchor tests were added with `git add -f`; the
entry is worth removing so tests are versioned by default.

No test contacts an LLM or a search provider. `FakeLLMClient` replays canned
structured output, so the suite runs without credentials and spends nothing.
Without a reachable database, DB-backed tests skip and the rest still run.

**Four are structural guards** rather than behaviour tests, and are the ones most
worth keeping:

- `test_schema_drift.py` — migrations must produce what the models declare
- `test_schema_strictness.py` — every JSON schema must satisfy strict mode
- `test_model_params.py` — parameter compatibility, including the learning path
- `useForceLayout.test.ts` — every node reaches the canvas

---

## 9. What the system deliberately will not do

If you are asked to make the output more confident, these will be in your way.
They are load-bearing.

1. **Synthetic experiments never raise confidence.** Pinned by a test.
2. **Debates can conclude "not decidable in time."** Two agents arguing would
   always produce a winner, because two agents always find something to say.
3. **Confidence is displayed as a band.** The float exists and orders correctly.
4. **Monte Carlo contradicts the point estimate.**
5. **The outside view refuses to invent a denominator.** *"Integrations usually
   slip"* yields no base rate — a fabricated one would be shown back to the user
   as their own recollection.

The cost is real: the system is **less satisfying**. It says "moderate" instead
of 72%, "coin flip" instead of "A wins". An executive used to hard numbers will
find it evasive.

The bet is that a tool which can say "I don't know" is believed when it says
something else.

---

## 10. Every hand-chosen threshold

None is calibrated. Each is a starting point.

| Constant | Value | Where | Reasoning |
|---|---|---|---|
| `DEDUP_THRESHOLD` | 0.86 | claim_dedup | Above: distinct facts merge. Below: restatements survive as independent support |
| `_DEDUP_SIMILARITY_THRESHOLD` | 0.95 | claim_extractor | Stricter, pre-embedding pass |
| `EVIDENCE_FLOOR` | 0.30 | belief_propagation | Absence of search ≠ evidence of absence |
| `MIN_STRENGTH` / `MAX_STRENGTH` | 0.10 / 0.95 | edge_weight | Floor: keep it propagating. Cap: nothing inferred earns certainty |
| `_SIMILARITY_THRESHOLD` | 0.30 | causal_inferrer | Pairs below are never sent to the model |
| `CONTESTED_THRESHOLD` | 0.45 | adversary | Mean severity above which a theory is flagged |
| `OBJECTION_WEIGHT` | 0.5 | adversary | `adjusted = confidence × (1 − 0.5 × load)` |
| `SIMULATED_OBJECTION_SEVERITY` | 0.35 | experiments | Below contested, so one simulated dissenter does not flag |
| `SAME_STORY_THRESHOLD` | 0.70 | debate | Above: one theory in two wordings |
| `ORTHOGONAL_THRESHOLD` | 0.20 | debate | Below: different subjects |
| `DEFAULT_SIGMA` | 0.12 | stability | Per-edge noise, scaled by link_confidence |
| `DEFAULT_RUNS` | 200 | stability | Enough for stable deciles |
| `MATERIAL_DIVERGENCE` | 0.20 | outside_view | Gap from base rate worth flagging |
| against_interest / interested | +0.15 / −0.10 | source_interest | Asymmetric on purpose |
| `CORROBORATION_BONUS` / cap | 0.06 / 0.15 | claim_dedup | Cap because repetition is not corroboration |
| `EVIDENCE_GROUNDING_TIMEOUT` | 180.0 | orchestrator | The one stage whose absence is survivable |
| `REASONING_BUDGET_MULTIPLIER` | 4 | model_params | Generous, not precise — a cap is a limit, not a target |
| `MAX_FREE_TEXT_CHARS` | 2000 | orchestrator | Not for the INSERT — a 2000-char "time delay" crowds out prompts |
| `MEANINGFUL_CHANGE_PX` | 1 | useResizeObserver | Below this, a resize is layout noise |
| minimum connected links | 1 | validation | A categorical boundary, not a tuned fraction. A fraction does not discriminate on short chains and would add a constant without adding a distinction — see §5.10 |

---

## 11. The three deepest assumptions

The ones that would invalidate results rather than degrade them.

**1. Belief is treated as probability for a one-off event.** The propagated
number is manipulated as though it were a frequency. For a decision that happens
once it is a degree of belief, and the arithmetic is a convention rather than a
derivation.

**2. Noisy-OR assumes independent causal mechanisms.** In strategy this is
routinely false — two paths to the same outcome usually share a hidden common
cause. Propagated belief is therefore biased **upward** wherever paths converge,
which is exactly where the graph is most interesting.

**3. Confidence and base rate are compared as if they measure the same thing.**
The outside view flags divergence between a theory's confidence and a recalled
frequency. One is a model's degree of belief; the other is a count. Useful, and
not strictly valid.

---

## 12. Further reading

`EXAMPLE_RUN.md` follows one analysis from upload to recommendation, with the
real output of every stage and **every alternative outcome each one can
produce** — including the ones that look like failures and are not. Written for
someone reading a log or a report rather than the code; also the fastest way to
see what the pipeline actually emits without running it.

## 13. If you are picking this up

1. **Run the pipeline with a fake LLM and watch the stage events.** A fake
   returning minimal valid structured output per schema takes seconds to write
   and shows exactly where anything stalls. Every bug in §5 was found this way.
2. **Read `graph/edge_weight.py` and `graph/stability.py`.** Short, and they
   contain the ideas the rest depends on.
3. **Read §9 before "improving" anything that looks like unnecessary hedging.**

Where I would look first:

- **Claim volume and graph fragmentation** (§6) — the two things most affecting
  whether the output is usable on real material.
- **Noisy-OR independence** (§11.2) — the assumption most likely to be materially
  wrong on a real graph.
- **The thresholds in §10** have never been checked against outcomes. The first
  real calibration data would be worth more than any new feature.
- **Objection severities** come from the same model family that wrote the
  theories. Whether an adversary can genuinely attack its own output is an open
  question worth testing.
