# The decision view: priorities, robustness, sensitivity, what would change my mind

Decision Studio is not a forecasting system. These four features help a decider
see what each option implies, which outcomes matter, how robust the comparison
is, which assumptions drive it, what would change their mind, and what is worth
finding out first. None of them recommends an option.

All four read the same computation: the option comparison
(`reasoning/option_comparison.py`), which applies each option to the reviewed
causal map as an intervention and runs the existing Monte Carlo
(`graph/stability.compare_options`). No second graph, no second probability
system, no model call.

## Six quantities that are never merged

| Quantity | What it is | Where it comes from | Where it shows |
|---|---|---|---|
| **Current belief** | Probability of a claim given the graph as it stands | `belief_propagation.propagate_beliefs` | Graph screen, claim panel |
| **Theory conviction** | How strongly the decider believes a theory | `theory_value` (stated prior, updated only by observations) | Theory panel; "what would change my mind" |
| **Option-implied outcome** | Probability of a success criterion if the option is chosen | Intervention + propagation (`option_comparison`) | "What each option implies"; report "Model-implied outcomes" |
| **Robustness** | How often the *relative* comparison survives varied link strengths | Pairwise shares in `compare_options` + `decision_robustness` | "Robustness & sensitivity" |
| **Decision weight** | How much a success criterion matters to the decider | `project.outcome_priorities` (`decision_priorities`) | "Decision priorities" |
| **Weighted view** | Option-implied outcomes averaged with the decision weights | `decision_priorities.weighted_view` | Weighted-view column; report "Weighted view based on decision-maker priorities" |
| **Information priority** | Heuristic rank of which open uncertainty to investigate | `information_priority` | "Information that could reduce decision uncertainty" |

Conviction is never used as an outcome probability, and no utility is written
back into conviction. There is no hidden overall score: the weighted view is
shown with its inputs (weights and per-criterion contributions), and when every
criterion is set to "not a factor" there is no weighted view and no leader.

## 1. Decision priorities and the weighted view

**Mapping** (`decision_priorities.IMPORTANCE_WEIGHTS`, deterministic):

| Importance | Weight |
|---|---|
| Critical | 8 |
| High | 4 |
| Medium (default when unset) | 2 |
| Low | 1 |
| Not a factor | 0 |

Each step doubles. Weights are normalised to sum to 1 over the criteria.

**Weighted view** of option *o*: `Σ_i w_i · P(Y_i | do(o))`. Each term is shown
as that criterion's contribution. Displayed as points out of 100 — not a
probability. The Monte Carlo's overall score and the robustness of the weighted
view use the same weights. When every criterion is "not a factor" there is no
weighted view: no leader is named, and drivers, information priority and
automatic scenarios are left empty rather than computed on a hidden equal
weighting. (`compare_options` still falls back to equal weights internally for
its per-option `p_best` field, which no screen or report shows.)

**Storage.** `project.outcome_priorities` (migration 025), apart from
`decision_anchor`: changing a priority never touches the graph and never
re-scores a claim. `PUT /graph/{id}/decision-priorities` returns the comparison
recomputed under the new priorities. Existing projects read as "all Medium".

## 2. Robustness and sensitivity

### Robustness (`reasoning/decision_robustness.py`)

For every pair of options and every criterion (and the weighted view), the
Monte Carlo counts the runs in which each option was higher (ties count half).

| Rule (in order) | Verdict |
|---|---|
| Point estimates differ by less than 2 points | no material difference |
| Higher option is higher in ≥ 80% of runs | robustly higher |
| … in ≥ 60% | higher, but sensitive |
| otherwise | unresolved |

A pair is **mixed** when each option is (robustly or sensitively) higher on a
different criterion — a trade-off the priorities settle — and **consistent**
when one option is higher on every criterion that differs.

### Driver sensitivity (`graph/option_sensitivity.py`)

One input at a time, on the same compiled option graphs and the same
`propagate_once` as the Monte Carlo:

