"""Domain-specific framing questions.

The core catalogue in ``framing.py`` asks what is true of every decision: what is
being decided, by when, how reversible, what would change your mind. Those ten
required questions gate generation and are deliberately identical everywhere, so
answers stay comparable across projects.

But a merger and a reorganisation do not share the questions that actually
matter. Asking only generic questions produces a generic frame, and everything
downstream — theories, adversary, tripwires, discriminators — is bounded by it.

So each domain adds a pack. Two design rules:

* **Domain questions are never required.** The gate stays uniform: a project
  whose owner picks the wrong domain, or none, must still be able to proceed.
  Making them required would turn a helpful classification into an obstacle.
* **The reference-class question is domain-specific and matters most.** The
  outside view is the only empirical anchor a one-off decision has, and the
  right question differs sharply: for M&A it is "of the acquisitions you have
  made, how many hit their synergy case", which is a far better predictor than
  anything in the deal model.

Domains the user cannot find here fall to ``OTHER``, where the LLM proposes a
pack instead — see ``suggest_domain_questions``.
"""

from __future__ import annotations

from decision_studio.reasoning.framing import (
    SECTION_BELIEF,
    SECTION_CRITERIA,
    SECTION_DECISION,
    SECTION_SOURCES,
    FramingQuestion,
)

DOMAIN_GENERIC = "generic"
DOMAIN_MA = "mergers_acquisitions"
DOMAIN_HIRING = "executive_hiring"
DOMAIN_CAPITAL = "capital_structure"
DOMAIN_INNOVATION = "innovation"
DOMAIN_MARKET_ENTRY = "market_entry"
DOMAIN_RESTRUCTURING = "organizational_restructuring"
DOMAIN_OTHER = "other"

DOMAINS: tuple[str, ...] = (
    DOMAIN_GENERIC,
    DOMAIN_MA,
    DOMAIN_HIRING,
    DOMAIN_CAPITAL,
    DOMAIN_INNOVATION,
    DOMAIN_MARKET_ENTRY,
    DOMAIN_RESTRUCTURING,
    DOMAIN_OTHER,
)

#: Human labels, for the picker.
DOMAIN_LABELS: dict[str, str] = {
    DOMAIN_GENERIC: "General strategic decision",
    DOMAIN_MA: "Merger or acquisition",
    DOMAIN_HIRING: "Executive hiring",
    DOMAIN_CAPITAL: "Capital structure or financing",
    DOMAIN_INNOVATION: "Innovation or R&D investment",
    DOMAIN_MARKET_ENTRY: "Market entry",
    DOMAIN_RESTRUCTURING: "Organizational restructuring",
    DOMAIN_OTHER: "Something else",
}


def _q(
    qid: str,
    section: str,
    question: str,
    why: str,
    feeds: str,
    answer_type: str = "free_text",
    options: tuple[str, ...] = (),
    placeholder: str | None = None,
) -> FramingQuestion:
    """Domain questions are optional by construction — the gate stays uniform."""
    return FramingQuestion(
        id=qid,
        section=section,
        question=question,
        why=why,
        answer_type=answer_type,
        feeds=feeds,
        required=False,
        options=options,
        placeholder=placeholder,
    )


