# Decision Studio — A Run, End to End

**What this is.** One analysis followed from upload to recommendation, with the
actual output of every stage. Every JSON shape here matches the real schema;
every threshold is the one in the code.

**Why it exists.** The pipeline has nine stages and four reasoning steps, and
most of them have more than one possible outcome. A stage that finds nothing is
usually *not* a failure, and telling the two apart is the difference between
debugging a run and misreading it. So each stage below shows what it produces
when it works — and every other thing it can produce.

**How to read the outcome tables.** Each stage ends with one. `✓` means the run
proceeds normally, `→` means it proceeds differently, `✗` means it stops.

---

## The example

Throughout: **a construction contractor deciding whether to commit publicly to
a Q3 delivery date.** Four documents — a contract extract, two progress reports,
a vendor email thread.

The decision, typed into the box under the title:

> Whether to commit publicly to the Q3 delivery date

That one sentence is read by everything after the graph. Without it, theories
describe the situation rather than bearing on a choice — which is why the
summary page warns when it is missing.

---

# Part 1 — Before the pipeline

## Step 0 · Upload

`POST /api/v1/upload`, one call per file.

**Store first, read second.** The file is saved, then parsed. Only a 400-character
preview comes back; the full text stays on the server.

```json
{
  "document_id": "7f3a…",
  "title": "Contract extract - clause 14",
  "filename": "contract-extract.pdf",
  "size_bytes": 184320,
  "char_count": 31902,
  "text": "14.2 The Contractor shall complete the Works by the Date for Completion…",
  "extraction_error": null
}
```

| Outcome | What you see | Why |
|---|---|---|
| ✓ Text extracted | `char_count` above zero, `extraction_error` null | |
| → **Unreadable file** | `char_count: 0`, `extraction_error: "no text layer"` | **The document is kept.** A file today's parser cannot read is still the file you meant to use, and a better parser may handle it later |
| ✗ Empty file | 400 | Nothing was uploaded |
| ✗ Unsupported type | 415 | Keeping a file nothing can read only defers the same message |

An unreadable document shows as an amber chip you can remove. It does not block
the analysis.

---

## Step 1 · Intake questions

`POST /api/v1/intake` creates the project and returns **immediately** — no model
call. `POST /api/v1/intake/{id}/questions` then reads the material, which takes
five to ten seconds.

Two calls, not one, for a specific reason: the client needs a `project_id`
during those seconds, because that is exactly when you may decide not to wait.
Without an id, "start anyway" either blocks until the reading finishes or opens
a second project and abandons the first.

**The output:**

```json
{
  "questions": [
    {
      "kind": "authority",
      "question": "Who signs off on moving the date, and can you commit on their behalf?",
      "quoted_source": "",
      "rationale": "A recommendation aimed at a lever you cannot pull is wasted.",
      "options": []
    },
    {
      "kind": "ambiguity",
      "question": "\"The team lost three people\" — out of how many?",
      "quoted_source": "Following the reorganisation the team lost three people in April.",
      "rationale": "Out of eight this is the binding constraint; out of thirty it is noise.",
      "options": ["A small team, under ten", "A large team, thirty or more"]
    }
  ]
}
```

Five kinds: **authority**, **ambiguity**, **scope**, **absence**, **frame**.
Sorted with `authority` first, *before* truncation to the cap of four — so who
decides is never the question dropped. It is also the one almost never in the
documents, because documents record what happened, not who can act on it.

**`quoted_source` is verified against the material** and dropped if it does not
appear there literally, whitespace aside. A citation you cannot find in your own
document makes you doubt the document rather than answer the question.

| Outcome | What happens | Why |
|---|---|---|
| ✓ 1–4 questions | The screen appears | |
| → **Zero questions** | **You never see the screen** — it forwards straight to the analysis | Clear material needs none. The prompt says twice that returning none is correct: a model that believes it owes four questions produces four, and at that point this has become a form |
| → Generation fails | Same as zero — analysis starts | This step improves a run perfectly able to proceed without it |
| → `INTAKE_ENABLED=false` | Same as zero | Deployment-wide off switch, no rebuild needed |
| → Options too alike | Question shown with free text only | Two options meaning nearly the same thing are worse than none |

