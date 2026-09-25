"""Counting the tokens an analysis spends.

A run makes hundreds of model calls across nine pipeline stages plus theory
generation, the adversary, debates and the recommendation. Until now the only
signal of what one cost was the provider's monthly bill, by which point it is
too late to know *which* analysis was expensive, let alone which stage inside
it.

The design is deliberately narrow:

* **A context variable, not a parameter.** Threading a counter through nine
  stages, four reasoning services and two client implementations would touch
  every signature in the call graph and be forgotten by the next person adding
  a stage. A ``ContextVar`` set once at the top of a run is picked up by every
  call underneath it, including ones written later by someone who has not read
  this file.
* **Never raises.** Accounting that can fail a run is worse than no accounting.
  Every entry point swallows its own errors: a missing ``usage`` field or an
  unknown model produces a gap in the numbers, not a failed analysis.
* **Costs are advisory.** The per-token prices below are hard-coded and go stale
  the moment a provider changes them. They exist to make a run's cost
  *comparable* to another run's, not to reconcile with an invoice — and the API
  reports the price table's date so nobody mistakes one for the other.

Token counts, by contrast, come from the provider's own ``usage`` field and are
exact.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: When the prices below were last checked. Reported alongside every cost so a
#: stale table is visible rather than silently wrong.
PRICE_TABLE_DATE = "2026-08-01"

#: USD per 1M tokens, (input, output). Prefix match, longest first, so
#: "gpt-4o-2024-11-20" resolves through "gpt-4o".
_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "o1-mini": (1.10, 4.40),
    "o1": (15.00, 60.00),
    "o3-mini": (1.10, 4.40),
    "o3": (2.00, 8.00),
    "gpt-5": (1.25, 10.00),
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-sonnet-4": (3.00, 15.00),
    "claude-opus-4": (15.00, 75.00),
    "text-embedding-3-small": (0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.0),
}


def price_for(model: str) -> tuple[float, float] | None:
    """USD per 1M (input, output) tokens, or None for an unrecognised model.

    None rather than a guess: a made-up price is worse than a visible gap,
    because it looks like a measurement.
    """
    name = model.lower().strip().rsplit("/", 1)[-1]
    for prefix in sorted(_PRICES, key=len, reverse=True):
        if name.startswith(prefix):
            return _PRICES[prefix]
    return None


@dataclass
class StageUsage:
    """What one pipeline stage spent."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    #: Reasoning models bill these as output; kept separate because a stage
    #: whose cost is mostly invisible thinking is worth spotting.
    reasoning_tokens: int = 0
    cost_usd: float = 0.0
    #: Models seen in this stage, so a stage that silently fell back to a
    #: cheaper or more expensive model is visible.
    models: set[str] = field(default_factory=set)

    def as_dict(self) -> dict[str, Any]:
        """This stage's spend, for the API and the log."""
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
            "cost_usd": round(self.cost_usd, 4),
            "models": sorted(self.models),
        }


