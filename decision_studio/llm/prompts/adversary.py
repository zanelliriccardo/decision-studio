"""Prompts for adversarial review and tripwire generation.

Both exist because a strategic decision cannot be validated empirically. If the
conclusion cannot be checked against data, the only remaining discipline is
(a) actively trying to destroy it, and (b) committing in advance to what would
prove it wrong.

The adversary never receives the theory's title, summary or recommendation —
only the decision, the causal chain and what the theory claims to move. Given
the persuasive prose it would critique the writing; denied it, it has to attack
the reasoning.
"""

ADVERSARY_SYSTEM = """\
You are arguing that a proposed decision is a mistake.

You will be shown a situation, a decision, and the causal chain someone is \
relying on to justify it. You will NOT be shown their write-up, and you should \
not ask for it. Attack the reasoning, not the prose.

Look specifically for:
- common cause: would some third factor produce this same pattern with no \
causal link between the two things at all? If a plausible one exists, name it.
- single source: does a whole step rest on one document, one person, or one \
unverified assertion? Which step, and which source?
- reversal: what would have to be true for the opposite conclusion to hold, and \
how plausible is that?
- scope: does the evidence support a narrower claim than the one being made?
- timing: does the causal story require things to happen in an order the \
evidence does not establish?
- incentive: does the chain depend on a claim from someone who benefits from \
being believed?

Rules:
- Be specific. "This is uncertain" is not an objection; "this step rests \
entirely on the vendor's own status report, and the vendor is the party that \
would be blamed for a slip" is.
- Rate severity honestly. An objection that would not change the decision even \
if correct is low severity, however clever.
- Do not manufacture objections. If a step is genuinely well supported, say so \
by returning fewer objections rather than padding with weak ones.
- At most 4 objections, strongest first.
- Write in the same language as the causal chain.

Return JSON."""


ADVERSARY_SCHEMA = {
    "type": "object",
    "properties": {
        "objections": {
            "type": "array",
            "description": "Up to 4 objections, strongest first. May be empty.",
            "items": {
                "type": "object",
                "properties": {
                    "objection": {
                        "type": "string",
                        "description": "The specific problem, naming the step or "
                        "source it attacks.",
                    },
                    "kind": {
                        "type": "string",
                        "enum": [
                            "common_cause",
                            "single_source",
                            "reversal",
                            "scope",
                            "timing",
                            "incentive",
                            "other",
                        ],
                    },
                    "severity": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "How much this should reduce confidence in "
                        "the decision. 0-1.",
                    },
                },
                "required": ["objection", "kind", "severity"],
                "additionalProperties": False,
            },
        },
        "strongest_defence": {
            "type": "string",
            "description": "The best response the theory's author could give to "
            "your strongest objection. Empty string if you found none.",
        },
    },
    "required": ["objections", "strongest_defence"],
    "additionalProperties": False,
}


TRIPWIRE_SYSTEM = """\
You are converting a theory into something that can be proved wrong.

A strategic decision cannot be tested by experiment, so the nearest available \
discipline is committing in advance to what observation would change the \
conclusion -- and then actually looking on a stated date.

For each theory, propose observations that:
- are CONCRETE and CHECKABLE by a specific date. "Vendor confirms integration \
date in writing" is checkable. "Vendor seems more engaged" is not.
- would actually move the decision. If you would shrug at both outcomes, it is \
not a tripwire.
- fall inside the decision's time horizon where possible. An observation that \
arrives after the decision is made is a post-mortem, not a tripwire.
- name WHO would observe it, or WHERE it would show up, when that is not obvious.

Prefer observations that would FALSIFY the theory. Confirmation is weaker: many \
things confirm a false theory, few things falsify a true one.

Rules:
- 1 to 3 tripwires per theory. Fewer good ones beat more vague ones.
- Do not propose an observation that has already happened.
- Do not propose something nobody in the organisation could actually check.
- Write in the same language as the theory.

Return JSON."""


TRIPWIRE_SCHEMA = {
    "type": "object",
    "properties": {
        "tripwires": {
            "type": "array",
            "description": "1-3 falsifiable observations for this theory.",
            "items": {
                "type": "object",
                "properties": {
                    "observable": {
                        "type": "string",
                        "description": "The concrete, checkable observation.",
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["falsifies", "confirms"],
                        "description": "Which way this observation cuts.",
                    },
                    "horizon_days": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 730,
                        "description": "Within how many days this should be observable.",
                    },
                },
                "required": ["observable", "direction", "horizon_days"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["tripwires"],
    "additionalProperties": False,
}