**Every question is optional.** Unanswered ones are omitted from the context
entirely — not rendered as "unknown" — which is what makes skipping genuinely
free, and what makes an empty context indistinguishable from no context at all.

**What the answers become:**

```
# How to read this material (stated by the user, authoritative)
Where this contradicts your reading, the user is right.

- "The team lost three people" — out of how many?
  -> A small team, under ten
```

Prepended to the extraction *and* inference prompts. Reaching extraction matters:
an answer arriving afterwards can only correct claims already split the wrong
way, whereas one arriving before stops them being split that way at all.

---

# Part 2 — The pipeline

Nine stages. The log now opens and closes each one:

```
=== Pipeline started for project 3f2a… ===
→ claim_extraction: started (4 documents)
← claim_extraction: done in 34.2s (476 claims) · 3 call(s), 45,000 tokens, $0.180
```

## Stage 1 · Claim extraction

Every factual assertion becomes a node, each keeping a pointer to the sentence
it came from.

```json
{
  "claims": [
    {
      "text": "The vendor has not confirmed integration dates",
      "type": "FACT",
      "confidence": 0.9,
      "prior": 0.85,
      "source_interest": "against_interest",
      "source_role": "vendor programme manager",
      "source_sentence": "We are not currently able to confirm integration dates for Q3."
    }
  ],
  "has_temporal_relevance": false
}
```

`type` — one of five:

| Type | What it is |
|---|---|
| `FACT` | Empirically verifiable, past or present |
| `ASSUMPTION` | Taken as true without evidence in the text |
| `PREDICTION` | Forward-looking |
| `OPINION` | A judgment or preference |
| `DOCUMENT_METADATA` | **About the document, not the world.** Dropped — see below |

**Two numbers that look alike and are not:**

- `confidence` — how firmly the source asserts it. A property of the text.
- `prior` — how likely it is to be true. What propagation uses.

They were one field. A document stating something emphatically is not thereby
more likely to be right, and conflating them let rhetorical force leak into
belief.

**`source_interest` moves the prior, asymmetrically:**

| Value | Effect on prior | Reasoning |
|---|---|---|
| `against_interest` | **+0.15** | The vendor admitting they cannot confirm is evidence against themselves |
| `disinterested` | — | |
| `interested` | **−0.10** | A contractor asserting the schedule is fine benefits from being believed |
| `unknown` | — | |

An admission against one's own interest is stronger evidence than a self-serving
assertion is weak. Hence the asymmetry.

**`DOCUMENT_METADATA` is dropped, and logged:**

```
Dropped 112 document-metadata claim(s) of 588 extracted
(about the paperwork, not the subject matter):
    · Alberto Invernizzi approved REX-2024-000492 on 11 July 2024.
    · The file NNG-SAI-FOU-CHA-0365 is listed as an attachment.
```

The test: **could it participate in a causal chain about the subject matter?** A
signature date cannot cause a schedule to slip. *"The approval was delayed by six
weeks"* can, and is a `FACT`.

Dropped here rather than filtered later because everything downstream costs money
to run over them — an embedding call each, a place in every similarity comparison,
a candidate slot in inference.

| Outcome | What you see | Why |
|---|---|---|
| ✓ Claims extracted | `476 claims` in the log and on screen | |
| → Some dropped as metadata | `112 metadata dropped` beside the stage | A filter removing a fifth of the input silently is one nobody can check |
| → Fewer than expected | Check the metadata count first | |
| ✗ Model returns nothing | Stage fails, project marked `failed` | Nothing to build a graph from |

### Deduplication

Cosine similarity ≥ **0.86** merges restatements, strongest prior kept.

```
Claim dedup: 588 claims -> 476 (112 merged as restatements)
```

Corroboration adds **+0.06 per additional source, capped at +0.15**. The cap is
the point: without it, a fact repeated across ten documents from one original
source acquires the weight of ten independent confirmations. The bonus is for
corroboration; the cap is because repetition is not corroboration.