class UsageLedger:
    """Everything one analysis spent, broken down by stage."""

    def __init__(self, project_id: str | None = None) -> None:
        """Start an empty ledger for one analysis."""
        self.project_id = project_id
        self.stages: dict[str, StageUsage] = {}
        #: Calls whose model has no price entry. Counted so an unpriced model
        #: shows up as a known gap rather than as a suspiciously cheap run.
        self.unpriced_calls = 0

    def record(
        self,
        *,
        stage: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        reasoning_tokens: int = 0,
    ) -> None:
        """Add one call's usage to a stage.

        A model with no price entry contributes its tokens and increments
        ``unpriced_calls`` rather than a cost — a gap made visible, so an
        unrecognised model does not read as a suspiciously cheap run.
        """
        entry = self.stages.setdefault(stage, StageUsage())
        entry.calls += 1
        entry.input_tokens += input_tokens
        entry.output_tokens += output_tokens
        entry.reasoning_tokens += reasoning_tokens
        entry.models.add(model)

        prices = price_for(model)
        if prices is None:
            self.unpriced_calls += 1
            return
        input_price, output_price = prices
        entry.cost_usd += (
            input_tokens * input_price + output_tokens * output_price
        ) / 1_000_000

    @property
    def total_input(self) -> int:
        """Input tokens across every stage."""
        return sum(s.input_tokens for s in self.stages.values())

    @property
    def total_output(self) -> int:
        """Output tokens across every stage."""
        return sum(s.output_tokens for s in self.stages.values())

    @property
    def total_cost(self) -> float:
        """Estimated USD across every stage. Advisory — see the module docstring."""
        return sum(s.cost_usd for s in self.stages.values())

    @property
    def total_calls(self) -> int:
        """Model calls made during this run."""
        return sum(s.calls for s in self.stages.values())

    def as_dict(self) -> dict[str, Any]:
        """The whole run's spend, stages ordered most expensive first.

        That ordering is the point: the question being asked is always "what
        cost the money", never "what ran alphabetically first".
        """
        return {
            "project_id": self.project_id,
            "calls": self.total_calls,
            "input_tokens": self.total_input,
            "output_tokens": self.total_output,
            "total_tokens": self.total_input + self.total_output,
            "cost_usd": round(self.total_cost, 4),
            "unpriced_calls": self.unpriced_calls,
            "price_table_date": PRICE_TABLE_DATE,
            # Most expensive first: the question being asked is always "what
            # cost the money", never "what ran alphabetically first".
            "by_stage": {
                name: usage.as_dict()
                for name, usage in sorted(
                    self.stages.items(), key=lambda kv: -kv[1].cost_usd
                )
            },
        }

    def summary_line(self) -> str:
        """One line for the log at the end of a run."""
        cost = f"${self.total_cost:.2f}" if self.total_cost else "unpriced"
        return (
            f"{self.total_calls} model call(s) · "
            f"{self.total_input:,} in / {self.total_output:,} out tokens · {cost}"
        )


#: The ledger for the analysis currently running on this task, if any.
_ledger: ContextVar[UsageLedger | None] = ContextVar("usage_ledger", default=None)

#: The pipeline stage currently executing. Calls made outside any stage are
#: recorded under "other" rather than dropped — an unattributed cost is still a
#: cost, and losing it would make the totals disagree with the bill.
_stage: ContextVar[str] = ContextVar("usage_stage", default="other")


def start_ledger(project_id: str | None = None) -> UsageLedger:
    """Begin accounting for a run. Returns the ledger for later reading."""
    ledger = UsageLedger(project_id)
    _ledger.set(ledger)
    return ledger


    """The ledger for the analysis running on this task, or None outside one."""
    return _ledger.get()


    """Attribute subsequent calls to a pipeline stage.

    Set by the orchestrator as it moves between stages. Calls made outside any
    stage land under ``other`` rather than being dropped: an unattributed cost
    is still a cost, and losing it would make the totals disagree with the bill.
    """
    _stage.set(stage)


def record_usage(model: str, usage: Any) -> None:
    """Record one call's usage, from a provider response object.

    Accepts whatever the SDK returned and reads defensively: providers add and
    rename usage fields between versions, and a missing one must cost a number,
    not a run.
    """
    ledger = _ledger.get()
    if ledger is None or usage is None:
        return

    try:
        # OpenAI: prompt_tokens / completion_tokens.
        # Anthropic: input_tokens / output_tokens.
        input_tokens = int(
            getattr(usage, "prompt_tokens", None)
            or getattr(usage, "input_tokens", None)
            or 0
        )
        output_tokens = int(
            getattr(usage, "completion_tokens", None)
            or getattr(usage, "output_tokens", None)
            or 0
        )
        details = getattr(usage, "completion_tokens_details", None)
        reasoning_tokens = int(getattr(details, "reasoning_tokens", 0) or 0)

        ledger.record(
            stage=_stage.get(),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
        )
    except Exception as exc:  # pragma: no cover - provider dependent
        logger.debug("Could not record usage for %s: %s", model, exc)
