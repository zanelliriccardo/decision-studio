"""Stage 1: Claim Decomposition.

Extracts atomic claims from input text, deduplicates by embedding similarity,
and returns structured claim data with embeddings.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from decision_studio.exceptions import PipelineError
from decision_studio.llm.client import LLMClient
from decision_studio.llm.embeddings import EmbeddingService
from decision_studio.llm.prompts import language_instruction
from decision_studio.llm.prompts.claim_extraction import (
    claim_extraction_schema,
    claim_extraction_system,
)
from decision_studio.reasoning.decision_anchor import (
    anchor_keys,
    clean_claim_scores,
    render_anchor,
)

logger = logging.getLogger(__name__)

# Chunking parameters
_MAX_CHUNK_LENGTH = 8000
_OVERLAP_LENGTH = 1000

# Claims with embedding cosine similarity above this threshold are duplicates
_DEDUP_SIMILARITY_THRESHOLD = 0.95


def _chunk_text(text: str) -> list[str]:
    """Split text into overlapping chunks when it exceeds the max length.

    Uses a sliding window approach with 1000-character overlap to preserve
    context across chunk boundaries.

    Args:
        text: The full input text.

    Returns:
        A list of text chunks. If the text is short enough, returns a
        single-element list.
    """
    if len(text) <= _MAX_CHUNK_LENGTH:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + _MAX_CHUNK_LENGTH
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - _OVERLAP_LENGTH
    return chunks


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


#: Claims about the document rather than about the world it describes.
#: Dropped before anything downstream sees them.
METADATA_TYPE = "DOCUMENT_METADATA"


def _drop_document_metadata(
    claims: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Remove claims about the paperwork.

    "Alberto Invernizzi approved REX-2024-000492 on 11 July 2024" is true,
    atomic, verifiable and correctly extracted — and it cannot participate in a
    causal chain about the subject matter, because a signature date does not
    cause a schedule to slip. On a set of technical documents these run to a
    substantial fraction of everything extracted: title blocks, revision notes,
    attachment lists, distribution tables.

    Dropped here rather than filtered later, because everything downstream costs
    real money to run over them: an embedding call each, a place in every
    similarity comparison, and a candidate slot in causal inference.

    Every dropped claim is logged. A filter that removes a fifth of the input
    silently is a filter nobody can check, and this one is a judgement made by a
    language model about what counts as paperwork — which is exactly the sort of
    judgement that should leave a trail.
    """
    kept, dropped = [], []
    for claim in claims:
        (dropped if claim.get("type") == METADATA_TYPE else kept).append(claim)


    if dropped:
        logger.info(
            "Dropped %d document-metadata claim(s) of %d extracted "
            "(about the paperwork, not the subject matter):",
            len(dropped), len(claims),
        )
        for claim in dropped:
            logger.info("    · %s", claim.get("text", "")[:160])

    return kept


