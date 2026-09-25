# Item 4 — Monte Carlo stability

## Why the first version put strength and confidence in one number

Not an oversight. `belief_propagation.py` implements **Noisy-OR**, a standard
Bayesian-network formulation, and Noisy-OR takes exactly **one parameter per edge**
by construction: the link probability `P(effect | cause, all other parents off)`.
That single number legitimately folds magnitude and certainty together, because in
a probabilistic model they genuinely multiply into one conditional probability.

The original authors were also already uneasy with one number — `evidence_score`
and `_evidence_modulation` are a *departure* from textbook Noisy-OR, added to carry
a second dimension. They were halfway to the split.

Where it breaks is the elicitation boundary. In a classical Bayesian network that
parameter is estimated from data. Decision Studio gets it by asking a language model "how
strong is this causal connection?" — and a model answering that returns a blend of
magnitude and certainty, not a calibrated conditional probability.

So the split I made does **not** replace Noisy-OR. `strength` is still the single
Noisy-OR parameter. What changed is how it is *derived*: two answerable questions,
multiplied, instead of one unanswerable one. Same maths, better inputs. The same
story applies to `claim.confidence` — root nodes genuinely need a prior; "intrinsic
confidence" just was not one.

## What was wrong with the intervals

`compute_belief_intervals` claimed in its docstring to re-propagate. It does not.
It perturbs one node's incoming edges, recomputes that node alone, and reads its
parents' beliefs as fixed point values. Measured on a 4-hop chain:

| Node | Old width | Monte Carlo width |
|---|---|---|
| B (1 hop) | 0.160 | 0.201 |
| C (2 hops) | 0.112 | 0.202 |
| D (3 hops) | 0.078 | 0.171 |
| E (4 hops) | 0.055 | 0.141 |

The old intervals get **narrower with depth** — it reports rising confidence the
further a node sits from the evidence, which is backwards. 2.6x understated at E.
It also moved every parent in the same direction: a perfectly correlated worst case
rather than a distribution.

## What was built

`decision_studio/graph/stability.py`:

- `node_stability` / `belief_intervals` — joint perturbation, 200 runs, p10/p50/p90.
  `belief_intervals` is a drop-in shape replacement, already wired into the graph
  response, so every interval in the existing UI became honest with no frontend change.
- `compare_stability` — per-node robustness of a scenario divergence.
- `rank_stability` — p_first per option plus a `decisive` flag.
- `compile_graph` / `propagate_once` — the graph is flattened once and reused,
  so 200 runs cost one topological sort. The caller's graph is never mutated
  (the old function did mutate it).

Fidelity is asserted by test: unjittered `propagate_once` reproduces
`propagate_beliefs` exactly, including AND gates and inhibiting edges.

### Per-edge noise — where item 1 pays off

`edge_sigma(link_confidence)` scales the perturbation: confidence 0.9 gets 0.28x
the base sigma, confidence 0.2 gets 0.85x. A speculative link is shaken hard, a
certain one gently. Before the split there was no number to scale by.

### Selective common random numbers

Edges every option agrees on share one draw per run, so unrelated noise cancels.
Edges whose weight *differs* between options get independent draws — that edge is
the intervention, and each option's value for it is its own uncertain estimate.

This mattered: with fully shared noise, options differing by 0.01 in one edge came
back 100% decisive, because the shared jitter cancelled exactly the uncertainty
under test. Two identical options also needed explicit tie handling, or `max()`
handed one of them a 100% win rate.

## Verification

- 259 backend tests pass (224 + 35 new in `tests/test_stability.py`)
- 112 frontend tests pass (105 + 7 new)
- Typecheck 32 vs 33 baseline errors; none introduced

## Known limitations

1. **Sigma 0.12 is asserted, not measured.** It encodes "these numbers are good to
   about +/- 0.12". Nothing has validated that.
2. **Gaussian additive noise on the operative weight**, not on effect and
   confidence separately. The joint distribution of the two components is not
   identified by anything we have, so splitting the noise would be invented
   precision. Documented in the module rather than left implied.
3. **`rank_stability` is not wired to any endpoint yet** — scenario comparison uses
   `compare_stability`. There is no multi-scenario ranking surface to attach it to
   until item 10 gives theories a decision node to score against.
4. **200 runs on a large graph is not free.** Pure Python, no API calls, but a
   500-edge graph will be noticeable. Not benchmarked.
5. **`compute_belief_intervals` is deprecated in place, not deleted**, with the
   docstring corrected to describe what it actually does.
