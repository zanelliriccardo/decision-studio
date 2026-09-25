"""The framing questionnaire: what the system must know before it reasons.

Strategic decisions have no data to appeal to, so the quality of the output is
bounded by the quality of the question. A theory generated without knowing what
is being decided, by whom, by when, and what would change the decider's mind is
not a theory — it is a summary of the input documents wearing a recommendation.

These questions are a **fixed catalogue rather than LLM-generated**, for three
reasons: they must exist before any generation has happened, they must be
identical across projects so answers stay comparable, and the required subset
must be knowable in advance in order to gate anything.

Every question earns its place by feeding something concrete downstream — the
``feeds`` field records what. A question that steers nothing should be deleted
rather than asked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Answer types, matching the clarification-question vocabulary so the frontend
#: can reuse the same input controls.
ANSWER_TYPES = (
    "free_text",
    "single_choice",
    "multi_choice",
    "yes_no",
    "number",
    "date",
)


#: Where an answer belongs.
#:
#: ``profile`` questions are about the person and their organisation, not about
#: any particular decision: your role, what you can authorise, which kind of
#: mistake you would rather make. Asking them again for every analysis is a tax
#: on using the tool more than once, and the repeated answers are identical, so
#: they are answered once and copied into each new frame.
#:
#: ``decision`` questions are about *this* decision and cannot be reused.
SCOPE_PROFILE = "profile"
SCOPE_DECISION = "decision"


@dataclass(frozen=True)
class FramingQuestion:
    """One intake question."""

    id: str
    section: str
    question: str
    why: str
    answer_type: str
    feeds: str
    required: bool = False
    options: tuple[str, ...] = field(default_factory=tuple)
    placeholder: str | None = None
    scope: str = SCOPE_DECISION

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "scope": self.scope,
            "section": self.section,
            "question": self.question,
            "why": self.why,
            "answer_type": self.answer_type,
            "required": self.required,
            "options": list(self.options),
            "placeholder": self.placeholder,
        }


SECTION_ROLE = "role"
SECTION_DECISION = "decision"
SECTION_CRITERIA = "criteria"
SECTION_BELIEF = "belief"
SECTION_SOURCES = "sources"


#: The catalogue. Fifteen questions, five sections.
FRAMING_QUESTIONS: tuple[FramingQuestion, ...] = (
    # ── Role and authority ───────────────────────────────────────────────
    FramingQuestion(
        id="role",
        section=SECTION_ROLE,
        question="What is your role in this decision?",
        why="A recommendation to someone who decides is different from a "
            "recommendation to someone who must persuade the decider.",
        answer_type="single_choice",
        options=(
            "I decide",
            "I recommend to whoever decides",
            "I approve or veto",
            "I analyse, someone else decides",
        ),
        feeds="Framing of every recommendation, and who it is addressed to.",
        required=True,
        scope=SCOPE_PROFILE,  # Your role rarely changes between one decision and the next.
    ),
    FramingQuestion(
        id="authority",
        section=SECTION_ROLE,
        question="Can you act on this alone, or must you convince others first?",
        why="If the decision needs to be sold, the binding constraint is often "
            "what can be evidenced to a sceptic, not what is true.",
        answer_type="single_choice",
        options=(
            "I can act alone",
            "I need sign-off from one person",
            "I need agreement from a group",
            "I can only advise",
        ),
        feeds="Whether recommendations optimise for being right or being defensible.",
        required=True,
        scope=SCOPE_PROFILE,  # What you can authorise is a property of your position, not of this decision.
    ),
    FramingQuestion(
        id="audience",
        section=SECTION_ROLE,
        question="Who has to be convinced, and what do they already believe?",
        why="Objections you can anticipate are cheaper than objections you meet "
            "in the room.",
        answer_type="free_text",
        feeds="The adversarial pass, which argues from the sceptic's position.",
        placeholder="e.g. the CFO, who thinks the vendor risk is overstated",
        scope=SCOPE_PROFILE,  # The people who must be convinced are usually the same group each time.
    ),

    # ── The decision itself ──────────────────────────────────────────────
    FramingQuestion(
        id="decision",
        section=SECTION_DECISION,
        question="What exactly is being decided?",
        why="Without this, generated theories describe the situation instead of "
            "bearing on a choice. This is the single most important answer here.",
        answer_type="free_text",
        feeds="The decision objective. Theories are scored on whether they move it.",
        required=True,
        placeholder="e.g. whether to commit publicly to the Q3 delivery date",
    ),
    FramingQuestion(
        id="options",
        section=SECTION_DECISION,
        question="What options are genuinely on the table?",
        why="A decision with one option is not a decision. Naming the real "
            "alternatives is what makes comparison possible.",
        answer_type="free_text",
        feeds="Scenario comparison and the ranking of recommendations.",
        required=True,
        placeholder="e.g. commit to Q3 / commit to Q4 / commit with conditions / delay announcing",
    ),
    FramingQuestion(
        id="deadline",
        section=SECTION_DECISION,
        question="By when must it be decided?",
        why="It sets how much of the missing information can realistically be "
            "gathered before deciding, which changes what is worth asking.",
        answer_type="date",
        feeds="Tripwire horizons, and which clarification questions are worth asking.",
        required=True,
    ),
    FramingQuestion(
        id="reversibility",
        section=SECTION_DECISION,
        question="How reversible is this once done?",
        why="A reversible decision made quickly on thin evidence is usually "
            "right. An irreversible one on the same evidence usually is not.",
        answer_type="single_choice",
        options=(
            "Easily reversed",
            "Reversible at real cost",
            "Effectively irreversible",
        ),
        feeds="How much confidence to demand before recommending action.",
        required=True,
    ),

    # ── Success criteria and constraints ─────────────────────────────────
    FramingQuestion(
        id="success",
        section=SECTION_CRITERIA,
        question="Looking back in a year, how would you know this was the right call?",
        why="Stated in advance, this is a criterion. Stated afterwards, it is a "
            "rationalisation of whatever happened.",
        answer_type="free_text",
        feeds="What theories are evaluated against, and tripwire generation.",
        required=True,
        placeholder="e.g. we shipped within 3 weeks of the date and kept the enterprise contract",
    ),
    FramingQuestion(
        id="constraints",
        section=SECTION_CRITERIA,
        question="What constraints are not negotiable?",
        why="A recommendation that breaches a hard constraint wastes everyone's "
            "time however well reasoned it is.",
        answer_type="free_text",
        feeds="Filtering of recommended actions.",
        placeholder="e.g. no additional headcount, contractual penalty after 30 Sept",
        scope=SCOPE_PROFILE,  # Hard organisational constraints — headcount freezes, spending limits — apply across decisions.
    ),
    FramingQuestion(
        id="risk_appetite",
        section=SECTION_CRITERIA,
        question="Which mistake would you rather make?",
        why="Every decision under uncertainty trades one error against the "
            "other. Choosing in advance beats discovering your preference "
            "afterwards.",
        answer_type="single_choice",
        options=(
            "Act and be wrong",
            "Wait and miss the window",
            "Genuinely no preference",
        ),
        feeds="How cautious recommendations should be.",
        required=True,
        scope=SCOPE_PROFILE,  # Which error you would rather make is a disposition, not a per-decision choice.
    ),

    # ── Existing beliefs ─────────────────────────────────────────────────
    FramingQuestion(
        id="current_belief",
        section=SECTION_BELIEF,
        question="What do you currently believe you should do, and how strongly?",
        why="Stating your prior makes it possible to notice when the analysis "
            "merely agrees with you — which is when it is least informative.",
        answer_type="free_text",
        feeds="Flagging theories that only confirm what you already thought.",
        placeholder="e.g. leaning towards Q4, maybe 70% confident",
    ),
    FramingQuestion(
        id="change_mind",
        section=SECTION_BELIEF,
        question="What would change your mind?",
        why="If nothing would, this is not a decision to analyse. If something "
            "would, it is the most valuable thing to go and look for.",
        answer_type="free_text",
        feeds="Tripwires and the prioritisation of clarification questions.",
        required=True,
        placeholder="e.g. written confirmation from the vendor of an integration date",
    ),
    FramingQuestion(
        id="reference_class",
        section=SECTION_BELIEF,
        question="Have you seen similar decisions before, and how did they turn out?",
        why="The outside view. It is the one place a one-off strategic decision "
            "can borrow a base rate, and it is the strongest known corrective "
            "to plan optimism.",
        answer_type="free_text",
        feeds="Calibration of confidence against how comparable cases actually went.",
        placeholder="e.g. last two integrations both slipped about a quarter",
    ),

    # ── Sources ──────────────────────────────────────────────────────────
    FramingQuestion(
        id="source_types",
        section=SECTION_SOURCES,
        question="What kinds of source have you uploaded?",
        why="Internal testimony and external analysis are weighed differently. "
            "Left unstated, the system treats an unfindable internal fact as an "
            "unsupported one.",
        answer_type="multi_choice",
        options=(
            "Internal reports",
            "Meeting notes",
            "Email or chat threads",
            "Interviews or SME judgement",
            "External analysis",
            "Quantitative data",
            "Contracts or legal documents",
        ),
        feeds="Evidence weighting, and which credibility model applies.",
        required=True,
    ),
    FramingQuestion(
        id="source_interest",
        section=SECTION_SOURCES,
        question="Who wrote the main sources, and does anyone gain from being believed?",
        why="An admission that costs the author something is strong evidence. "
            "An assurance from someone who benefits is weak, however emphatic.",
        answer_type="free_text",
        feeds="Truth priors on extracted claims.",
        placeholder="e.g. the status report is from the vendor's account manager",
    ),
)


QUESTIONS_BY_ID: dict[str, FramingQuestion] = {q.id: q for q in FRAMING_QUESTIONS}

REQUIRED_IDS: tuple[str, ...] = tuple(q.id for q in FRAMING_QUESTIONS if q.required)

#: Questions answered once and reused. See SCOPE_PROFILE.
PROFILE_IDS: tuple[str, ...] = tuple(
    q.id for q in FRAMING_QUESTIONS if q.scope == SCOPE_PROFILE
)

#: Questions that must be answered for each decision separately.
DECISION_IDS: tuple[str, ...] = tuple(
    q.id for q in FRAMING_QUESTIONS if q.scope == SCOPE_DECISION
)


def missing_required(answers: dict[str, Any] | None) -> list[str]:
    """Required question ids that still have no usable answer."""
    given = answers or {}
    missing: list[str] = []
    for question_id in REQUIRED_IDS:
        entry = given.get(question_id)
        value = entry.get("value") if isinstance(entry, dict) else entry
        if value is None:
            missing.append(question_id)
        elif isinstance(value, str) and not value.strip():
            missing.append(question_id)
        elif isinstance(value, (list, tuple)) and not value:
            missing.append(question_id)
    return missing


def is_complete(answers: dict[str, Any] | None) -> bool:
    """True when every required question has been answered."""
    return not missing_required(answers)


def answer_value(answers: dict[str, Any] | None, question_id: str) -> Any:
    """Read one answer's value, or None."""
    entry = (answers or {}).get(question_id)
    if isinstance(entry, dict):
        return entry.get("value")
    return entry


def render_frame(
    answers: dict[str, Any] | None,
    questions: "list[FramingQuestion] | tuple[FramingQuestion, ...] | None" = None,
) -> str:
    """Render the frame for a generation prompt.

    Only answered questions are rendered. An unanswered optional question is
    left out rather than shown as empty, so the model is not invited to invent
    a plausible filling for it.

    Args:
        answers: the stored answers.
        questions: the catalogue to render. Pass the project's effective
            questions (core + domain pack + accepted custom ones) or the
            domain-specific answers never reach the prompt — they would be
            collected and then silently ignored, which is worse than not
            asking. Defaults to the core catalogue.
    """
    if not answers:
        return ""

    lines: list[str] = ["# Decision frame (stated by the user, authoritative)"]
    for question in questions or FRAMING_QUESTIONS:
        value = answer_value(answers, question.id)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(v) for v in value)
        lines.append(f"- {question.question} -> {value}")
    return "\n".join(lines) + "\n"
