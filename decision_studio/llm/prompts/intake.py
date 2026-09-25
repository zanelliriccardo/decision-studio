"""Prompt for the questions asked before the pipeline starts.

Three question systems were built in this repository and all three removed. The
common fault was never *asking* — it was **where**: the framing form blocked
theory generation, the first intake paused a twenty-minute run halfway through.
This one runs before the orchestrator is called, so there is nothing to pause
and nothing to block.

The prompt is written against one failure mode above all others: a model that
believes it owes the user four questions will produce four, and at that point
the intake has become the framing form again. So it says twice, in different
words, that returning none is correct.

The other constraint worth knowing is that answers are **interpretive**. They
change how the material is read; they never become claims. A claim carries
provenance, evidence grounding, a bias audit and a prior separate from its
confidence — a sentence typed into a box has passed through none of those gates,
and admitting one as a node would route around the whole apparatus. So the
prompt asks about reading the material, not about facts absent from it.
"""

INTAKE_SYSTEM = """\
You are about to analyse someone's documents and build a causal graph from \
them. Before you start, you may ask them a few questions — but only where an \
answer would change how you read the material.

**Returning no questions is a correct and common answer.** Clear material needs \
none. Do not manufacture questions to fill a quota.

Ask only where one of these holds:

- **authority** — who is making this decision, and what they can actually \
change. This is almost never written in the material: documents record what \
happened, not who has the power to act on it. A recommendation aimed at a lever \
the reader cannot pull is wasted.
- **ambiguity** — a term, figure or referent that could be read two ways, where \
the two readings lead somewhere different. "The team lost three people" means \
one thing out of eight and another out of thirty.
- **scope** — what is in and out of the decision, when the material implies a \
boundary it does not state.
- **absence** — something conspicuously missing that the reader would know. Not \
"what else is there", but "this references a schedule that is not here".
- **frame** — what the reader already believes about the situation, where the \
material is compatible with opposite readings.

Do NOT ask:
- anything the material answers
- anything you can reasonably infer
- for facts to add — you are asking how to READ this material, not for more of it
- general interview questions about goals or strategy
- more than one question about the same thing

For each question:
- **Quote the sentence it is about**, word for word from the material, when \
there is one. Copy it exactly; do not paraphrase or tidy it.
- **Say what answering would change** about the analysis. If you cannot say, do \
not ask.
- Offer up to 3 options **only when you genuinely see distinct readings**. Two \
options that mean nearly the same thing are worse than none — free text is \
always available. Zero options is fine.

Write in the same language as the material.

Return JSON. An empty question list is valid."""


INTAKE_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "description": "0 to 4 questions. Empty is valid and common.",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": [
                            "authority", "ambiguity", "scope", "absence", "frame"
                        ],
                    },
                    "question": {"type": "string"},
                    "quoted_source": {
                        "type": "string",
                        "description": "The sentence this is about, copied "
                        "verbatim from the material. Empty string when the "
                        "question is not about one specific sentence.",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "What answering would change about the "
                        "analysis. One sentence.",
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "0 to 3 distinct readings. Empty when "
                        "you do not see genuinely different ones.",
                    },
                },
                "required": [
                    "kind", "question", "quoted_source", "rationale", "options"
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}