* each **link strength** that can reach a success criterion is moved to
  ±2 × its Monte Carlo sigma (sigma is scaled by the link's own confidence),
  clipped to [0, 1];
* each **root claim** the options do not set is moved ±20 points (a what-if:
  the Monte Carlo does not vary priors).

The gap between the two leading options on the weighted view is recomputed at
each end. **Impact** = how far the gap moves across the range; inputs are
ranked by it (ties by key, so the ranking is deterministic). An input **can
reverse the comparison** when the gap changes sign within the range, and **can
close the gap** when it reaches zero. Levers and success criteria themselves are
never perturbed; nothing is added to the graph. Interactions between inputs are
not captured.

## 3. What would change my mind (`reasoning/mind_changers.py`)

Built only from existing tripwires, link tests and field tests. Each is a signal
for or against its theory:

| Signal | Outcome that counts | Effect on the theory |
|---|---|---|
| Tripwire (falsifies / confirms) | it happens | weakens / strengthens |
| Link test | refuted / holds | weakens / strengthens |
| Field test | refutes / supports | weakens / strengthens |

A theory that says the option *achieves* an outcome passes the effect to the
option; one that says it *threatens* it inverts it. Theories bound to no option
are left out. Ranking: unresolved first, then `|ln LR| × open question ×
on-target`, where LR follows the decisiveness stated in advance,
`open question = max(0.25, 4p(1−p))` of the decider's conviction (the model's
score until one is stated), and on-target is 1 if the theory's chain reaches a
success criterion, else 0.5. Statuses: pending, overdue, happened, did not
happen, not tested, held, refuted, inconclusive, not run, and so on.

`GET /graph/{id}/what-would-change-my-mind`.

## 4. Information priority (`reasoning/information_priority.py`)

`score = uncertainty × impact × relevance`

* **uncertainty**: `value_of_information.link_uncertainty` for a link;
  `4p(1−p)` for a root claim;
* **impact**: the driver's movement of the weighted gap in points ÷ 20, capped
  at 1 — absolute, so a 3-point movement is never "high impact" just because
  nothing moves more (bands: high ≥ 10 points, medium ≥ 3);
* **relevance**: 1 if it can reverse the comparison, 0.75 if it can close the
  gap, 0.5 otherwise.

Inputs moving the weighted gap by under half a point are not listed, unless
they can reverse the comparison on the weighted view or on any single success
criterion (`option_comparison.is_reportable`; the same rule decides which
drivers are shown). Information priority, like the drivers, concerns only the
two leading options on the weighted view; robustness covers every pair. When an open link test exists on the link, it becomes the action (with
its cheapest test). This is a heuristic priority, not an expected value of
information and not a money amount.

## In the report

Page one: key number "Weighted view" (e.g. "O1 higher · robust"), then two
separate tables — **Model-implied outcomes** (probabilities with ranges) and
**Weighted view based on decision-maker priorities** (priorities, contributions,
points). Then, flowing onto page two: **How robust is the comparison?** (what is
robust, what is uncertain, what could flip it), **What would change my mind**,
and **Information that could reduce decision uncertainty**.

## V1 limitations

The canonical list is in `HANDOVER.md`, "Decision view: intentional V1
limitations". It is kept in one place so it cannot drift from the code.

---

# Part 2: the decision workspace

Five more views on the same graph and the same comparison. Router:
`api/routes/decision_workspace.py`. Migration `026` adds nullable columns only.

## 5. Assumption register (`reasoning/assumptions.py`)

`GET /graph/{id}/assumptions`. An assumption is an **existing claim** in the
reviewed graph that the options do not set themselves (not a lever an option
switches, not a success criterion) and that has a causal path to a success
criterion. Nothing is added to the graph.

