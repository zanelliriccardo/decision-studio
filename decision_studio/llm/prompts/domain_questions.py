# DEAD-CODE-CANDIDATE DC-04 [module]: prompt for DC-01; nothing else imports it. See docs/DEAD_CODE_REPORT.md
"""Prompt for proposing framing questions in an unanticipated domain.

The core catalogue is fixed and the six domain packs are written by hand,
because those questions must exist before any generation has happened and must
stay comparable across projects. But we cannot anticipate every kind of
decision, and a project the six packs do not fit would otherwise get only the
generic frame.

So for those, the model proposes a pack. Note what it is *not* allowed to do:
it cannot make anything required, and it cannot restate a core question. The
gate stays uniform, and a proposed question is proposed — the user accepts it
before it is asked.
"""

DOMAIN_QUESTIONS_SYSTEM = """\
You are designing intake questions for a specific kind of strategic decision.

The person has already been asked what every decision needs: what is being \
decided, by when, how reversible, what would change their mind, what success \
looks like, who wrote their sources. Do not repeat any of that.

Your job is the questions that matter for THIS kind of decision and would be \
pointless for another one.

Rules:
- Each question must be one an experienced practitioner in this domain would \
ask and an outsider would not think of.
- Explain in one sentence why it matters. A question whose importance you \
cannot state is not worth asking.
- Include exactly one REFERENCE CLASS question: "of the times you have done \
this before, how many turned out how you expected?" phrased in the domain's own \
terms. This is usually the most valuable question in the set, because it is the \
only place a one-off decision can borrow a base rate.
- Include at least one question about WHO LOSES or WHO IS INTERESTED, since the \
credibility of a source depends on what they gain from being believed.
- 3 to 5 questions. Fewer, sharper beats more, vaguer.
- Choose the simplest answer type that captures the answer. Supply options for \
choice questions.
- Write in the same language as the decision.

Return JSON."""


DOMAIN_QUESTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "domain_label": {
            "type": "string",
            "description": "A short name for this kind of decision, e.g. "
            "'Supplier consolidation'.",
        },
        "questions": {
            "type": "array",
            "description": "3-5 questions specific to this kind of decision.",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "why": {
                        "type": "string",
                        "description": "One sentence on why this matters here.",
                    },
                    "section": {
                        "type": "string",
                        "enum": ["decision", "criteria", "belief", "sources"],
                    },
                    "answer_type": {
                        "type": "string",
                        "enum": [
                            "free_text",
                            "single_choice",
                            "multi_choice",
                            "yes_no",
                            "number",
                            "date",
                        ],
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Choices for choice questions, empty otherwise.",
                    },
                    "is_reference_class": {
                        "type": "boolean",
                        "description": "True for the one question asking how "
                        "comparable past cases turned out.",
                    },
                },
                "required": [
                    "question", "why", "section", "answer_type",
                    "options", "is_reference_class",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["domain_label", "questions"],
    "additionalProperties": False,
}
