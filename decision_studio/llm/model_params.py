"""Per-model parameter compatibility for the OpenAI API.

The chat completions API is no longer uniform across models. Reasoning models
(o1, o3, gpt-5 and successors) reject parameters that older models require:

* ``max_tokens`` is refused in favour of ``max_completion_tokens``
* ``temperature`` may only be its default; any explicit value is an error
* ``logprobs`` is not returned at all

Passing the wrong one is a hard 400, not a warning, so a single unsupported
parameter takes the whole application down for that model. This module decides
what to send.

**Why probe rather than pattern-match on the model name.** A name list goes
stale the day a new model ships, and the failure mode is total: the application
stops working for exactly the model the user just chose. So the name check is
only an initial guess. When a request is rejected for an unsupported parameter,
the error names the parameter, and that fact is recorded and the request
retried without it. The second call succeeds, and every later call for that
model is already correct.

The learned facts live in a process-local cache. They are cheap to rediscover
after a restart — one failed request per model — and caching them anywhere more
permanent would mean a wrong entry outliving the deployment that caused it.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

#: Models known to use the reasoning-style parameter set. Only a starting
#: guess: anything missing here is learned from the first rejection.
_REASONING_PREFIXES = ("o1", "o3", "o4", "gpt-5")

#: model -> set of parameters that model rejected.
_UNSUPPORTED: dict[str, set[str]] = {}


def _looks_like_reasoning_model(model: str) -> bool:
    """Whether the name suggests the reasoning parameter set.

    A guess, and only the starting one — anything missing here is learned
    from the first rejection.
    """
    name = model.lower().strip()
    # Strip any provider prefix such as "openai/" or a deployment path.
    name = name.rsplit("/", 1)[-1]
    return any(name.startswith(prefix) for prefix in _REASONING_PREFIXES)


def initial_unsupported(model: str) -> set[str]:
    """Parameters to leave out before anything has been learned."""
    if _looks_like_reasoning_model(model):
        return {"max_tokens", "temperature", "logprobs", "top_logprobs"}
    return set()


def unsupported_for(model: str) -> set[str]:
    """Everything known to be unsupported for this model."""
    if model not in _UNSUPPORTED:
        _UNSUPPORTED[model] = initial_unsupported(model)
    return _UNSUPPORTED[model]


#: Multiplier applied to the caller's cap for reasoning models.
#:
#: `max_completion_tokens` covers reasoning tokens *and* output tokens, while
#: `max_tokens` covered output alone. Translating one to the other unchanged
#: therefore silently cuts the answer budget: the model can spend the entire
#: allowance thinking and return an empty string, which surfaces as a JSON
#: parse error pointing at character zero and naming nothing useful.
#:
#: Four is generous rather than precise. The cap is a safety limit, not a
#: target, and an unused allowance costs nothing.
REASONING_BUDGET_MULTIPLIER = 4


def build_params(
    model: str,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    logprobs: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    """Assemble the request parameters this model will actually accept.

    ``max_tokens`` is translated to ``max_completion_tokens`` rather than
    dropped: the caller means "cap the output", and a model that refuses the old
    spelling still needs the cap. Dropping it would silently allow a reasoning
    model to spend far more than intended.
    """
    blocked = unsupported_for(model)
    params: dict[str, Any] = dict(extra)

    if max_tokens is not None:
        if "max_tokens" in blocked:
            # Room for the thinking as well as the answer -- see the constant.
            params["max_completion_tokens"] = max_tokens * REASONING_BUDGET_MULTIPLIER
        else:
            params["max_tokens"] = max_tokens

    # Temperature is dropped rather than replaced. A model that refuses it has
    # one sampling behaviour, and there is nothing to substitute.
    if temperature is not None and "temperature" not in blocked:
        params["temperature"] = temperature

    if logprobs and "logprobs" not in blocked:
        params["logprobs"] = True

    return params


#: Matches the API's complaint about a parameter, in the shapes it uses.
_PARAM_PATTERNS = (
    re.compile(r"[Uu]nsupported parameter:? '?\"?([a-z_]+)"),
    re.compile(r"[Uu]nknown parameter:? '?\"?([a-z_]+)"),
    re.compile(r"'?\"?([a-z_]+)'?\"? is not supported"),
    re.compile(r"does not support '?\"?([a-z_]+)"),
    re.compile(r"[Uu]se '?\"?(max_completion_tokens)"),
)

#: Parameters worth learning about. Anything else is a real error and should
#: surface rather than be silently retried away.
_LEARNABLE = {"max_tokens", "temperature", "logprobs", "top_logprobs", "top_p"}


def learn_from_error(model: str, error: Exception) -> str | None:
    """Record a parameter the API rejected, so the retry omits it.

    Returns the parameter name when one was recognised, otherwise None — in
    which case the error is not about parameter support and the caller should
    let it propagate rather than retrying blindly.
    """
    message = str(error)

    # "Use max_completion_tokens instead" is a complaint about max_tokens.
    if "max_completion_tokens" in message and "max_tokens" in message:
        _record(model, "max_tokens")
        return "max_tokens"

    for pattern in _PARAM_PATTERNS:
        match = pattern.search(message)
        if not match:
            continue
        name = match.group(1)
        if name == "max_completion_tokens":
            name = "max_tokens"
        if name in _LEARNABLE:
            _record(model, name)
            return name

    # Temperature rejections are often phrased as a value error rather than an
    # unsupported parameter, e.g. "only the default (1) is supported".
    if "temperature" in message and (
        "default" in message or "only" in message or "unsupported_value" in message
    ):
        _record(model, "temperature")
        return "temperature"

    return None


def _record(model: str, param: str) -> None:
    """Note that a model refuses a parameter, so later calls omit it."""
    known = unsupported_for(model)
    if param not in known:
        known.add(param)
        logger.info(
            "Model %s does not accept '%s'; omitting it from now on", model, param
        )


# DEAD-CODE-CANDIDATE DC-18: no callers (probably a test helper whose tests are not in the repo). See docs/DEAD_CODE_REPORT.md
def reset_cache() -> None:
    """Forget what has been learned. For tests."""
    _UNSUPPORTED.clear()
