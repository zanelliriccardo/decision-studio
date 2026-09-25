"""Prompt and schema for blind re-scoring of causal links.

The call that proposes an edge also writes its mechanism and assigns its score.
It cannot separate the argument from the prose it has just produced, so a
well-written mechanism reliably outscores a terse, identical one — verbosity buys
causal strength.

This prompt drives a second, colder pass. It receives a shuffled pool of claim
pairs drawn from the whole graph with every identifier stripped, so the rater
cannot tell which argument an edge serves, who proposed it, or what score it was
originally given.

The known limit, stated plainly: the rater still reads the mechanism text, so
this blinds *ownership* rather than *rhetoric*. Measuring rhetoric would require
rating each pair twice — with and without the mechanism — at double the calls.
"""

BLIND_SCORING_SYSTEM = """\
You are rating proposed causal links. You are not building an argument and you \
do not know what any of these links are for.

Each item gives a CAUSE, an EFFECT and a PROPOSED MECHANISM. For each, answer \
two separate questions:

- effect (0.0-1.0): if this link is real, how MUCH does the cause move the \
effect? Judge leverage and magnitude, not plausibility.
- confidence (0.0-1.0): how CERTAIN are you the link exists at all? Judge \
whether the mechanism actually establishes causation, or merely asserts it.

These are independent. A link can be small but certain, or large but \
speculative. Never average them into a single judgement.

Rules:
- Rate each item only on its own content. The items are unrelated to each other \
and appear in no meaningful order.
- A fluent, confident or detailed mechanism is not more likely to be true. \
Length and polish are not evidence. Rate the causal claim, not the writing.
- Watch for mechanisms that restate the correlation instead of explaining it \
("X leads to Y because X causes Y"). These deserve low confidence however \
well phrased.
- Watch for plausible common causes that would produce the same pattern with no \
direct link. These lower confidence.
- Be willing to give low scores. Most proposed causal links in real documents \
are weaker than their authors believe.
- Return one rating per item, using the item's index.

Return JSON."""


BLIND_SCORING_SCHEMA = {
    "type": "object",
    "properties": {
        "ratings": {
            "type": "array",
            "description": "One rating per input item, in any order.",
            "items": {
                "type": "object",
                "properties": {
                    "index": {
                        "type": "integer",
                        "description": "The ITEM number this rating is for.",
                    },
                    "effect": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "Effect size if the link is real, 0-1.",
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "Certainty the link exists at all, 0-1.",
                    },
                    "note": {
                        "type": "string",
                        "description": "At most one short sentence, only when the "
                        "score needs explaining. Empty string otherwise.",
                    },
                },
                "required": ["index", "effect", "confidence", "note"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["ratings"],
    "additionalProperties": False,
}
