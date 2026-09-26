"""Prompt and JSON schema for decision-oriented theory generation.

Follows the repo's prompt convention: a ``*_SYSTEM`` string plus a strict
``*_SCHEMA`` passed to ``LLMClient.complete_json``.

Graph elements are cited by the short reference tokens produced by
``decision_studio.reasoning.context_builder`` (``C1``, ``E4``, ``V2``) rather than by
UUID. Anything the model invents fails to resolve during validation, so
fabricated provenance cannot reach the database.
"""

THEORY_GENERATION_SYSTEM = """\
You are a senior decision analyst working from a causal graph that a human has \
already reviewed.

Your task is to generate a small set of distinct, decision-relevant theories. A \
theory is a causal explanation supported by explicit graph paths and evidence. \
It is not a summary of the input, not a restatement of individual nodes, and it \
must not introduce unsupported claims.

For each theory:
- explain what may be happening and why it matters to the decision
- identify the exact supporting claims (C-refs), edges (E-refs) and evidence \
(V-refs) from the context
- list contradicting evidence and weak assumptions honestly
- distinguish supported conclusions from hypotheses
- estimate confidence without overstating certainty
- state the business impact
- recommend one concrete decision or validation action
- name only the additional information that would materially change the theory

Rules:
- use ONLY the references supplied in the generation context; never invent a \
reference token
- an element that is absent from the context was rejected or disabled by the \
user, or is out of scope — never reconstruct it
- respect human notes and strength overrides: they outrank your own inference
- when the context contains OUTCOME claims (the user's success criteria), a \
theory bears on the decision only if its causal chain reaches one: end the chain \
at an OUTCOME claim wherever the graph allows. A theory whose chain reaches no \
outcome is describing the situation — say so in weak_assumptions
- treat business-critical status as a relevance signal, not as proof
- do not fabricate sources, quotes or identifiers
- avoid duplicate theories: two theories resting on substantially the same \
causal path are one theory
- generate 3 to 7 theories when the graph supports them; generate fewer, or \
none, when it does not. Never pad
- if the evidence is thin, say so with status "hypothesis" or \
"insufficient_evidence" rather than inflating confidence
- when a previous theory is supplied and your theory continues it, set \
previous_theory_key and explain the material change in change_explanation, \
including why confidence moved after the user's edits or answers
- write every human-readable field in the SAME LANGUAGE as the claim texts

Theories of value — when the context lists options (O1, O2 ...) and outcomes \
(Y1, Y2 ...):
- a theory is a theory OF one option: set option_key to it, and say whether its \
causal chain predicts that choosing it ACHIEVES or THREATENS the outcomes in \
outcome_keys
- build rival theories. For each option the graph says something about, give \
the strongest case it supports; where it supports both a case for and a case \
against the same option, give both. The case against the option the evidence \
favours most is the one most worth stating
- never invent a theory for an option the graph is silent about: an uncovered \
option is a finding the user needs to see, not a gap to fill
- leave option_key empty, with predicted_effect "unclear", only for a theory \
about a condition that bears on every option alike
Without options in the context, option_key is "", predicted_effect "unclear" and \
outcome_keys empty.

Status vocabulary:
- supported: evidence in the context directly backs the causal chain
- hypothesis: the chain is plausible and consistent but under-evidenced
- contested: meaningful contradicting evidence exists
- insufficient_evidence: the graph cannot currently support a judgement

Return JSON."""


THEORY_GENERATION_SCHEMA = {
    "type": "object",
    "properties": {
        "theories": {
            "type": "array",
            "description": "Distinct decision-relevant theories, most important first.",
            "items": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Specific, decision-oriented title (max ~15 words).",
                    },
                    "summary": {
                        "type": "string",
                        "description": "What may be happening, why, and why it matters "
                        "for the decision. 2-5 sentences.",
                    },
                    "status": {
                        "type": "string",
                        "enum": [
                            "hypothesis",
                            "supported",
                            "contested",
                            "insufficient_evidence",
                        ],
                    },
                    "causal_chain": {
                        "type": "array",
                        "description": "Ordered walk through the graph, alternating "
                        "claim and edge references, e.g. ['C3','E7','C9'].",
                        "items": {"type": "string"},
                    },
                    "supporting_claim_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Claim references (C-refs) the theory rests on.",
                    },
                    "supporting_edge_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Edge references (E-refs) the theory rests on.",
                    },
                    "supporting_evidence_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Evidence references (V-refs) that support it.",
                    },
                    "contradicting_evidence_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Evidence references (V-refs) that undercut it.",
                    },
                    "weak_assumptions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Assumptions that are unverified and, if wrong, "
                        "would change the conclusion.",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "0.0 to 1.0. Calibrated, not aspirational.",
                    },
                    "business_impact": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                    },
                    "recommendation": {
                        "type": "string",
                        "description": "One concrete decision or validation action.",
                    },
                    "option_key": {
                        "type": "string",
                        "description": "The option (O1, O2 ...) this is a theory of, "
                        "or an empty string.",
                    },
                    "predicted_effect": {
                        "type": "string",
                        "enum": ["achieves", "threatens", "unclear"],
                        "description": "What the chain predicts for the outcomes if "
                        "the option is chosen.",
                    },
                    "outcome_keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Outcomes (Y1, Y2 ...) the theory bears on.",
                    },
                    "previous_theory_key": {
                        "type": "string",
                        "description": "Key of the previous theory this continues, or "
                        "an empty string when the theory is new.",
                    },
                    "change_explanation": {
                        "type": "string",
                        "description": "What materially changed versus the previous "
                        "version and why. Empty string for new theories.",
                    },
                },
                "required": [
                    "title",
                    "summary",
                    "status",
                    "causal_chain",
                    "supporting_claim_refs",
                    "supporting_edge_refs",
                    "supporting_evidence_refs",
                    "contradicting_evidence_refs",
                    "weak_assumptions",
                    "confidence",
                    "business_impact",
                    "recommendation",
                    "option_key",
                    "predicted_effect",
                    "outcome_keys",
                    "previous_theory_key",
                    "change_explanation",
                ],
                "additionalProperties": False,
            },
        },
        "insufficient_reason": {
            "type": "string",
            "description": "When few or no theories could be generated, explain what "
            "the graph is missing. Empty string otherwise.",
        },
    },
    "required": ["theories", "insufficient_reason"],
    "additionalProperties": False,
}
