# Items 1, 2, 5, 6 — implemented

## What changed

**1. `edge.strength` split into `effect` × `link_confidence`**
`causal_inference.py` now asks two questions instead of one blended one, with an
explicit instruction not to average them. `decision_studio/graph/edge_weight.py` owns the
collapse (`edge_strength`, floor 0.10, ceiling 0.95) so pipeline, API and graph maths
cannot disagree about what `strength` means. `strength` remains a stored column
holding the product, so every existing consumer works unchanged.

**2. `claim.prior` separated from `claim.confidence`**
`confidence` keeps its original meaning — how firmly the *source* asserts the claim.
`prior` is new: the probability the claim is actually true, elicited with explicit
instruction to weigh source type, hedging and author incentive (the prompt carries the
vendor-deck vs internal-admission worked example). `belief_propagation._root_prior`
now seeds root beliefs from `prior`, falling back to `confidence` for pre-split graphs.
`graph/propagation.py` and `dag_builder.py` follow the same rule.

**3. Semantic claim dedup** — `decision_studio/pipeline/claim_dedup.py`
Cosine on existing claim embeddings at threshold 0.86, strongest-prior-first so the
best-supported phrasing survives. Merged sentences are kept in `corroborated_by`;
`prior` gets a bounded lift (0.06 per extra source, capped at 0.15) so three reports
outweigh one without triple-counting. Claims without embeddings are never merged.
Runs after embedding, before evidence grounding.

**4. Blind rescoring** — `decision_studio/pipeline/blind_rescorer.py` + `llm/prompts/blind_scoring.py`
New pipeline stage `blind_scoring` between causal inference and bias audit. Pools every
edge, strips identifiers, shuffles with a fixed seed, rates in batches of 8 at
temperature 0.1. Author scores are preserved in `author_effect` / `author_confidence`
and the gap is reported as inflation. A failed batch keeps author scores rather than
dropping or zeroing edges.

## Migration

`alembic/versions/005_split_conflated_scores.py`, reversible. Back-fill preserves every
existing number exactly:
- `effect = strength`, `link_confidence = 1.0` → product equals the old strength
- `prior = confidence` → no propagated belief moves

So upgrading changes no output until the pipeline is re-run.

## Verification

- 224 backend tests pass (183 pre-existing + 41 new in `tests/test_score_separation.py`)
- 105 frontend tests pass (89 pre-existing + 16 new in `ScoreSeparation.test.tsx`)
- Migration upgrade → downgrade → upgrade clean
- Typecheck: 32 errors vs 33 on the untouched baseline (one pre-existing error fixed
  earlier, none introduced)

```bash
alembic upgrade head
TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/decision_studio_test pytest
cd frontend && npm test
```

## Known limitations

1. **Blind scoring blinds ownership, not rhetoric.** The rater still reads the mechanism
   text, so a fluent mechanism still outscores a terse identical one. Measuring that
   needs a two-stage rate (pair alone, then pair + mechanism) at double the calls.
2. **Dedup threshold 0.86 is untuned.** Chosen conservatively — a false merge loses
   information irrecoverably, a missed merge only leaves current behaviour in place.
3. **Corroboration treats distinct source sentences as independent.** Three reports
   quoting one original still count as three.
4. **Models may ignore the two-field schema.** `_components()` falls back to the legacy
   single `strength` rather than defaulting everything to 0.5.
5. **Item 4 (Monte Carlo) is not done**, so `sigma` cannot yet be scaled by
   `link_confidence` — the main payoff of item 1 is still unrealised.
6. **`evidence_score` is untouched** (that is item 3). It still gates edge transmission
   with a zero floor, so absence of evidence is still treated as refutation.
