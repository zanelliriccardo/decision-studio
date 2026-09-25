"""Prompt for the recommendation: what to do, given everything that was found.

The theories are separate explanations. Reading them one after another leaves
the reader to do the synthesis themselves — which is the hardest part and the
one they came for. Two theories can point the same way, or opposite ways, or be
about different things entirely, and only after weighing all of them together
can anyone say what to actually do.

So this is a distinct call over the finished set rather than a field on any one
theory. It sees each theory with its objections and tripwires, and it is told
plainly what the objections mean: they are reasons the theory may be wrong, not
decoration.
"""

RECOMMENDATION_SYSTEM = """\
You are advising someone who has to make a specific decision. An analysis has \
produced several competing explanations of their situation. Say what they \
should do.

You will see each explanation with its confidence, the objections raised \
against it, and the observations that would prove it wrong. Weigh them \
together — that synthesis is the thing being asked for, and it is not the same \
as restating the strongest one.

Rules:
- **Answer the decision as stated.** If the decision is whether to commit to a \
date, say commit or do not commit. An answer that describes the situation \
instead of choosing is not an answer.
- **Say what would have to be true.** A recommendation rests on some of the \
explanations holding and not others. Name which.
- **Account for the objections.** An explanation that has been seriously \
attacked should carry less weight, and if the recommendation depends on one \
that has, say so rather than quietly ignoring the attack.
- **Note when explanations point different ways.** If two of them imply \
opposite actions, the honest recommendation may be the option that survives \
either — say that rather than picking one and hoping.
- **Give the near-term move.** Something the person can do this week, not a \
statement of principle.
- **Be honest about strength.** If the analysis does not support a confident \
recommendation, say that plainly. A hedge stated clearly is more useful than \
confidence that is not warranted, and the reader can tell the difference.
- Write in the same language as the explanations.

Return JSON."""


RECOMMENDATION_SCHEMA = {
    "type": "object",
    "properties": {
        "recommendation": {
            "type": "string",
            "description": "What to do about the stated decision. Two or three "
            "sentences, answering the decision rather than describing it.",
        },
        "reasoning": {
            "type": "string",
            "description": "Why this follows from the explanations. Name which "
            "ones it rests on.",
        },
        "depends_on": {
            "type": "array",
            "items": {"type": "string"},
            "description": "What would have to be true for this to be right.",
        },
        "against_it": {
            "type": "string",
            "description": "The strongest case for doing something else, stated "
            "fairly. Empty string only if there genuinely is none.",
        },
        "next_step": {
            "type": "string",
            "description": "One thing to do this week.",
        },
        "confidence": {
            "type": "string",
            "enum": ["low", "moderate", "high"],
            "description": "How well the analysis supports this. 'low' is a "
            "legitimate and useful answer.",
        },
    },
    "required": [
        "recommendation", "reasoning", "depends_on",
        "against_it", "next_step", "confidence",
    ],
    "additionalProperties": False,
}
