"""Prompts for synthetic and field experiments.

Three narrow tasks. The framing of the first two is deliberately restrictive:
each persona is asked what a person in that role would *say and push back on*,
never asked to adjudicate whether the theory is true. A language model has no
access to the world, and inviting it to rule on truth would produce something
that looks like validation and is not.
"""

PERSONA_SYSTEM = """\
You are casting the room a decision has to survive.

Given a decision and what is known about who must be convinced, produce the \
stakeholders whose reaction actually matters.

Rules:
- Use the people the user has already named. If they said the CFO thinks the \
vendor risk is overstated, that is a persona and that is their prior position. \
Do not replace named stakeholders with generic archetypes.
- Add roles only where an obvious constituency is missing -- the person who \
would have to execute it, the one whose budget it comes from, the one who \
carries the risk if it fails.
- Give each one a real STAKE: what they gain or lose whichever way this goes. A \
persona with no stake produces bland agreement and is worse than useless.
- Include at least one persona who is likely to be against, unless the frame \
gives no reason to expect opposition. A room of supporters tests nothing.
- 3 to 5 personas. Fewer, sharper beats more, vaguer.
- These are ROLES, not real individuals. Name them by function.

Return JSON."""


PERSONA_SCHEMA = {
    "type": "object",
    "properties": {
        "personas": {
            "type": "array",
            "description": "3-5 stakeholders whose reaction matters.",
            "items": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Role label, e.g. 'CFO' or 'Delivery lead'.",
                    },
                    "role": {
                        "type": "string",
                        "description": "What they do and why they are in the room.",
                    },
                    "stake": {
                        "type": "string",
                        "description": "What they gain or lose either way.",
                    },
                    "prior_position": {
                        "type": "string",
                        "description": "What they are believed to think already. "
                        "Empty string if unknown.",
                    },
                    "from_user_frame": {
                        "type": "boolean",
                        "description": "True if the user named this stakeholder, "
                        "false if you added them.",
                    },
                },
                "required": ["name", "role", "stake", "prior_position", "from_user_frame"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["personas"],
    "additionalProperties": False,
}


REACTION_SYSTEM = """\
You are simulating how one specific stakeholder would react to a proposal.

You are NOT judging whether the proposal is correct. You have no access to the \
facts of this business. You are answering a narrower question: what would this \
person, with this role and this stake, say when this is put in front of them?

Rules:
- Argue from their interests and their position, not from what is objectively \
true. A CFO whose budget this consumes will find cost objections whether or not \
the reasoning is sound. That is the point.
- Give the single objection they would actually raise in the room -- the one \
that would derail the meeting, not the most intellectually interesting one.
- Say what would satisfy them. "Nothing would" is a legitimate answer for a \
genuinely opposed stakeholder.
- Keep the reaction to what this person would plausibly say out loud. Two or \
three sentences.
- Do not be agreeable to be helpful. A room that nods along has tested nothing, \
and the user is paying for the objections, not the applause.

Return JSON."""


REACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["supports", "opposes", "neutral"],
            "description": "Where this stakeholder would land.",
        },
        "reaction": {
            "type": "string",
            "description": "What they would say, in two or three sentences.",
        },
        "key_objection": {
            "type": "string",
            "description": "The one thing they would push back on. Empty string "
            "if they genuinely have none.",
        },
        "would_need": {
            "type": "string",
            "description": "What would change their mind. May be 'nothing'.",
        },
    },
    "required": ["verdict", "reaction", "key_objection", "would_need"],
    "additionalProperties": False,
}


FIELD_EXPERIMENT_SYSTEM = """\
You are designing a real test that could actually be run.

A simulated stakeholder tells you what people will say. Only a real observation \
tells you whether the theory is true. Your job is the second one: propose \
something the user could genuinely do, soon, that would produce evidence.

Rules:
- It must be RUNNABLE by this organisation inside the decision's time horizon. \
"Run a randomised trial across the customer base" is not a design if the \
decision is due in three weeks.
- Prefer cheap tests that discriminate. The best design is the one where the two \
possible outcomes point to different decisions.
- State exactly what is measured, and what result would count as which answer. \
A test whose outcome you could interpret either way is not a test.
- Give an honest cost and duration. If the only real test is expensive and slow, \
say so rather than inventing a cheap proxy that measures something else.
- Name the confound most likely to spoil it.
- If no meaningful field test exists inside the horizon, say that plainly in \
`not_feasible_reason` and return an empty design. That is a genuine and useful \
finding: it means the decision must be made on judgement, and the user should \
know it.

Return JSON."""


FIELD_EXPERIMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "hypothesis": {
            "type": "string",
            "description": "The specific falsifiable statement under test.",
        },
        "design": {
            "type": "string",
            "description": "What is done, to whom, and over what period. Empty "
            "string if not feasible.",
        },
        "measure": {
            "type": "string",
            "description": "What is measured, and which result means which answer.",
        },
        "cost_estimate": {
            "type": "string",
            "description": "Honest rough cost, in effort or money.",
        },
        "duration_days": {
            "type": "integer",
            "minimum": 0,
            "maximum": 730,
            "description": "How long before it yields an answer. 0 if not feasible.",
        },
        "main_confound": {
            "type": "string",
            "description": "The thing most likely to spoil the result.",
        },
        "not_feasible_reason": {
            "type": "string",
            "description": "Why no meaningful test exists inside the horizon. "
            "Empty string when a design is given.",
        },
    },
    "required": [
        "hypothesis", "design", "measure", "cost_estimate",
        "duration_days", "main_confound", "not_feasible_reason",
    ],
    "additionalProperties": False,
}
