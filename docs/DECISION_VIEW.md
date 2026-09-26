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
view use the same weights.

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

Inputs moving the gap by under half a point (and flipping nothing) are not
listed. When an open link test exists on the link, it becomes the action (with
its cheapest test). This is a heuristic priority, not an expected value of
information and not a money amount.

## In the report

Page one: key number "Weighted view" (e.g. "O1 higher · robust"), then two
separate tables — **Model-implied outcomes** (probabilities with ranges) and
**Weighted view based on decision-maker priorities** (priorities, contributions,
points). Then, flowing onto page two: **How robust is the comparison?** (what is
robust, what is uncertain, what could flip it), **What would change my mind**,
and **Information that could reduce decision uncertainty**.

## V1 simplifications

* Sensitivity is one-at-a-time: interactions between inputs are ignored, and it
  explains only the gap between the two leading options (all pairs get
  robustness).
* Root claim priors are perturbed by a fixed ±20 points; the Monte Carlo varies
  only link strengths, so claim drivers are what-ifs.
* The importance mapping and every threshold above are conventions, not
  calibrated values.
* Theories bound to no option do not appear in "what would change my mind".
* Field tests carry no decisiveness yet; their default ratios apply.