DOMAIN_QUESTIONS: dict[str, tuple[FramingQuestion, ...]] = {
    # ── Mergers and acquisitions ────────────────────────────────────────────
    DOMAIN_MA: (
        _q(
            "ma_what_you_buy",
            SECTION_DECISION,
            "What are you actually buying: the business, the team, the customers, "
            "or the technology?",
            "These fail in different ways. Buying a team and losing the founders "
            "is a total loss; buying customers and losing the founders may not be.",
            "What counts as the deal failing, and which risks matter.",
            answer_type="multi_choice",
            options=(
                "The business as it stands",
                "The team",
                "The customer base",
                "The technology or IP",
                "Market position or a competitor removed",
            ),
        ),
        _q(
            "ma_key_person_risk",
            SECTION_CRITERIA,
            "How much of the value depends on specific people staying?",
            "Key-person dependence is the most common way a defensible-looking "
            "deal quietly loses its value after closing.",
            "Weighting of retention risk in theories and tripwires.",
            answer_type="single_choice",
            options=(
                "Most of it — without them there is little left",
                "Substantial but survivable",
                "Little — the value is in assets or contracts",
            ),
        ),
        _q(
            "ma_synergies",
            SECTION_CRITERIA,
            "Which synergies are in the financial model, and which are in the "
            "pitch but not the model?",
            "Synergies that were never modelled are the ones nobody is "
            "accountable for, and they are usually the ones quoted in the room.",
            "Separating evidenced value from asserted value.",
            placeholder="e.g. €4M cost synergy modelled; 'cross-sell potential' not modelled",
        ),
        _q(
            "ma_diligence_surprise",
            SECTION_BELIEF,
            "What did diligence turn up that surprised you?",
            "A surprise is a place your model of the target was wrong. There are "
            "usually more where it came from.",
            "Where the adversary looks first.",
        ),
        _q(
            "ma_reference_class",
            SECTION_BELIEF,
            "Of the acquisitions your organisation has made, how many delivered "
            "the synergies that justified them?",
            "The outside view for M&A, and the single most predictive number "
            "available. It is also reliably worse than the deal model implies.",
            "Base rate against which theory confidence is checked.",
            placeholder="e.g. 3 acquisitions, 1 delivered the case",
        ),
    ),
    # ── Executive hiring ────────────────────────────────────────────────────
    DOMAIN_HIRING: (
        _q(
            "hiring_problem",
            SECTION_DECISION,
            "What problem is this hire meant to solve, and how would you know it "
            "had been solved?",
            "A role defined by its seniority rather than its problem tends to "
            "produce a hire everybody likes and nobody can evaluate.",
            "Success criteria, and what tripwires should watch.",
        ),
        _q(
            "hiring_evidence",
            SECTION_SOURCES,
            "What evidence do you actually have about how this person performs, "
            "as opposed to how they present?",
            "Interviews measure interviewing. References are selected by the "
            "candidate. Naming what you have exposes how thin it usually is.",
            "Truth priors on claims about the candidate.",
            placeholder="e.g. two back-channel references, one work sample, four interviews",
        ),
        _q(
            "hiring_context_transfer",
            SECTION_BELIEF,
            "Their past success happened in what context, and how much of it "
            "carries over here?",
            "Executive performance is unusually context-dependent. The question "
            "is not whether they succeeded but whether the conditions travel.",
            "Weak assumptions in theories about their impact.",
        ),
        _q(
            "hiring_failure_cost",
            SECTION_CRITERIA,
            "If this hire is wrong, how long before you know, and what does it "
            "cost to undo?",
            "Senior mistakes surface slowly and cost more to reverse than the "
            "salary, because of what they change while in post.",
            "How much confidence to demand before recommending.",
        ),
        _q(
            "hiring_reference_class",
            SECTION_BELIEF,
            "Of the senior hires you have made, how many worked out?",
            "The outside view for hiring. Almost always lower than remembered, "
            "because the failures leave and the survivors define the memory.",
            "Base rate against which theory confidence is checked.",
            placeholder="e.g. 5 senior hires in 3 years, 2 still in post and performing",
        ),
    ),
    # ── Capital structure ───────────────────────────────────────────────────
    DOMAIN_CAPITAL: (
        _q(
            "capital_constraint",
            SECTION_DECISION,
            "What is the binding constraint: cash today, dilution, covenants, or "
            "optionality later?",
            "Financing decisions look like arithmetic and are usually about which "
            "constraint you refuse to breach.",
            "What theories are scored against.",
            answer_type="single_choice",
            options=(
                "Cash runway",
                "Dilution",
                "Covenants or control",
                "Keeping future options open",
            ),
        ),
        _q(
            "capital_downside",
            SECTION_CRITERIA,
            "What happens if the plan underperforms by 30%?",
            "Capital structures are chosen on the base case and tested by the "
            "downside. Naming it in advance is cheaper than discovering it.",
            "Scenario comparison and stability analysis.",
        ),
        _q(
            "capital_who_decides",
            SECTION_SOURCES,
            "Who is advising you, and how are they paid?",
            "Advisors on transaction fees, lenders selling debt and investors "
            "buying equity all give sincere advice shaped by their position.",
            "Source-interest adjustment on extracted claims.",
        ),
        _q(
            "capital_reference_class",
            SECTION_BELIEF,
            "In your past raises or financings, how did the outcome compare with "
            "the plan the money was raised against?",
            "The outside view for financing: plans presented to capital providers "
            "are systematically optimistic, including your own.",
            "Base rate against which theory confidence is checked.",
        ),
    ),
    # ── Innovation and R&D ──────────────────────────────────────────────────
    DOMAIN_INNOVATION: (
        _q(
            "innovation_uncertainty",
            SECTION_DECISION,
            "Is the main uncertainty technical (can it be built?) or market "
            "(will anyone want it?)",
            "They need opposite responses. Technical uncertainty resolves with a "
            "prototype; market uncertainty resolves with customers, and a "
            "prototype tells you nothing about it.",
            "What kind of experiment to propose.",
            answer_type="single_choice",
            options=(
                "Technical — can we build it",
                "Market — will anyone want it",
                "Both, roughly equally",
                "Neither — the uncertainty is timing or competition",
            ),
        ),
        _q(
            "innovation_kill_criteria",
            SECTION_CRITERIA,
            "What result would make you stop funding this?",
            "R&D portfolios fail by continuing, not by starting. A kill criterion "
            "agreed before the money is spent is worth more than one argued after.",
            "Tripwires with explicit stop conditions.",
        ),
        _q(
            "innovation_cheapest_test",
            SECTION_BELIEF,
            "What is the cheapest thing that would tell you the most?",
            "The best experiment is the one whose two outcomes point to different "
            "decisions. This question usually finds it faster than a design does.",
            "Field experiment design.",
        ),
        _q(
            "innovation_reference_class",
            SECTION_BELIEF,
            "Of the innovation bets your organisation has funded, how many "
            "reached the market?",
            "The outside view for R&D. Portfolio base rates are far below what "
            "individual project confidence implies, which is why portfolios exist.",
            "Base rate against which theory confidence is checked.",
        ),
    ),
    # ── Market entry ────────────────────────────────────────────────────────
    DOMAIN_MARKET_ENTRY: (
        _q(
            "entry_why_now",
            SECTION_DECISION,
            "Why this market, and why now rather than in a year?",
            "'Why now' separates a strategic move from an opportunistic one. If "
            "the answer is weak, waiting is usually free.",
            "Whether timing belongs in the causal chain.",
        ),
        _q(
            "entry_incumbent_response",
            SECTION_BELIEF,
            "How will the incumbents respond, and how long will it take them?",
            "Entry models routinely treat competitors as static. They are not, "
            "and their response is often the deciding factor.",
            "The adversary's strongest line of attack.",
        ),
        _q(
            "entry_transferable",
            SECTION_CRITERIA,
            "What actually transfers from your current market — brand, "
            "relationships, supply chain, regulatory standing?",
            "Advantages that feel general are frequently local. Naming what "
            "transfers separates the real edge from the assumed one.",
            "Weak assumptions in theories about the advantage.",
            answer_type="multi_choice",
            options=(
                "Brand recognition",
                "Customer relationships",
                "Supply chain or operations",
                "Regulatory standing or licences",
                "Technology or product",
                "Honestly, very little",
            ),
        ),
        _q(
            "entry_exit_cost",
            SECTION_CRITERIA,
            "If this does not work, what does exiting cost?",
            "Entry decisions are evaluated on upside and lived through the exit. "
            "A cheap exit justifies a bolder entry.",
            "Reversibility weighting in recommendations.",
        ),
        _q(
            "entry_reference_class",
            SECTION_BELIEF,
            "Of the markets you have entered before, how many reached the "
            "position you were aiming for?",
            "The outside view for entry. Also worth asking about competitors who "
            "entered this market and left.",
            "Base rate against which theory confidence is checked.",
        ),
    ),
    # ── Organizational restructuring ────────────────────────────────────────
    DOMAIN_RESTRUCTURING: (
        _q(
            "restructure_problem",
            SECTION_DECISION,
            "What behaviour do you want that the current structure prevents?",
            "Restructuring justified by a diagram tends to move boxes. "
            "Restructuring justified by a behaviour has a test.",
            "Success criteria and tripwires.",
        ),
        _q(
            "restructure_who_loses",
            SECTION_SOURCES,
            "Who loses status, scope or headcount, and what will they do about it?",
            "Reorganisations are contested by the people implementing them. "
            "Naming the losers in advance is more useful than discovering them.",
            "Personas for the synthetic experiment, and the adversary.",
        ),
        _q(
            "restructure_disruption",
            SECTION_CRITERIA,
            "How much delivery disruption can you absorb while this settles?",
            "Every restructure costs months of output. The question is whether "
            "the benefit exceeds a cost that is usually underestimated.",
            "Business impact weighting.",
        ),
        _q(
            "restructure_reference_class",
            SECTION_BELIEF,
            "Of the reorganisations you have been through, how many achieved "
            "what they were meant to?",
            "The outside view for restructuring, and generally the most sobering "
            "number in this list.",
            "Base rate against which theory confidence is checked.",
        ),
    ),
}


def questions_for(domain: str | None) -> tuple[FramingQuestion, ...]:
    """The domain pack, or empty for generic, unknown and OTHER.

    ``OTHER`` returns nothing here on purpose: its pack is proposed by the model
    at runtime rather than shipped, since the whole point is that we did not
    anticipate the domain.
    """
    return DOMAIN_QUESTIONS.get(domain or "", ())


def all_questions(domain: str | None) -> tuple[FramingQuestion, ...]:
    """Core questions followed by the domain pack.

    Core first so the required ones are answered before the specialised ones,
    and so the sections read in the same order regardless of domain.
    """
    from decision_studio.reasoning.framing import FRAMING_QUESTIONS

    return FRAMING_QUESTIONS + questions_for(domain)


def is_valid_domain(domain: str | None) -> bool:
    return domain in DOMAINS
