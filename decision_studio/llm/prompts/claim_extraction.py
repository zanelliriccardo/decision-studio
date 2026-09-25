"""Prompts and schemas for Stage 1: Claim Extraction."""

CLAIM_EXTRACTION_SYSTEM = """\
You are an expert analyst specializing in deconstructing arguments, narratives, \
and complex texts into their fundamental atomic claims.

Your task is to extract every distinct claim from the provided text. A claim is a \
single, self-contained assertion that can be independently evaluated for truth or \
plausibility. Follow these principles:

1. **Atomicity**: Each claim must express exactly one idea. If a sentence contains \
multiple assertions, split them into separate claims.

2. **Completeness**: Extract ALL claims present in the text. Do not omit implied \
claims that are clearly part of the reasoning chain.

3. **Faithfulness**: Preserve the original meaning. Do not editorialize or add \
interpretation. Rephrase only for clarity and to make the claim self-contained \
(i.e., resolve pronouns and ambiguous references).

4. **Classification**: Assign each claim one of the following types:
   - FACT: An empirically verifiable statement about the world (past or present).
   - ASSUMPTION: A premise taken as true without explicit evidence in the text, \
often foundational to the argument.
   - PREDICTION: A forward-looking statement about what will or might happen.
   - OPINION: A subjective judgment, evaluation, or preference.
   - DOCUMENT_METADATA: A statement about the document itself rather than about \
the world it describes. Who signed, reviewed or approved it; its revision \
number, date or status; which files are attached to it; page or section \
numbering; distribution lists. "Alberto Invernizzi approved REX-2024-000492 on \
11 July 2024" is DOCUMENT_METADATA. "The approval was delayed by six weeks" is \
a FACT, because it is about what happened rather than about the paperwork.

   The test is whether the statement could participate in a causal chain about \
the subject matter. A signature date cannot cause a schedule to slip; a delayed \
approval can.

5. **Confidence** (0.0 to 1.0): How firmly does the SOURCE TEXT assert this?
   This measures the writing, not the world.
   - 0.9-1.0: Stated flatly as fact, no hedging.
   - 0.6-0.8: Asserted, with mild qualification.
   - 0.3-0.5: Hedged -- "possibly", "it appears", "we think".
   - 0.0-0.2: Raised only as a question or a remote possibility.

6. **Prior** (0.0 to 1.0): How likely is the claim ACTUALLY TRUE?
   This is a different question and often has a different answer. Weigh:
   - Source type: an internal status report outranks a sales deck.
   - Incentive: does the author BENEFIT from this being believed? A vendor
     promising delivery is weak evidence. A team admitting its own slip is
     strong evidence, precisely because admitting it costs them something.
   - Hedging: in an internal document, hedged admission of a problem usually
     means yes. Emphatic assertion by an interested party usually means less
     than it sounds.
   - Verifiability: can it be checked, and would someone have checked?

   Worked example -- these two get OPPOSITE pairs:
   - "The vendor will absolutely deliver by Q3." (vendor's own deck)
     confidence 0.95 (emphatic), prior 0.35 (interested party, unverified)
   - "It's possible the freeze slipped, though I'm not certain." (eng lead, internal)
     confidence 0.35 (hedged), prior 0.80 (costly admission, insider knowledge)

   When the source is neutral and disinterested, the two may legitimately match.

7. **Source role and interest**: who is asserting this, and do they gain from it
   being believed? Answer per claim, because one document often carries claims
   from several parties.
   - against_interest: the author admits something that costs them -- a team
     conceding its own slip, a supplier flagging its own risk. This is the
     STRONGEST kind of testimony, because nobody volunteers bad news about
     themselves without reason.
   - disinterested: the author has no stake in which way it goes.
   - interested: the author benefits from being believed -- a vendor promising
     delivery, a department defending its budget, a consultant recommending more
     consulting.
   - unknown: the document does not say who is asserting it.

   Record source_role in plain words ("the vendor's account manager", "the
   engineering lead") so the judgement can be audited rather than trusted.

6. **Temporal Relevance**: Determine whether the input describes events that unfold \
over time with meaningful temporal relationships (e.g., geopolitical crises, market \
reactions, disaster cascades — where the timing between cause and effect is a real, \
distinguishing characteristic) versus conceptual or structural content where time is \
not meaningful (e.g., startup idea validation, philosophical arguments, product feature \
evaluation). Set `has_temporal_relevance` to true ONLY for event-driven content.

7. **Provenance**: For each claim, include the original sentence from the input text \
(verbatim) that the claim was derived from. This enables audit trails.

Return your analysis as a JSON object. Order the claims as they appear in the text.

IMPORTANT: Write all claim texts in the same language as the input text."""

CLAIM_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The atomic claim, rephrased for clarity and self-containment.",
                    },
                    "type": {
                        "type": "string",
                        "enum": [
                            "FACT", "ASSUMPTION", "PREDICTION", "OPINION",
                            "DOCUMENT_METADATA",
                        ],
                        "description": "The classification of this claim.",
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "How firmly the SOURCE asserts this, 0-1. "
                                       "A property of the text, not of the world.",
                    },
                    "prior": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "Probability the claim is actually TRUE, 0-1. "
                                       "Weigh source type, author incentive and "
                                       "hedging. Often differs from confidence.",
                    },
                    "source_interest": {
                        "type": "string",
                        "enum": ["against_interest", "disinterested",
                                 "interested", "unknown"],
                        "description": "Does whoever asserts this gain from it being "
                                       "believed? An admission that costs the author "
                                       "is strong evidence.",
                    },
                    "source_role": {
                        "type": "string",
                        "description": "Who is asserting it, in plain words. Empty "
                                       "string if the document does not say.",
                    },
                    "source_sentence": {
                        "type": "string",
                        "description": "The original sentence(s) from the input that this claim was extracted from, verbatim.",
                    },
                },
                "required": ["text", "type", "confidence", "prior",
                                 "source_interest", "source_role",
                                 "source_sentence"],
                "additionalProperties": False,
            },
        },
        "has_temporal_relevance": {
            "type": "boolean",
            "description": "True if content describes events with real temporal relationships, false for conceptual analysis.",
        },
    },
    "required": ["claims", "has_temporal_relevance"],
    "additionalProperties": False,
}
