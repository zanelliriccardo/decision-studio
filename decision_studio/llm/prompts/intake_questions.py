"""Prompt for the questions asked before the causal graph is built.

There are now three question moments, and they answer different things:

  framing        before anything    what decision is this, and whose
  **intake**     after claims       what did the documents leave ambiguous
  clarification  after theories     what would change a conclusion

This is the middle one, and it exists because the graph is expensive to build
and expensive to correct. Once causal inference has run over sixty claims,
fixing a misread claim means re-inferring its links, re-grounding its evidence
and re-propagating every belief downstream. Asking about the ambiguity while it
is still a claim costs one question.

The bar is deliberately high. A question here delays the user in front of a
progress bar, so it must be one where the answer changes the *structure* of the
graph, not merely its wording.
"""

INTAKE_QUESTIONS_SYSTEM = """\
You have just extracted a set of claims from someone's documents. Before \
building a causal graph from them, ask about anything genuinely ambiguous.

The user is waiting in front of a progress bar, so the bar is high. Ask only \
where the answer would change the STRUCTURE of the graph — what causes what, \
or whether a claim means what it appears to mean. Do not ask about wording.

Ask about:
- **Ambiguous referents.** "The delay" — whose delay, which one? If two claims \
could be about the same thing or two different things, that changes whether \
they become one node or two.
- **Direction.** Where two claims are clearly related but the documents do not \
say which way the causation runs. Getting this backwards inverts the graph.
- **Contradictions.** Two claims that cannot both be true. Which holds, or does \
the difference depend on something?
- **Missing context that changes meaning.** A figure with no baseline, a date \
with no year, a decision with no stated alternative.
- **Scope.** Whether a claim is about the whole organisation or one team, one \
period or generally.

Do NOT ask:
- for information plainly present in the claims
- generic interview questions ("what are your goals")
- anything you could reasonably infer
- about matters of degree that would only reword a claim

Rules:
- At most 5 questions. Fewer is better. Returning none is a perfectly good \
answer and means the documents were clear.
- Quote the claim you are asking about, so the user knows what you read.
- Say what changes depending on the answer. If nothing does, do not ask.
- Choose the simplest answer type. Prefer single_choice with the readings you \
are actually torn between over an open question.
- Write in the same language as the claims.

Return JSON."""


INTAKE_QUESTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "description": "Up to 5 questions. An empty list is a valid answer.",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "about_claim": {
                        "type": "string",
                        "description": "The claim this is about, quoted.",
                    },
                    "what_changes": {
                        "type": "string",
                        "description": "What the answer would change about the graph.",
                    },
                    "kind": {
                        "type": "string",
                        "enum": [
                            "ambiguous_referent",
                            "direction",
                            "contradiction",
                            "missing_context",
                            "scope",
                        ],
                    },
                    "answer_type": {
                        "type": "string",
                        "enum": ["free_text", "single_choice", "yes_no"],
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "The readings you are torn between. Empty "
                        "for free_text and yes_no.",
                    },
                },
                "required": [
                    "question", "about_claim", "what_changes", "kind",
                    "answer_type", "options",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}
