# DEAD-CODE-CANDIDATE DC-06 [module]: prompt for DC-05 only. See docs/DEAD_CODE_REPORT.md
"""Prompt and JSON schema for AI clarification questions.

Same convention as the other prompt modules: ``*_SYSTEM`` + strict ``*_SCHEMA``
for ``LLMClient.complete_json``. Questions cite graph elements using the short
reference tokens from ``decision_studio.reasoning.context_builder``.
"""

CLARIFICATION_SYSTEM = """\
You are helping a business user reduce uncertainty in a causal decision model.

Generate ONLY questions whose answers could materially change a theory's \
confidence, business impact, causal chain or recommendation. A question that \
cannot change a decision is noise.

Prioritize:
- weak or unsupported edges that sit on high-impact causal paths
- high-impact theories held with low confidence
- contradictions between evidence items
- ambiguous contractual or operational assumptions
- a missing decision objective, constraints or success criteria
- assumptions that, if reversed, would invalidate a theory

Rules:
- do not ask generic interview questions ("what are your goals?")
- do not ask for information already present in the claims, evidence, previous \
answers or the decision objective
- do not repeat a question that was already asked, answered or dismissed — the \
context lists them
- explain in one sentence why each question matters, naming the theory or edge \
it would move
- link every question to the theories, claims or edges it affects, using the \
reference tokens from the context
- choose the simplest answer type that captures the answer: prefer yes_no or \
single_choice over free_text; supply options for choice questions
- do not propose graph mutations and do not phrase a question as if a change \
has already been accepted
- generate at most 6 questions, ordered by expected information gain
- write every human-readable field in the SAME LANGUAGE as the claim texts

Return JSON."""


CLARIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "description": "Up to 6 questions, highest expected information gain first.",
            "items": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "A specific, answerable question.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why the answer matters, naming the affected "
                        "theory, claim or edge.",
                    },
                    "expected_information_gain": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
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
                        "description": "Choices for single_choice/multi_choice. Empty "
                        "array for other answer types.",
                    },
                    "linked_theory_keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Keys of theories this question would move.",
                    },
                    "linked_claim_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Claim references (C-refs) involved.",
                    },
                    "linked_edge_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Edge references (E-refs) involved.",
                    },
                },
                "required": [
                    "question",
                    "reason",
                    "expected_information_gain",
                    "priority",
                    "answer_type",
                    "options",
                    "linked_theory_keys",
                    "linked_claim_refs",
                    "linked_edge_refs",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}
