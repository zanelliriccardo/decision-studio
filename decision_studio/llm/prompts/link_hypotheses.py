"""Prompt for turning a theory's weakest causal links into falsifiable hypotheses."""

LINK_HYPOTHESIS_SYSTEM = """\
You are helping a decision-maker test a theory before committing to it. You are \
given the decision, the theory, and the causal links in its chain that are most \
worth testing — ranked by how much the outcome depends on them and how little is \
known about them.

For each numbered link, write:
- statement: the link as a falsifiable hypothesis, one sentence, specific \
enough that someone could disagree with it ("Losing three of eight engineers \
delays integration testing by more than four weeks", not "staffing affects \
delivery").
- refuted_if: the observation that would show the hypothesis is wrong, with a \
threshold where one makes sense. It must be something that could actually be \
seen, not a feeling or a trend.
- cheapest_test: the quickest, cheapest way to get that observation before the \
decision is due — a question to one person, a number to look up, a small trial. \
If nothing can be observed in time, say so plainly.

Do not restate the link; sharpen it. Do not invent facts beyond the link's own \
claims and mechanism. Return one entry per link, using its index."""

LINK_HYPOTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "hypotheses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "statement": {"type": "string"},
                    "refuted_if": {"type": "string"},
                    "cheapest_test": {"type": "string"},
                },
                "required": ["index", "statement", "refuted_if", "cheapest_test"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["hypotheses"],
    "additionalProperties": False,
}