class ClaimExtractor:
    """Extracts atomic claims from text using an LLM.

    Claims are deduplicated across chunks via embedding cosine similarity,
    and each claim is returned with its embedding vector.
    """

    def __init__(self, llm: LLMClient, embedder: EmbeddingService) -> None:
        #: Document-metadata claims removed by the last extract() call.
        """Hold the clients extraction needs, and reset the metadata counter."""
        self.metadata_dropped = 0
        self._llm = llm
        self._embedder = embedder

    async def extract(
        self,
        text: str,
        extra_context: str | None = None,
        anchor: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Extract atomic claims from the given text.

        Pipeline:
        1. Chunk long text into overlapping windows.
        2. For each chunk, call the LLM to extract structured claims.
        3. Merge results across chunks and assign order indices.
        4. Return claims WITHOUT embeddings (for fast initial display).

        Embeddings are added later via ``embed_claims()``.

        Args:
            text: The input text to decompose into claims.
            extra_context: The intake answers, prepended to every chunk's
                prompt. Repeated per chunk rather than sent once, because each
                chunk is an independent call and a disambiguation that only
                reached the first would leave the rest split differently.
            anchor: The decision anchor, when the project has one. Each claim
                is then also scored for its role, relevance and the options and
                outcomes it bears on. Scored, never filtered: see
                ``reasoning/decision_anchor.py``.

        Returns:
            A tuple of (claims, has_temporal_relevance).

        Raises:
            PipelineError: If claim extraction fails.
        """
        if not text or not text.strip():
            raise PipelineError("Cannot extract claims from empty text")

        chunks = _chunk_text(text)
        logger.info("Extracting claims from %d chunk(s)", len(chunks))

        anchored = bool(anchor)
        keys = anchor_keys(anchor)
        # The decision leads, then the reading of the material, then the text:
        # each line of the prompt is read in the light of the ones above it.
        preamble = "".join(
            f"{part}\n\n" for part in (render_anchor(anchor), extra_context) if part
        )

        all_raw_claims: list[dict[str, Any]] = []
        has_temporal = True
        for i, chunk in enumerate(chunks):
            logger.debug("Processing chunk %d/%d (%d chars)", i + 1, len(chunks), len(chunk))
            try:
                result = await self._llm.complete_json(
                    system=claim_extraction_system(anchored),
                    user=(
                        preamble
                        + f"Extract all atomic claims from the following text:\n\n{chunk}"
                        f"{language_instruction(chunk)}"
                    ),
                    schema=claim_extraction_schema(anchored),
                )
                claims = result.get("claims", [])
                for c in claims:
                    if anchored:
                        c.update(clean_claim_scores(c, keys))
                    else:
                        # Not every provider enforces the schema. A relevance
                        # score volunteered without an anchor measures relevance
                        # to nothing, and once persisted would mark the project
                        # as anchored everywhere downstream.
                        for field in ("decision_role", "relevance",
                                      "relevance_reason", "bears_on"):
                            c.pop(field, None)
                # Use logprob-based confidence if available (more calibrated
                # than LLM self-reported confidence scores)
                logprob_conf = result.get("_logprob_confidence")
                if logprob_conf is not None:
                    for c in claims:
                        # Blend: 70% logprob + 30% LLM self-report
                        llm_conf = c.get("confidence", 0.5)
                        c["confidence"] = round(0.7 * logprob_conf + 0.3 * llm_conf, 3)
                if i == 0:
                    has_temporal = result.get("has_temporal_relevance", True)
                logger.debug("Extracted %d claims from chunk %d", len(claims), i + 1)
                all_raw_claims.extend(claims)
            except Exception as exc:
                raise PipelineError(
                    f"Claim extraction failed on chunk {i + 1}: {exc}"
                ) from exc

        if not all_raw_claims:
            logger.warning("No claims extracted from any chunk")
            return [], has_temporal

        # Assign order indices (no embedding yet — that's done separately)
        for order, claim in enumerate(all_raw_claims):
            claim["order_index"] = order
            claim["source_sentence"] = claim.get("source_sentence", "")

        before = len(all_raw_claims)
        all_raw_claims = _drop_document_metadata(all_raw_claims)
        # Kept on the extractor rather than smuggled inside a claim dict: a
        # claim is a row in the database, and an out-of-band field on one would
        # eventually be persisted by someone who did not know it was there.
        self.metadata_dropped = before - len(all_raw_claims)

        logger.info("Extracted %d raw claims", len(all_raw_claims))
        return all_raw_claims, has_temporal

    async def embed_claims(
        self, claims: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Embed claims and deduplicate by cosine similarity.

        This is separated from ``extract()`` so that claims can be saved
        to the database and shown to the user immediately, before the
        (slower) embedding step runs.

        Args:
            claims: List of claim dicts from ``extract()``.

        Returns:
            Deduplicated claims with "embedding" keys attached.

        Raises:
            PipelineError: If embedding fails.
        """
        if not claims:
            return claims

        claim_texts = [c["text"] for c in claims]
        try:
            embeddings = await self._embedder.embed_batch(claim_texts)
        except Exception as exc:
            raise PipelineError(f"Failed to embed claims: {exc}") from exc

        # Deduplicate by cosine similarity
        embedding_matrix = np.array(embeddings)
        unique_indices: list[int] = []
        for idx in range(len(claims)):
            is_duplicate = False
            for kept_idx in unique_indices:
                sim = _cosine_similarity(
                    embedding_matrix[idx], embedding_matrix[kept_idx]
                )
                if sim > _DEDUP_SIMILARITY_THRESHOLD:
                    is_duplicate = True
                    break
            if not is_duplicate:
                unique_indices.append(idx)

        logger.info(
            "Deduplicated %d raw claims to %d unique claims",
            len(claims), len(unique_indices),
        )

        # order_index is left alone. The orchestrator uses it to find each
        # claim's already-saved row, so renumbering here pointed every claim
        # after the first dropped duplicate at its neighbour's row — and deleted
        # the wrong rows as "duplicates". Chunks overlap by design, so on long
        # material a dropped duplicate is the normal case, not the exception.
        # (claim_dedup documents the same trap and avoids it the same way.)
        result_claims: list[dict[str, Any]] = []
        for idx in unique_indices:
            claim = claims[idx]
            claim["embedding"] = embeddings[idx]
            result_claims.append(claim)

        return result_claims