> **On contract material, check this.** Two clauses can be worded almost
> identically and mean opposite things — a carve-out reading *"except where the
> delay is attributable to the Company"* sits at very high similarity to the
> same clause without it.
>
> ```
> python -m decision_studio.tools.inspect_dedup <project-id> --band 0.86 0.92
> ```
>
> Flags merges where a negation, an exception or a figure appears in only one
> member. It writes nothing. If those cluster near the threshold, raise it.

---

## Stage 2 · Causal inference

For each candidate pair: does one cause the other, and **through what mechanism**?

Not every pair is asked. Embedding similarity below **0.30** means the pair is
never sent to the model — which is also why a cross-topic link cannot be
"pruned for weakness": it was never a candidate. That distinction matters if you
ever want a denser graph.

```json
{
  "caused_claims": [
    {
      "target_index": 34,
      "mechanism": "With no confirmed integration date the test window cannot be scheduled, so defect discovery moves later",
      "effect": 0.75,
      "confidence": 0.60,
      "causal_type": "direct",
      "time_delay": "4-6 weeks"
    }
  ]
}
```

### Two numbers, not one

| | Meaning | Example |
|---|---|---|
| `effect` | How much gets through **if the link is real** | 0.75 |
| `link_confidence` | How sure we are the link **exists at all** | 0.60 |
| product | What propagates | 0.45 |

Consider two links:

```
Weak but certain          effect 0.20 × confidence 0.95  ≈ 0.19  → build the plan on it
Strong but speculative    effect 0.90 × confidence 0.20  ≈ 0.18  → go and investigate it
```

Ask for one blended "strength" and both come back near 0.5 — indistinguishable,
though they call for opposite responses.

The product is floored at **0.10** and capped at **0.95**. The cap is a
statement: nothing inferred by a language model earns certainty.

**A link without a mechanism is refused.** That requirement is the feature: it is
a correlation with an arrow drawn on it, and whoever tries to write the
connecting sentence frequently discovers there is no causal story to tell.

`causal_type` — one of `direct`, `indirect`, `probabilistic`, `enabling`,
`inhibiting`, `triggering`.

| Outcome | What you see | Why |
|---|---|---|
| ✓ Edges inferred | `confirmed 535 causal edges from 476 claims` | |
| → **No link** | Pair simply absent | The common case. Most pairs are unrelated |
| → Mechanism too short | Dropped in validation | Under 10 characters is not a mechanism |
| → Mechanism restates the claims | Dropped | *"A causes B because A causes B"* is not one either |
| → Strength outside 0.1–0.95 | Dropped | Outside the range the system permits |
| ✗ **Zero edges on a real corpus** | Suspect the schema | This happened: one deprecated field left in `properties` but out of `required` made OpenAI strict mode reject every call. `tests/test_schema_strictness.py` guards it now |

---

## Stage 3 · Blind re-scoring

Every edge scored again by a model that **cannot see the first score**. Fixed
seed 20260725, temperature 0.1, batches of 8.

```json
{
  "ratings": [
    {"index": 0, "effect": 0.55, "confidence": 0.40,
     "note": "The vendor email establishes uncertainty, not a dated commitment"}
  ]
}
```

```
Blind rescoring: 535/535 edges rescored, mean inflation 0.341
```

**Why blind.** A reviewer shown the original anchors on it and reviews the
reasoning rather than the claim. Hiding the number is the only way to get an
independent second opinion from the same model.

**That 0.341 is worth knowing on its own** — the first pass is systematically
34% overconfident. That is a fact about how these models estimate, not about
your documents.

| Outcome | What you see | Why |
|---|---|---|
| ✓ Scores revised | `mean inflation 0.341` | Some inflation is normal |
| → Inflation near zero | The first pass was well calibrated, or the model recognised its own output | Worth investigating rather than celebrating |
| → Inflation above ~0.5 | The generation prompt is badly overconfident | A prompt problem, not a data one |
| → **Reasoning model in use** | Inflation is noisier | Reasoning models ignore both seed and temperature, so this stops being a reproducible second *measure* |

---

## Stage 4 · Bias audit

```json
{
  "bias_warnings": [
    {
      "type": "survivorship",
      "explanation": "Progress reports are written by the delivery team; failed workstreams are under-represented",
      "severity": 0.6
    }
  ]
}
```