Per assumption: current belief (propagated, as on the graph screen), related
options (`bears_on` and the theories citing it), success criteria it reaches,
a summary of the documents on its links (see §6), whether a citing theory is out
of date or the claim was marked "needs evidence", its sensitivity-driver rank,
and whether moving it within its plausible range could materially alter the
comparison (it can reverse or close the gap, or moves it by 5 points or more on
the weighted view or on any criterion).

`priority = uncertainty × influence`, with `uncertainty = 4b(1−b)` and
influence the largest gap movement it causes (weighted view or any single
criterion) in points ÷ 20, capped at 1, × 1 / 0.75 / 0.5 for can-reverse /
can-close / neither. A claim that moves every option similarly but not the gap
is kept at a quarter of the weight and labelled "affects all options similarly".
Without a comparison, the model's relevance score stands in, and the register
says so. Top 8 shown.

## 6. Evidence quality (`reasoning/evidence_quality.py`)

Descriptive labels, no new score. For retrieved **documents** (graph evidence
panel, report theory sections, assumption register): recent (< 1 year) / N
years old / undated; supports / contradicts; independent / same source as N
others (same site, or same title for internal documents); direct (relevance ≥
0.7) / indirect; interested source / against the author's interest. For
**observations** that moved a conviction (theory panel history): tripwire /
link test / field test; recent (< 90 days) / N months ago; supports /
contradicts / inconclusive (likelihood ratio above 1.05 / below 0.95 / between);
independent / same event as another observation / event not named; the
decisiveness stated in advance; already in the stated conviction.

## 7. Decision journal (`reasoning/decision_timeline.py`)

`GET /graph/{id}/timeline`. Only records that carry their own timestamp:
project creation, the review audit log (`graph_operation`), theory revisions,
conviction priors, tripwire / link-test / field-test results (each with the
conviction it moved, before → after), comparable cases. Option-comparison and
priority changes had no history, so they are journalled in the existing
`event_timeline` table (`source = "decision_journal"`): a comparison entry is
written when the comparison is *viewed* and an option-implied outcome has moved
5 points or more, or the weighted verdict changed, since the last entry. It is
written when the summary loads the comparison or priorities are saved (not when
the report is exported), so its date is when the change was next *viewed*, and
the entry says earlier states were not kept. Material events (default
view): conviction moved ≥ 10 points, a fired falsifier, a refuted link, a
comparison, priority, scenario or sub-decision change, new or dropped theories.

## 8. Scenarios (`reasoning/decision_scenarios.py`)

`GET /graph/{id}/decision-scenarios`, `PUT`/`DELETE …/decision-scenarios/{upside|downside}`.
Base case = the reviewed graph. Upside / downside change a handful of existing
inputs and rerun the comparison (`build_comparison`, 100 simulations, no
drivers) on a throwaway copy of the snapshot graph; nothing is stored but the
overrides.

* **Automatic**: the 5 inputs from the sensitivity run that move the *level*
  of the weighted view most (averaged over options), each at the end of its
  plausible range that raises (upside) or lowers (downside) it — a kinder or
  harsher world for every option, not a thumb on the scale for one.
* **The decider's**: stored as a row of the existing `scenario` table
  (`decision_case`, `edge_overrides` by edge id, `claim_overrides` by claim id;
  only root claims' likelihood can be set). The scenario-fork list excludes
  these rows. Reset returns to automatic.

## 9. Sub-decisions (`reasoning/sub_decisions.py`)

`GET`/`PUT /graph/{id}/sub-decisions`, stored on `project.sub_decisions`. A
sub-decision hangs under one parent option and has 2–4 choices, each defined by
existing claims. Each choice is evaluated as `do(parent's levers) + do(its
claims = true) + do(the other choices' claims = false)` and the choices are
compared with the existing Monte Carlo under the decider's priorities, with the
same robustness vocabulary. The main comparison is unchanged: it evaluates each
option with its sub-choices as the map has them.

## V1 limitations (part 2)

The canonical list is in `HANDOVER.md`, "Decision view: intentional V1
limitations". It is kept in one place so it cannot drift from the code.
