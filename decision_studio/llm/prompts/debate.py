"""Prompt for the crux and the discriminating observation.

The model is given the overlap as an established fact rather than asked to
assess it, so it cannot contradict the graph. What it contributes is the two
things set arithmetic cannot: where the disagreement actually bites, and what
could be observed to settle it.

Note what is absent: there is no instruction to argue, and no field for a
transcript. Two agents debating are the same model twice, so the exchange
measures which side got the better prompt. The output that matters is a crux and
a test.
"""

DEBATE_SYSTEM = """\
You are finding what separates two competing explanations.

You will be told which parts of the causal chain the two share and which are \
unique to each. That overlap is already established from the graph -- do not \
re-assess it, and do not contradict it.

Your job is two things.

**The crux.** Where exactly do they part company? Name the point at which both \
accept the same situation and then draw different conclusions from it. Write it \
as: "Both accept X. A says X leads to Y; B says X leads to Z instead."

**The discriminating observation.** What could someone actually watch, before \
the decision is due, whose outcome would differ depending on which explanation \
holds?

This is the part that matters, so hold it to a standard:
- It must be CHECKABLE. "The team seems stretched" is not an observation. "The \
vendor's committed integration date moves" is.
- Its outcomes must POINT DIFFERENT WAYS. If the same result is consistent with \
both explanations, it discriminates nothing and you have not answered.
- State explicitly which outcome favours which side.
- It must be observable INSIDE the decision's time horizon. An observation that \
arrives after the decision is a post-mortem.

If no such observation exists in time, say so in `not_feasible_reason` and \
leave `discriminator` empty. That is a genuine and valuable answer: it means the \
choice between these explanations cannot be resolved before deciding, and the \
user should pick the option that survives both rather than betting on one.

Also say whether both could be true at once. Competing explanations are often \
not mutually exclusive, and if both hold the exposure is greater than either \
suggests alone.

Write in the same language as the theories.

Return JSON."""


DEBATE_SCHEMA = {
    "type": "object",
    "properties": {
        "crux": {
            "type": "string",
            "description": "Where the two chains part company, in the form "
            "'Both accept X. A says... B says instead...'.",
        },
        "discriminator": {
            "type": "string",
            "description": "A concrete observation whose outcome differs by "
            "theory, stating which outcome favours which. Empty if none exists "
            "in the available time.",
        },
        "discriminator_horizon_days": {
            "type": "integer",
            "minimum": 0,
            "maximum": 365,
            "description": "Days until it could be observed. 0 if not feasible.",
        },
        "evidence_favours": {
            "type": "string",
            "enum": ["a", "b", "neither"],
            "description": "Which side the evidence already in the graph favours. "
            "'neither' is the honest answer when it is genuinely balanced.",
        },
        "both_possible": {
            "type": "boolean",
            "description": "True if both explanations could hold at once.",
        },
        "not_feasible_reason": {
            "type": "string",
            "description": "Why no discriminating observation exists in time. "
            "Empty string when a discriminator is given.",
        },
    },
    "required": [
        "crux", "discriminator", "discriminator_horizon_days",
        "evidence_favours", "both_possible", "not_feasible_reason",
    ],
    "additionalProperties": False,
}