An empty list is common and correct.

---

## Stage 5 · Evidence grounding

Two web searches per edge — 34 for a 17-edge graph, 1,070 for a large one —
plus local NLI scoring of each snippet.

**Capped at 180 seconds.** Beyond that the stage is abandoned cleanly:

```
Evidence grounding exceeded 180s and was abandoned;
412 edge(s) remain ungrounded
```

This is the one stage whose absence is survivable, which is what makes it the
right place to give up. The reason is the **evidence floor**:

> An edge with no evidence still propagates at no less than **0.30**. Only an
> edge with an actual contradiction may go below it.
>
> *"We could not look"* and *"we looked and found nothing"* are different states,
> and only the second is evidence of absence. Without the floor, an edge nobody
> searched for was indistinguishable from one actively refuted — and since search
> coverage is uneven, that quietly deleted whole regions of the graph based on
> which queries happened to return results.

| Outcome | What you see | Why |
|---|---|---|
| ✓ Edges grounded | `edges_grounded: 128` | |
| → **No search key** | Stage skipped entirely | Brave/DuckDuckGo optional; the floor covers it |
| → **No edges** | Stage skipped | Nothing to ground |
| → Timeout | Partial results kept, warning logged | A weaker graph, not a broken one |
| → **NLI not installed** | Every snippet scores 0, warned once | `pip install -e ".[nli]"` — about 2 GB. Without it, retrieved evidence contributes nothing until installed |

---

## Stages 6–7 · Statistical validation and discovery

**Statistical validation** runs Granger causality or the PC algorithm where
numeric time series exist. On document-only corpora it finds nothing, which is
correct rather than broken.

**Discovery** extracts additional claims from evidence snippets, then infers
links involving only the new ones.

```
Statistical validation committed: 3 confirmed, 0 unsupported, 1 contradicted
No edges with evidence snippets; skipping discovery
```

---

## Stage 8 · DAG construction

Cycles are broken by removing the weakest edge in each, and the removed edges are
**marked `is_feedback` and committed**. That matters: without persisting the
result, every subsequent read of the graph recomputes it — hundreds of log lines,
and a layout that never settles because the edge set differs between requests.

**Fragmentation is measured on every run:**

```
Built DAG with 476 nodes and 535 edges — 58 connected component(s),
largest holds 398 node(s), 46 isolated
```

**Read this number.** A graph in dozens of pieces is not a graph of the decision
— it is several unrelated graphs sharing a canvas, and a theory spanning two of
them is joining things that do not communicate.

Note the density: 535 edges over 476 claims is barely one per node. Sparse in
absolute terms, not only divided by topic.

| Outcome | What it means | What to do |
|---|---|---|
| ✓ Few components, large main one | A connected graph | |
| → **Many components** | The documents discuss unconnected things | Expect theories to be narrower, and check them for spanning |
| → Many isolated nodes | Claims nothing links to | Often metadata that escaped the filter, or genuinely unrelated material |
| → Cycles broken | Feedback loops in the material | Recorded, not an error |

---

## Stage 9 · Belief propagation

Noisy-OR over topological order.

**A caveat worth carrying:** Noisy-OR assumes the causal mechanisms are
independent. In strategy this is routinely false — two paths to the same outcome
usually share a hidden common cause. So the propagated belief is biased
**upward** exactly where paths converge, which is exactly where the graph is
most interesting.

### Monte Carlo

200 runs, per-edge noise σ = 0.12 scaled by `link_confidence` — so a link we are
unsure about is perturbed more than one we are not.

The answer is *"A wins in 52% of simulations"*, not *"A wins"*. **The system
contradicting its own single answer is the point.**

---

# Part 3 — Reasoning

These four run automatically after the graph, each in its own database session.
A committed twenty-minute run must not be lost because a later model call timed
out.

## Theories

