# DEAD-CODE-CANDIDATE DC-10 [module]: older copy of DC-09, already prefixed deprecated_; nothing imports it. See docs/DEAD_CODE_REPORT.md
"""DEPRECATED — instrumentation for a pipeline stage. Written, never wired up.

**Nothing imports this.** It was built to give every stage a start line with the
size of the work, a finish line with duration and output, and token attribution
per stage. Attribution ended up handled elsewhere (``llm/usage.py`` intercepts
the calls), and this was left behind looking like live infrastructure.

Renamed rather than deleted because the decision is still open, and it is a real
decision rather than a tidy-up: wiring it into ``orchestrator.run()`` would both
remove the duplication that makes that function 668 lines and give progress
*inside* long stages, which is the thing the pipeline still does not report. The
alternative is to delete it. What should not happen is a third year of it
sitting here unused with an inviting name.

If you wire it up, drop the ``deprecated_`` prefix. If you decide against it,
delete the file — leaving it renamed is the temporary state, not the answer.

Original documentation follows.

---

Instrumentation for a pipeline stage.

Three things were missing and all three have the same shape, so they are solved
in one place rather than three:

* **The log said almost nothing.** A stage logged its result and nothing else,
  so a run that took four minutes in causal inference and forty seconds
  everywhere else looked identical in the log to one that was evenly spread.
  When something hung there was no way to tell where.
* **The UI showed a stage name and a bar.** No indication of how much work the
  stage had to do, how far through it was, or how long it had been running.
* **Token spend was unattributed.** Counting a run's cost is useful; knowing
  that 70% of it went to blind re-scoring is what lets you do something about
  it.

A stage entered through :class:`stage_context` gets all three: a start line with
the size of the work, a finish line with duration and what it produced, and every
model call made inside it recorded against that stage's name.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Callable, Awaitable

from decision_studio.llm import usage as usage_tracking

logger = logging.getLogger(__name__)

#: A stage slower than this without emitting anything looks like a hang. Stages
#: expected to exceed it should call `progress()` as they go.
QUIET_WARNING_SECONDS = 45.0


@asynccontextmanager
async def stage_context(
    stage: str,
    *,
    emit: Callable[[str, str, dict[str, Any] | None], Awaitable[None]] | None = None,
    inputs: dict[str, Any] | None = None,
    progress: float | None = None,
):
    """Run a stage with logging, timing and token attribution.

    Args:
        stage: the stage name, used for both events and usage attribution.
        emit: coroutine taking ``(stage, status, data)``, usually the
            orchestrator's event emitter.
        inputs: the size of the work — ``{"claims": 476, "edges": 535}``. Logged
            and sent to the UI so a progress bar can say *what* it is chewing
            through, not merely that it is chewing.
        progress: overall pipeline progress at the start of this stage.

    Yields a ``StageReporter``. Call ``reporter.progress(...)`` inside long
    loops and ``reporter.result(...)`` before exiting to record what came out.
    """
    started = time.monotonic()
    usage_tracking.set_stage(stage)

    size = ", ".join(f"{v} {k}" for k, v in (inputs or {}).items())
    logger.info("→ %s: started%s", stage, f" ({size})" if size else "")

    if emit is not None:
        await emit(stage, "started", {**(inputs or {}), "progress": progress})

    reporter = StageReporter(stage, emit, started)
    try:
        yield reporter
    except Exception as exc:
        elapsed = time.monotonic() - started
        # Logged here as well as by whoever handles the exception: the stage
        # name and how far it got are context the handler does not have.
        logger.error(
            "✗ %s: failed after %.1fs — %s", stage, elapsed, exc, exc_info=True
        )
        if emit is not None:
            await emit(stage, "error", {"error": str(exc), "elapsed_seconds": elapsed})
        raise
    else:
        elapsed = time.monotonic() - started
        ledger = usage_tracking.current_ledger()
        spend = ledger.stages.get(stage) if ledger else None

        detail = ", ".join(f"{v} {k}" for k, v in reporter.results.items())
        cost = ""
        if spend and spend.calls:
            cost = (
                f" · {spend.calls} call(s), "
                f"{spend.input_tokens + spend.output_tokens:,} tokens"
            )
            if spend.cost_usd:
                cost += f", ${spend.cost_usd:.3f}"

        logger.info(
            "← %s: done in %.1fs%s%s",
            stage, elapsed, f" ({detail})" if detail else "", cost,
        )

        if elapsed > QUIET_WARNING_SECONDS and not reporter.emitted_progress:
            # Not an error, but worth knowing: from the outside this stage was
            # indistinguishable from a hang for most of a minute.
            logger.warning(
                "  %s ran %.0fs without reporting progress — consider calling "
                "reporter.progress() inside its loop", stage, elapsed,
            )

        if emit is not None:
            await emit(stage, "completed", {
                **reporter.results,
                "elapsed_seconds": round(elapsed, 1),
                **({
                    "tokens": spend.input_tokens + spend.output_tokens,
                    "cost_usd": round(spend.cost_usd, 4),
                } if spend and spend.calls else {}),
            })
    finally:
        usage_tracking.set_stage("other")


class StageReporter:
    """Handle for reporting from inside a stage."""

    def __init__(
        self,
        stage: str,
        emit: Callable[[str, str, dict[str, Any] | None], Awaitable[None]] | None,
        started: float,
    ) -> None:
        """Hold what a stage needs to report from inside itself."""
        self.stage = stage
        self._emit = emit
        self._started = started
        self.results: dict[str, Any] = {}
        self.emitted_progress = False
        self._last_logged = 0.0

    async def progress(
        self, done: int, total: int, *, note: str | None = None
    ) -> None:
        """Report position inside a long stage.

        Rate-limited to one log line every two seconds. A stage looping over 500
        edges would otherwise write 500 lines and bury everything else — and the
        log is being made *more* useful here, not merely longer.
        """
        self.emitted_progress = True
        now = time.monotonic()

        if now - self._last_logged >= 2.0 or done >= total:
            self._last_logged = now
            elapsed = now - self._started
            # A rate is more use than a percentage: it tells you whether to wait.
            rate = f", {done / elapsed:.1f}/s" if elapsed > 1 and done else ""
            logger.info(
                "  %s: %d/%d (%.0f%%) after %.0fs%s%s",
                self.stage, done, total, 100 * done / max(total, 1),
                elapsed, rate, f" — {note}" if note else "",
            )

        if self._emit is not None:
            await self._emit(self.stage, "progress", {
                "done": done,
                "total": total,
                "elapsed_seconds": round(now - self._started, 1),
                **({"note": note} if note else {}),
            })

    def result(self, **counts: Any) -> None:
        """Record what the stage produced, for the completion line."""
        self.results.update(counts)
