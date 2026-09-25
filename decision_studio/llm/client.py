"""Abstract LLM client with OpenAI and Anthropic implementations."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

import anthropic
import openai
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from decision_studio.config import settings
from decision_studio.exceptions import LLMError
from decision_studio.llm import model_params
from decision_studio.llm.usage import record_usage

logger = logging.getLogger(__name__)


class LLMClient(ABC):
    """Abstract base class for LLM interactions."""

    async def stream_complete(
        self, system: str, user: str, **kwargs: Any
    ):
        """Stream a text completion token by token.

        Default implementation falls back to non-streaming complete().
        Subclasses can override for true streaming.

        Yields:
            str: Individual text chunks as they arrive.
        """
        result = await self.complete(system, user, **kwargs)
        yield result

    @abstractmethod
    async def complete(self, system: str, user: str, **kwargs: Any) -> str:
        """Generate a text completion given system and user prompts.

        Args:
            system: The system prompt providing instructions and context.
            user: The user message to respond to.
            **kwargs: Additional provider-specific parameters.

        Returns:
            The generated text response.
        """
        ...

    @abstractmethod
    async def complete_json(
        self, system: str, user: str, schema: dict, **kwargs: Any
    ) -> dict:
        """Generate a structured JSON response conforming to the given schema.

        Args:
            system: The system prompt providing instructions and context.
            user: The user message to respond to.
            schema: A JSON Schema dict describing the expected output structure.
            **kwargs: Additional provider-specific parameters.

        Returns:
            A parsed dict matching the provided schema. If logprobs are
            available, a ``_logprob_confidence`` key (float, 0-1) is
            added to the dict.
        """
        ...


class OpenAIClient(LLMClient):
    """LLM client backed by the OpenAI Chat Completions API."""

    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None) -> None:
        """Configure the provider client from settings, with optional overrides."""
        kwargs: dict[str, Any] = {"api_key": api_key or settings.openai_api_key}
        url = base_url or settings.openai_base_url
        if url:
            kwargs["base_url"] = url
        self._client = openai.AsyncOpenAI(**kwargs)
        self._model = model or settings.llm_model



    async def _create(self, **params: Any):
        """Call the API, and retry once without a parameter the model refused.

        Reasoning models reject `max_tokens`, `temperature` and `logprobs` with
        a hard 400 rather than ignoring them. Rather than maintaining a list of
        model names — which goes stale the day a new model ships, and fails
        totally when it does — the rejection itself is the source of truth: the
        error names the parameter, it is recorded, and the call is retried
        without it. Every later call for that model is already correct.
        """
        model = params.get("model", self._model)
        try:
            response = await self._client.chat.completions.create(**params)
            # Recorded here rather than at each call site: this is the single
            # point every OpenAI request passes through, so a stage added later
            # is counted without its author knowing this file exists.
            record_usage(model, getattr(response, "usage", None))
            return response
        except openai.APIError as exc:
            learned = model_params.learn_from_error(model, exc)
            if learned is None:
                # Not about parameter support: a real error, so let it surface.
                raise
            retry = dict(params)
            if learned == "max_tokens" and "max_tokens" in retry:
                # The cap is still wanted; only its spelling was wrong.
                retry["max_completion_tokens"] = retry.pop("max_tokens")
            else:
                retry.pop(learned, None)
                if learned == "logprobs":
                    retry.pop("top_logprobs", None)
            logger.info("Retrying without '%s' for model %s", learned, model)
            response = await self._client.chat.completions.create(**retry)
            record_usage(model, getattr(response, "usage", None))
            return response

    async def stream_complete(self, system: str, user: str, **kwargs: Any):
        """Stream completion tokens from OpenAI API."""
        try:
            stream = await self._create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                stream=True,
                **model_params.build_params(
                    self._model,
                    temperature=kwargs.get("temperature", 0.3),
                    max_tokens=kwargs.get("max_tokens", 4096),
                ),
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield delta
        except openai.APIError as exc:
            raise LLMError(f"OpenAI streaming error: {exc}") from exc

    @retry(
        retry=retry_if_exception_type(
            (openai.APIConnectionError, openai.RateLimitError, openai.APITimeoutError)
        ),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def complete(self, system: str, user: str, **kwargs: Any) -> str:
        """One completion, returned as text."""
        try:
            response = await self._create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                **model_params.build_params(
                    self._model,
                    temperature=kwargs.get("temperature", 0.3),
                    max_tokens=kwargs.get("max_tokens", 4096),
                ),
            )
            content = response.choices[0].message.content
            if content is None:
                raise LLMError("OpenAI returned empty response content")
            return content
        except (
            openai.APIConnectionError,
            openai.RateLimitError,
            openai.APITimeoutError,
        ):
            raise
        except openai.APIError as exc:
            raise LLMError(f"OpenAI API error: {exc}") from exc

    @retry(
        retry=retry_if_exception_type(
            (openai.APIConnectionError, openai.RateLimitError, openai.APITimeoutError)
        ),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def complete_json(
        self, system: str, user: str, schema: dict, **kwargs: Any
    ) -> dict:
        """One completion, validated against a JSON schema.

        Retried once without any parameter the model rejects; see
        `llm/model_params.py` for why the rejection rather than a name list is
        the source of truth.
        """
        try:
            response = await self._create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "response",
                        "schema": schema,
                        "strict": True,
                    },
                },
                **model_params.build_params(
                    self._model,
                    temperature=kwargs.get("temperature", 0.2),
                    max_tokens=kwargs.get("max_tokens", 4096),
                    logprobs=True,
                ),
            )
            choice = response.choices[0]
            content = choice.message.content

            # Empty string, not just None: that is what a reasoning model
            # returns when its whole allowance went on thinking. Falling
            # through to json.loads("") produced "Expecting value: line 1
            # column 1", which names neither the model nor the reason.
            if not content or not content.strip():
                reason = getattr(choice, "finish_reason", None)
                if reason == "length":
                    raise LLMError(
                        f"{self._model} used its entire token allowance and "
                        f"returned nothing. For reasoning models the allowance "
                        f"covers thinking as well as output — raise max_tokens, "
                        f"or use a model that reasons less for this step."
                    )
                if reason == "content_filter":
                    raise LLMError(
                        f"{self._model} declined to answer (content filter). "
                        f"This usually means something in the source documents "
                        f"tripped a safety classifier."
                    )
                raise LLMError(
                    f"{self._model} returned an empty response"
                    + (f" (finish_reason: {reason})" if reason else "")
                )
            result = json.loads(content)

            # Confidence from token logprobs, when the model returns them.
            # Reasoning models do not, so this is absent rather than zero:
            # "not measured" must stay distinguishable from "measured as low".
            logprob_content = getattr(response.choices[0], "logprobs", None)
            if logprob_content and logprob_content.content:
                import math
                token_logprobs = [
                    t.logprob for t in logprob_content.content
                    if t.logprob is not None
                ]
                if token_logprobs:
                    # Geometric mean of token probabilities
                    avg_logprob = sum(token_logprobs) / len(token_logprobs)
                    result["_logprob_confidence"] = round(math.exp(avg_logprob), 4)

            return result
        except json.JSONDecodeError as exc:
            raise LLMError(f"Failed to parse OpenAI JSON response: {exc}") from exc
        except (
            openai.APIConnectionError,
            openai.RateLimitError,
            openai.APITimeoutError,
        ):
            raise
        except openai.APIError as exc:
            raise LLMError(f"OpenAI API error: {exc}") from exc


class AnthropicClient(LLMClient):
    """LLM client backed by the Anthropic Messages API."""

    def __init__(
        self, api_key: str | None = None, model: str | None = None
    ) -> None:
        """Configure the provider client from settings, with optional overrides."""
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key or settings.anthropic_api_key
        )
        self._model = model or settings.llm_model

    @retry(
        retry=retry_if_exception_type(
            (
                anthropic.APIConnectionError,
                anthropic.RateLimitError,
                anthropic.APITimeoutError,
            )
        ),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def complete(self, system: str, user: str, **kwargs: Any) -> str:
        """One completion, returned as text."""
        try:
            response = await self._client.messages.create(
                model=self._model,
                system=system,
                messages=[{"role": "user", "content": user}],
                temperature=kwargs.get("temperature", 0.3),
                max_tokens=kwargs.get("max_tokens", 4096),
            )
            record_usage(self._model, getattr(response, "usage", None))
            text_blocks = [
                block.text for block in response.content if block.type == "text"
            ]
            if not text_blocks:
                raise LLMError("Anthropic returned no text content")
            return text_blocks[0]
        except (
            anthropic.APIConnectionError,
            anthropic.RateLimitError,
            anthropic.APITimeoutError,
        ):
            raise
        except anthropic.APIError as exc:
            raise LLMError(f"Anthropic API error: {exc}") from exc

    @retry(
        retry=retry_if_exception_type(
            (
                anthropic.APIConnectionError,
                anthropic.RateLimitError,
                anthropic.APITimeoutError,
            )
        ),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def complete_json(
        self, system: str, user: str, schema: dict, **kwargs: Any
    ) -> dict:
        """Use the prefill technique: start the assistant turn with '{' to force JSON."""
        try:
            response = await self._client.messages.create(
                model=self._model,
                system=system,
                messages=[
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": "{"},
                ],
                temperature=kwargs.get("temperature", 0.2),
                max_tokens=kwargs.get("max_tokens", 4096),
            )
            record_usage(self._model, getattr(response, "usage", None))
            text_blocks = [
                block.text for block in response.content if block.type == "text"
            ]
            if not text_blocks:
                raise LLMError("Anthropic returned no text content")
            # Reconstruct the full JSON (we prefilled with '{')
            raw_json = "{" + text_blocks[0]
            return json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise LLMError(
                f"Failed to parse Anthropic JSON response: {exc}"
            ) from exc
        except (
            anthropic.APIConnectionError,
            anthropic.RateLimitError,
            anthropic.APITimeoutError,
        ):
            raise
        except anthropic.APIError as exc:
            raise LLMError(f"Anthropic API error: {exc}") from exc


def get_llm_client(*, enable_cache: bool = True) -> LLMClient:
    """Factory function that returns the appropriate LLM client based on settings.

    Args:
        enable_cache: If True (default), wraps the client with a semantic
            cache that avoids redundant LLM calls for similar prompts.

    Returns:
        An LLMClient instance configured according to ``settings.llm_provider``.

    Raises:
        LLMError: If the configured provider is not supported.
    """
    provider = settings.llm_provider.lower()
    if provider == "openai":
        inner: LLMClient = OpenAIClient()
    elif provider == "anthropic":
        inner = AnthropicClient()
    else:
        raise LLMError(f"Unsupported LLM provider: {provider}")

    if enable_cache:
        from decision_studio.llm.cache import CachedLLMClient, SemanticCache
        from decision_studio.llm.embeddings import EmbeddingService

        embed_svc = EmbeddingService()
        cache = SemanticCache(embed_fn=embed_svc.embed)
        return CachedLLMClient(inner=inner, cache=cache)

    return inner
