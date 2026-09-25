"""Shared fakes for tests that must not call a model or an embedding API."""

from __future__ import annotations

import hashlib
import os
from typing import Any, Callable

import numpy as np
import pytest

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://decision_studio:decision_studio@localhost:5432/decision_studio_test",
)


class FakeLLM:
    """Answers by system prompt, and records every call.

    ``routes`` maps a system prompt (or a callable predicate on it) to a handler
    ``(user, schema) -> dict``. Anything unrouted returns ``{}``, which every
    stage in the pipeline treats as "nothing found".
    """

    def __init__(self, routes: list[tuple[Any, Callable[[str, dict], dict]]] | None = None):
        self.routes = routes or []
        self.calls: list[dict[str, Any]] = []

    async def complete_json(self, system: str, user: str, schema: dict, **kwargs: Any) -> dict:
        self.calls.append({"system": system, "user": user, "schema": schema, **kwargs})
        for match, handler in self.routes:
            if (callable(match) and match(system)) or match == system:
                result = handler(user, schema)
                if isinstance(result, Exception):
                    raise result
                return result
        return {}

    async def complete(self, system: str, user: str, **kwargs: Any) -> str:
        self.calls.append({"system": system, "user": user, **kwargs})
        return ""

    def calls_to(self, system: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["system"] == system]


class FakeEmbedder:
    """Deterministic unit vectors from a hash of the text.

    ``same`` maps texts to a shared key, so tests can make two claims
    near-identical on purpose.
    """

    def __init__(self, dimensions: int = 1536, same: dict[str, str] | None = None):
        self.dimensions = dimensions
        self.same = same or {}

    def vector(self, text: str) -> list[float]:
        seed = int(hashlib.sha256(self.same.get(text, text).encode()).hexdigest()[:8], 16)
        v = np.random.default_rng(seed).normal(size=self.dimensions)
        return list(v / np.linalg.norm(v))

    async def embed(self, text: str) -> list[float]:
        return self.vector(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.vector(t) for t in texts]


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()
