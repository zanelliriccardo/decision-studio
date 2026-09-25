"""Prompts for the decision anchor: drafting it, and scoring claims against it.

The vocabulary comes from the theory-based view of strategy (Felin, Zenger,
Gambardella, Camuffo): a theory of value is a causal map from **attributes** —
the choices the decider controls and the contingencies they depend on — to the
outcome that defines success. ``decision_role`` is that vocabulary applied to a
single claim.
"""

#: Shared by extraction and re-scoring, so the two can never disagree on what a
#: role or a relevance score means.
DECISION_ROLE_GUIDE = """\
**Decision role** — how the claim relates to the decision below:
   - lever: a choice or action the decision owner controls, or a property of one \
of the options (what an option would actually involve).
   - contingency: a condition outside the owner's control that changes how an \
option plays out — a market, a competitor, a regulator, a supplier, a deadline.
   - mechanism: an intermediate effect through which levers and contingencies \
reach the outcomes.
   - outcome: a statement about one of the success criteria themselves.
   - background: context that would not move any outcome under any option.

**Relevance** (0.0 to 1.0) — how much the claim could change the choice:
   - 0.8-1.0: changes whether an outcome is reached under at least one option, \
or discriminates between options.
   - 0.5-0.7: acts on a lever or contingency one step removed from an outcome.
   - 0.2-0.4: connected through a chain you can name, but distant.
   - 0.0-0.1: background; the decision would be the same without it.
   Score the claim's CONSEQUENCE for the decision, not how prominent it is in \
the text. A side remark that could sink one option scores high; a headline fact \
that bears on no option scores low. Never omit a claim because it scores low.

**Bears on** — the keys (O1, O2, Y1 ...) of the options and outcomes the claim \
affects. Empty when it affects none."""

ANCHOR_DRAFT_SYSTEM = """\
You are a decision analyst helping someone state a decision precisely before \
any analysis happens. Turn their one-line objective, read against their \
material, into a structured problem statement.

Produce:
- decision: the choice, restated as one precise sentence. Keep the user's \
meaning; sharpen it, never replace it.
- options: 2 to 4 alternatives genuinely on the table. Include the ones the \
objective names. Add "do nothing / defer" only when it is a real alternative. \
Do not invent exotic options the material gives no reason to consider.
- outcomes: 1 to 3 success criteria — what would make this the right call, \
looking back. Each has a short label and how it would be measured. Prefer \
outcomes the material itself cares about (dates, money, customers, risk).
- deadline: by when the decision must be made, if the material or objective \
says; otherwise an empty string. Never guess a date.
- constraints: hard limits the material states (budget, headcount, contract \
terms, regulation). Empty when none are stated. Never invent one.

This is a draft the user will edit. Be concrete and short: labels of a few \
words, not paragraphs. Write in the same language as the objective."""

ANCHOR_DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string"},
        "options": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"label": {"type": "string"}},
                "required": ["label"],
                "additionalProperties": False,
            },
        },
        "outcomes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "measure": {"type": "string"},
                },
                "required": ["label", "measure"],
                "additionalProperties": False,
            },
        },
        "deadline": {"type": "string"},
        "constraints": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["decision", "options", "outcomes", "deadline", "constraints"],
    "additionalProperties": False,
}

RELEVANCE_SYSTEM = f"""\
You are a decision analyst. For each numbered claim, judge how it bears on the \
decision described below. You are scoring, not filtering: every claim gets a \
score, and a low score is a correct answer for background.

{DECISION_ROLE_GUIDE}

Also give a one-sentence reason naming the option or outcome affected, or \
saying why the claim is background.

Return one entry per claim, using the claim's index."""

ROLE_ENUM = ["lever", "contingency", "mechanism", "outcome", "background"]

RELEVANCE_SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "decision_role": {"type": "string", "enum": ROLE_ENUM},
                    "relevance": {"type": "number", "minimum": 0, "maximum": 1},
                    "bears_on": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                },
                "required": ["index", "decision_role", "relevance", "bears_on", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["scores"],
    "additionalProperties": False,
}

#: Added to each claim of the extraction schema when an anchor exists.
EXTRACTION_ANCHOR_PROPERTIES = {
    "decision_role": {
        "type": "string",
        "enum": ROLE_ENUM,
        "description": "How the claim relates to the decision.",
    },
    "relevance": {
        "type": "number",
        "minimum": 0,
        "maximum": 1,
        "description": "How much the claim could change the choice, 0-1.",
    },
    "relevance_reason": {
        "type": "string",
        "description": "One sentence: which option or outcome it affects, or why "
                       "it is background.",
    },
    "bears_on": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Keys of the options and outcomes it affects.",
    },
}