```json
{
  "theories": [
    {
      "title": "Vendor readiness gates the Q3 date",
      "summary": "The vendor has not confirmed integration dates, which compresses the test window…",
      "status": "supported",
      "causal_chain": ["C12", "E4", "C34", "E9", "C41"],
      "supporting_claim_refs": ["C12", "C34", "C41"],
      "supporting_edge_refs": ["E4", "E9"],
      "supporting_evidence_refs": ["V2"],
      "contradicting_evidence_refs": ["V7"],
      "weak_assumptions": ["Critical-path exposure is unconfirmed"],
      "confidence": 0.72,
      "business_impact": "high",
      "recommendation": "Move the public commitment to Q4"
    }
  ],
  "insufficient_reason": ""
}
```

**Reference tokens, not UUIDs.** A model asked to reproduce a UUID produces
something UUID-shaped that does not exist, and a fabricated citation that
*parses* is worse than one that fails — it gets persisted and looks
authoritative. A hallucinated `C97` in a 60-claim graph fails to resolve and is
dropped.

`status` — `hypothesis`, `supported`, `contested`, `insufficient_evidence`.

### Chain connectivity

Each edge in the chain must **join the claim before it to the claim after it**.
Resolution is not enough.

Before this check, chains like this reached the brief:

```
The contract does not specify the equalisation window.
  ↓ Poor internet disrupted data exchange onboard vessel C1.
Repeated price-reduction requests consumed time.
```

Every token real. Nothing missing. Still fiction.

| Verdict | What happens |
|---|---|
| `connected` | Kept |
| `reversed` | **Dropped**, recorded separately. In a causal graph the direction *is* the assertion, so a model that reversed it got the theory wrong rather than the transcription. Silently flipping it would repair the sentence and keep the error |
| `disconnected` | Dropped |

**A theory with zero connected links is dropped entirely** — not shown with lower
confidence. It is not a weak theory; it is a list of claims with prose between
them, and lowering its confidence would leave it in the ranking beside real ones.

The threshold is **one link, not a fraction**. On a two-edge chain "over half"
and "all" coincide, so a fraction would add a hand-picked constant without
adding a distinction.

Surviving theories carry the count, shown everywhere the ranking appears:

```
2  Create one reconciled material-data control   moderate   4 of 5 links verified
1  Close the topside weight gap                       low   1 of 3 links verified
```

Deliberately **not** folded into the score: weighting integrity there would be
another uncalibrated constant. It is exposed instead.

| Outcome | What you see | Why |
|---|---|---|
| ✓ Theories generated | 3–5 typically | |
| → **`insufficient_reason` set** | *"No decision-relevant theory can be supported by an explicit causal path"* | Honest, and usually points upstream: a graph too fragmented or too sparse to reason over |
| → Theory dropped | `no_connected_chain` in the report | Visible, not hidden — that four theories were generated and none held is information |
| → Chain shown with a gap | *"⚠ no verified link here"* | Better than a break rendered as continuity |
| → No decision stated | Theories describe rather than recommend | The summary page warns |

## The adversary

Sees the causal chain, the claims and the evidence — **never the title, summary
or recommendation**. Given the prose it critiques the writing; given the
structure it attacks the argument. Temperature 0.7.

```json
{
  "objections": [
    {
      "objection": "The entire chain rests on a single vendor email from March; no subsequent communication is cited",
      "kind": "single_source",
      "severity": 0.8
    }
  ],
  "strongest_defence": "The email is from the vendor's own programme manager, and is against their interest"
}
```

Kinds: `common_cause`, `single_source`, `reversal`, `scope`, `timing`,
`incentive`, `other`.

**Objections cost rank:**

```
objection_load  = mean(severities)
adjusted_score  = confidence × (1 − 0.5 × load)
contested       = load ≥ 0.45
```

`mean`, not `sum`: with sum, a theory attacked five times weakly would rank below
one attacked once devastatingly, which is backwards.

**An objection that changes no ranking is decoration.** That is why it is
arithmetic. You can dismiss one you judge unfounded — but it takes a deliberate
act; the default is that criticism has weight.

> **On existing projects:** objections generated before the connectivity check
> are marked `pre_connectivity_check`. The adversary was criticising a text that
> did not describe the graph, and those objections fed `adjusted_score`. Marked
> rather than deleted or regenerated — they may still be sound, and their
> provenance is what you need to weigh them.

## Tripwires

