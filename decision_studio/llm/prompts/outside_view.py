"""Prompts for the outside view.

Two narrow, low-temperature tasks. Both are deliberately *reading* rather than
*estimating*: the arithmetic and the thresholds live in code, so that what the
model contributes is judgement about meaning, not numbers that would then be
treated as measurements.
"""

REFERENCE_CLASS_SYSTEM = """\
You are extracting base rates from someone's recollection of similar past cases.

You will be given a decision and a sentence or two about how comparable \
situations turned out. Convert it into explicit counts.

Rules:
- Only extract counts the user actually implies. "The last two integrations both \
slipped" is 2 of 2. "Integrations usually slip" implies no denominator -- return \
nothing for it rather than inventing one.
- "A couple" is 2. "A few" is 3. "Several" is ambiguous: skip it.
- "Most" or "usually" without a number is not countable. Skip.
- State the outcome in the user's own terms, not yours. If they said "slipped a \
quarter", the outcome is "the schedule slipped", not "project delay risk \
materialised".
- One entry per distinct outcome. If they describe two different things that \
went wrong, that is two entries.
- Never return cases_with_outcome greater than cases_total.
- If nothing countable is present, return an empty list. An empty list is a \
correct and useful answer here; a fabricated denominator is not, because the \
number will be shown to the user as their own.

Return JSON."""


REFERENCE_CLASS_SCHEMA = {
    "type": "object",
    "properties": {
        "cases": {
            "type": "array",
            "description": "Countable base rates. May be empty.",
            "items": {
                "type": "object",
                "properties": {
                    "outcome": {
                        "type": "string",
                        "description": "What happened, in the user's own terms.",
                    },
                    "cases_total": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Comparable cases the user recalls.",
                    },
                    "cases_with_outcome": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "How many produced the outcome. Never more "
                        "than cases_total.",
                    },
                    "basis": {
                        "type": "string",
                        "description": "The phrase this was read from.",
                    },
                },
                "required": ["outcome", "cases_total", "cases_with_outcome", "basis"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cases"],
    "additionalProperties": False,
}


OUTSIDE_VIEW_MATCH_SYSTEM = """\
You are matching theories to reference classes.

You will be given base rates from someone's past experience, and a set of \
theories about a current decision. Say which theory is *about the same outcome* \
as which reference class.

Rules:
- Match only when the theory is genuinely about that outcome. A theory about \
vendor readiness and a base rate about schedule slippage match only if the \
theory's conclusion IS that the schedule slips.
- A theory may match no reference class. Leave it out. Forcing a match onto the \
nearest available class would produce a comparison the numbers do not support.
- A reference class may match several theories, or none.
- Do not judge whether the theory is right. Only whether it is about that outcome.
- polarity: "same" when the theory's conclusion is that the reference outcome \
happens (the base rate is "the schedule slipped" and the theory says it will \
slip); "opposite" when its conclusion is that it does not happen (the theory \
says the date will be met).
- Give a one-line reason for each match.

Return JSON."""


OUTSIDE_VIEW_MATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "description": "Theory-to-reference-class matches. May be empty.",
            "items": {
                "type": "object",
                "properties": {
                    "theory_ref": {
                        "type": "string",
                        "description": "The theory tag, e.g. 'T0'.",
                    },
                    "reference_ref": {
                        "type": "string",
                        "description": "The reference class tag, e.g. 'R0'.",
                    },
                    "polarity": {
                        "type": "string",
                        "enum": ["same", "opposite"],
                        "description": "Whether the theory predicts the reference "
                        "outcome (same) or its absence (opposite).",
                    },
                    "reason": {
                        "type": "string",
                        "description": "One line on why these are about the same outcome.",
                    },
                },
                "required": ["theory_ref", "reference_ref", "polarity", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["matches"],
    "additionalProperties": False,
}