```json
{
  "tripwires": [
    {
      "observable": "The vendor confirms an integration date in writing",
      "direction": "falsifies",
      "horizon_days": 14
    }
  ]
}
```

You cannot run an experiment on a strategic decision. You can write down, before
the outcome is known, what would change your mind — and be held to it.

When one fires, its theory is flagged stale automatically. **This is the only
route by which new information about the world enters after the analysis.**

## Debates

Overlap is computed from the graph before any model is called, on **edges** not
claims — two theories about the same decision share claims by construction; the
links differ.

| Overlap | Relation | What happens |
|---|---|---|
| ≥ 0.70 | `same_story` | **Never sent to the model.** One theory in two wordings |
| ≤ 0.20 | `orthogonal` | Different subjects; both may hold |
| between | `competing` | Worth a model call |

```json
{
  "crux": "Whether the binding constraint is vendor readiness or internal scope creep",
  "discriminator": "Whether the vendor confirms a date before the scope freeze completes",
  "discriminator_horizon_days": 21,
  "evidence_favours": "a",
  "both_possible": false,
  "not_feasible_reason": ""
}
```

| Outcome | What it means |
|---|---|
| ✓ Crux + discriminator | Promotable to a tripwire on **both** theories — explicitly, with confirmation, never automatically |
| → `not_feasible_reason` set | **Nothing separates them before the deadline.** That is the finding: prefer the option robust to both |
| → Fewer than two theories | Skipped, logged as `skipped` not as an error |

## The recommendation

One synthesis across **all** theories, distinct from the per-theory
`recommendation` field. Stacking those produces contradictory advice with nothing
to resolve it.

The prompt sees each theory **with its objections and tripwires** — a
recommendation resting on a contested explanation is weaker than one resting on
an unattacked one, and the model cannot account for that if it never sees the
attacks.

```json
{
  "recommendation": "Commit to Q4 rather than Q3.",
  "reasoning": "Two of the three explanations point at vendor readiness as the binding constraint. The strongest has been objected to on one ground, which is why the recommendation is to move the date rather than renegotiate.",
  "depends_on": [
    "The vendor cannot confirm before September",
    "Scope stays as agreed"
  ],
  "against_it": "If the vendor confirms next week, Q3 is still reachable and moving now costs credibility for nothing.",
  "next_step": "Ask the vendor's programme manager for a dated written commitment.",
  "confidence": "moderate"
}
```

**`confidence: "low"` is an explicitly legitimate answer.** A hedge stated
clearly beats confidence that is not warranted, and the reader can tell the
difference.

| Outcome | What you see |
|---|---|
| ✓ Recommendation | Opens the summary page and page one of the PDF |
| → `low` confidence | Shown as such. The analysis does not support a confident answer |
| → No theories | Skipped; the page offers a button to generate later |
| → Theories regenerated since | Marked stale — it answers a question about explanations you can no longer find |

---

# Part 4 — What you get

## The summary page

`/summary/:projectId`, where the analysis lands. The graph is a link at the
bottom, not the destination: a graph is the material a conclusion is made from.

Order:

1. **The stated decision** — editable in place, because people often work out
   what they are deciding only after seeing what the documents contain
2. **The recommendation** — with what it depends on and the case against
3. **Each theory in full** — chain step by step, what argues against it, weak
   assumptions, comparison with past cases, tripwires with dates
4. **How to read this**
5. **What this cost** — collapsible, per stage
6. Links to the graph and the PDF

**Objections sit beside the conclusion, not in an appendix.** Burying them is how
a qualification gets lost between the analysis and the meeting.

## The PDF

**Page one stands alone**: the decision, the recommendation with its conditions,
the case against, the next step, a one-row-per-theory table with chain integrity
and objection counts, and the caveats.

A brief requiring four pages before the conclusion gets skimmed to the conclusion
anyway, losing the qualifications on the way. Conclusion *and* caveats on the
same page means the reader who reads only one page gets both.

Pages after: theories in full, with each kept whole so a page break cannot
separate a conclusion from what undermines it.

## What it cost

```
Spend: 112 model call(s) · 225,000 in / 47,200 out tokens · $1.02
    blind_scoring             67 call(s)   120,600 tokens  $0.452
    causal_inference          40 call(s)    96,000 tokens  $0.360
    claim_extraction           3 call(s)    45,000 tokens  $0.180
    theory_generation          2 call(s)    10,600 tokens  $0.032
```

Ordered by cost: the question is always *what consumed the money*, never *what
ran first*.

Two honesty requirements, both visible rather than buried:

- **Token counts are exact** — they come from the provider's own usage field.
- **Costs are advisory.** Computed from a hard-coded price table whose date is
  shown beside them. They make one run comparable to another and will not
  reconcile with an invoice. Calls to a model with no price entry are counted
  separately, so an unrecognised model does not read as a cheap run.

---

# Part 5 — What the system refuses to do

Each of these makes the output less impressive. Each is there because the
alternative is worse.

| It will not | Because |
|---|---|
| Raise confidence because simulated stakeholders agreed | Five simulated people agreeing measures the model's agreeableness, not the world. Their **objections** still count at severity 0.35 — a budget problem raised by a simulated CFO will be raised by the real one |
| Show confidence as a percentage | Nothing here has been calibrated against outcomes. You get *"moderate"* |
| Declare a winner the analysis does not support | 200 runs with the uncertainty varied: *"A wins in 52%"* |
| Invent a base rate | Told *"integrations usually slip"* it produces nothing. A fabricated denominator would be shown back to you as your own recollection |
| Force a conclusion between competing theories | If nothing observable separates them before your deadline, it says so |
| Record a causal link without a mechanism | A link without one is a correlation with an arrow drawn on it |
| Show a chain whose links do not connect | The theory is dropped, and the drop is reported |

**The cost, stated plainly.** The tool is less satisfying than it could be. It
says *"moderate"* where you wanted 72%, *"coin flip"* where you wanted a winner.
Someone used to hard numbers will find it evasive.

The bet is that a tool which can say *"I don't know"* is believed when it says
something else.

---

# Appendix — Reading a run

## The log, start to finish

```
=== Pipeline started for project 3f2a… ===
→ claim_extraction: started (4 documents)
Dropped 112 document-metadata claim(s) of 588 extracted
Claim dedup: 476 claims -> 412 (64 merged as restatements)
← claim_extraction: done in 34.2s (412 claims) · 3 calls, 45,000 tokens, $0.180
→ causal_inference: started (412 claims)
  causal_inference: 180/412 (44%) after 62s, 2.9/s
BFS: confirmed 535 causal edges from 412 claims
← causal_inference: done in 141.7s (535 edges) · 40 calls, 96,000 tokens, $0.360
→ blind_scoring: started (535 edges)
Blind rescoring: 535/535 edges rescored, mean inflation 0.341
Skipping evidence grounding (no search client or no edges)
Built DAG with 412 nodes and 535 edges — 58 component(s), largest 398, 46 isolated
=== Pipeline completed for project 3f2a… in 312s: 412 claims, 535 edges ===
    Spend: 112 model call(s) · 225,000 in / 47,200 out tokens · $1.02
```

## Lines worth stopping at

| Line | What it tells you |
|---|---|
| `Dropped N document-metadata claim(s)` | How much was paperwork. A third is normal on technical documents |
| `dedup: X -> Y` | If Y is far below X on contract material, run `inspect_dedup` |
| `mean inflation` | How overconfident the first scoring pass was |
| `N connected component(s)` | Whether you have one graph or an archipelago |
| `Skipping evidence grounding` | No search key, or no edges. Check which |
| `exceeded 180s and was abandoned` | Search backend rate-limiting. The graph is weaker, not broken |
| `Spend:` | What it cost, and which stage |

## When something looks wrong

| Symptom | Most likely cause |
|---|---|
| Zero edges | Schema strict-mode violation — every inference call rejected |
| Theories say "no causal path" | Graph too fragmented; check the component count |
| Few claims | Metadata filter, or short documents. The log distinguishes them |
| Pipeline appears hung after the graph | Evidence grounding against a rate-limited search backend. Capped at 180s |
| A stage runs long and silent | Warned in the log after 45 seconds |
| `relation "..." does not exist` | Run `alembic upgrade head`. The startup check names the missing objects |
