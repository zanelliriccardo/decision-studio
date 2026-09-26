"""Pipeline Orchestrator.

Runs the full 5-stage causal analysis pipeline, emitting progress events
and persisting results to the database at each stage.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Callable, Coroutine

from sqlalchemy.ext.asyncio import AsyncSession

from decision_studio.db.models import AnalysisUsage, Claim, CausalEdge, Evidence, Project
from decision_studio.evidence.web_search import BraveSearchClient
from decision_studio.exceptions import PipelineError
from decision_studio.graph.anchoring import anchored_edges, edge_priority
from decision_studio.graph.belief_propagation import propagate_beliefs
from decision_studio.graph.critical_path import find_critical_path
from decision_studio.graph.sensitivity import analyze_sensitivity
from decision_studio.llm.client import LLMClient
from decision_studio.llm.embeddings import EmbeddingService
from decision_studio.pipeline.bias_auditor import BiasAuditor
from decision_studio.pipeline.blind_rescorer import BlindRescorer
from decision_studio.llm import usage as usage_tracking
from decision_studio.pipeline.claim_dedup import dedup_claims
from decision_studio.reasoning.source_interest import apply_to_claims as apply_source_interest
from decision_studio.pipeline.causal_inferrer import CausalInferrer
from decision_studio.pipeline.claim_extractor import ClaimExtractor
from decision_studio.pipeline.dag_builder import DAGBuilder
from decision_studio.pipeline.discovery import DiscoveryEngine
from decision_studio.pipeline.evidence_grounder import EvidenceGrounder
from decision_studio.pipeline.statistical_validator import StatisticalValidator
from decision_studio.reasoning.decision_anchor import (
    ORIGIN_FRAME,
    ROLE_OUTCOME,
    draft_anchor,
    normalise_anchor,
    outcome_claim_text,
    render_anchor,
    score_relevance,
)

logger = logging.getLogger(__name__)

#: Ceiling on evidence grounding, in seconds.
#:
#: The stage issues two web searches per edge — 34 for a seventeen-edge graph —
#: and the free search backend rate-limits without warning. With a 30-second
#: HTTP timeout per request and no ceiling on the stage, a run sat there for
#: tens of minutes looking exactly like a hang: the graph was built, and nothing
#: after it ever started.
#:
#: Grounding is also the one stage whose absence is survivable — the evidence
#: floor keeps every edge propagating without it — which makes it the right
#: place to give up rather than wait.
EVIDENCE_GROUNDING_TIMEOUT = 180.0

#: Ceiling on free-text fields written by the model, in characters.
#:
#: A belt to the schema's braces. The columns are now unbounded text, so this is
#: not needed to make the INSERT succeed — it is here because a "time delay"
#: that runs to two thousand characters is a malformed answer, and storing it
#: whole means it reappears in every prompt that renders the edge, crowding out
#: the parts that matter.
#:
#: Truncation is logged. A value quietly cut in half is worse than one that
#: fails loudly, so the record of it has to exist somewhere.
MAX_FREE_TEXT_CHARS = 2000


def _bounded(value: Any, field: str, limit: int = MAX_FREE_TEXT_CHARS) -> Any:
    """Cap a model-written string, noting when it was necessary."""
    if not isinstance(value, str) or len(value) <= limit:
        return value
    logger.warning(
        "Truncated %s from %d to %d characters — the model returned prose where "
        "a short answer was asked for", field, len(value), limit,
    )
    return value[:limit]

# Maximum new claims to keep per discovery layer (prevents combinatorial explosion)
_MAX_CLAIMS_PER_LAYER = 30

# Pipeline stage names
STAGE_CLAIM_EXTRACTION = "claim_extraction"
STAGE_CAUSAL_INFERENCE = "causal_inference"
STAGE_BLIND_SCORING = "blind_scoring"
STAGE_BIAS_AUDIT = "bias_audit"
STAGE_EVIDENCE_GROUNDING = "evidence_grounding"
STAGE_STATISTICAL_VALIDATION = "statistical_validation"
STAGE_DISCOVERY = "discovery"
STAGE_DAG_CONSTRUCTION = "dag_construction"
STAGE_BELIEF_PROPAGATION = "belief_propagation"
STAGE_GRAPH_UPDATED = "graph_updated"

# Event callback type alias
EventCallback = Callable[["PipelineEvent"], Coroutine[Any, Any, None]] | None


class PipelineEvent:
    """Event emitted during pipeline execution.

    Attributes:
        stage: The current pipeline stage name.
        status: One of "started", "progress", "completed", or "error".
        data: Stage-specific data (e.g., extracted claims, edges).
        progress: Completion fraction, 0.0 to 1.0.
    """

    def __init__(
        self,
        stage: str,
        status: str,
        data: Any = None,
        progress: float = 0.0,
        layer: int = 0,
    ) -> None:
        """One event in a run's progress, emitted to the log and the stream."""
        self.stage = stage
        self.status = status
        self.data = data
        self.progress = progress
        self.layer = layer

    def __repr__(self) -> str:
        """The stage and status, for logs."""
        return (
            f"PipelineEvent(stage={self.stage!r}, status={self.status!r}, "
            f"progress={self.progress:.2f}, layer={self.layer})"
        )


class CausalPipeline:
    """Orchestrates the full 5-stage causal chain reasoning pipeline.

    Stages:
    1. Claim Extraction: Decompose input text into atomic claims.
    2. Causal Inference: Identify causal links between claims.
    3. Evidence Grounding: Search for and score supporting/contradicting evidence.
    4. DAG Construction: Build a directed acyclic graph, break cycles.
    5. Belief Propagation: Propagate beliefs through the graph via Noisy-OR.

    After all stages, sensitivity analysis and critical path are computed.
    """

    def __init__(
        self,
        session: AsyncSession,
        llm_client: LLMClient,
        embedding_service: EmbeddingService,
        search_client: BraveSearchClient | None = None,
        metric_data: dict | None = None,
    ) -> None:
        """Hold everything the nine stages need, for one run.

        The model client is kept on the instance as well as handed to each
        stage: a stage that calls the model directly has no other way to reach
        it, and the absence of that reference is how one was added and found
        nothing.
        """
        self.session = session
        # Kept as well as passed on: stages that call the model directly --
        self.llm = llm_client
        self.embedder = embedding_service
        self.claim_extractor = ClaimExtractor(llm_client, embedding_service)
        self.causal_inferrer = CausalInferrer(llm_client)
        self.bias_auditor = BiasAuditor(llm_client)
        self.evidence_grounder = (
            EvidenceGrounder(llm_client, search_client)
            if search_client
            else None
        )
        self.discovery_engine = DiscoveryEngine(llm_client, embedding_service, search_client)
        self.blind_rescorer = BlindRescorer(llm_client)
        self.dag_builder = DAGBuilder()
        self.statistical_validator = StatisticalValidator(metric_data)

    # Ordered pipeline stages for checkpoint comparison
    _STAGE_ORDER = [
        STAGE_CLAIM_EXTRACTION,
        STAGE_CAUSAL_INFERENCE,
        STAGE_BLIND_SCORING,
        STAGE_BIAS_AUDIT,
        STAGE_EVIDENCE_GROUNDING,
        STAGE_STATISTICAL_VALIDATION,
        STAGE_DISCOVERY,
        STAGE_DAG_CONSTRUCTION,
        STAGE_BELIEF_PROPAGATION,
    ]

    def _stage_completed(self, stage: str, checkpoint: str | None) -> bool:
        """Check if a stage was already completed in a previous run."""
        if checkpoint is None:
            return False
        try:
            return self._STAGE_ORDER.index(stage) <= self._STAGE_ORDER.index(checkpoint)
        except ValueError:
            return False

    async def _save_checkpoint(
        self, project_id: uuid.UUID, stage: str
    ) -> None:
        """Record the last completed stage for resume capability."""
        try:
            project = await self.session.get(Project, project_id)
            if project is not None:
                project.last_completed_stage = stage
                await self.session.flush()
        except Exception as exc:
            logger.warning("Failed to save checkpoint: %s", exc)

    async def _load_claims_from_db(
        self, project_id: uuid.UUID
    ) -> tuple[list[dict[str, Any]], list[uuid.UUID]]:
        """Load existing claims from DB for pipeline resume."""
        from sqlalchemy import select

        result = await self.session.execute(
            select(Claim)
            .where(Claim.project_id == project_id)
            .order_by(Claim.order_index)
        )
        db_claims = result.scalars().all()

        claims: list[dict[str, Any]] = []
        claim_db_ids: list[uuid.UUID] = []
        for c in db_claims:
            claims.append({
                "text": c.text,
                "type": c.claim_type,
                "confidence": c.confidence,
                "embedding": list(c.embedding) if c.embedding is not None else None,
                "order_index": c.order_index,
                "source_sentence": c.source_sentence or "",
                "layer": c.layer,
                "origin": c.origin,
                "decision_role": c.decision_role,
                "relevance": c.relevance,
                "bears_on": c.bears_on,
                "metadata": c.metadata_,
            })
            claim_db_ids.append(c.id)

        return claims, claim_db_ids

    async def _load_edges_from_db(
        self, project_id: uuid.UUID, claim_db_ids: list[uuid.UUID],
    ) -> tuple[list[dict[str, Any]], list[uuid.UUID]]:
        """Load existing edges from DB for pipeline resume."""
        from sqlalchemy import select

        result = await self.session.execute(
            select(CausalEdge)
            .where(CausalEdge.project_id == project_id)
        )
        db_edges = result.scalars().all()

        # Build claim UUID → index mapping
        id_to_idx = {cid: idx for idx, cid in enumerate(claim_db_ids)}

        edges: list[dict[str, Any]] = []
        edge_db_ids: list[uuid.UUID] = []
        for e in db_edges:
            src_idx = id_to_idx.get(e.source_claim_id)
            tgt_idx = id_to_idx.get(e.target_claim_id)
            if src_idx is None or tgt_idx is None:
                continue
            edges.append({
                "source_idx": src_idx,
                "target_idx": tgt_idx,
                "mechanism": e.mechanism,
                "strength": e.strength,
                "time_delay": e.time_delay,
                "conditions": e.conditions or [],
                "reversible": e.reversible,
                "direction": "source_to_target",
                "causal_type": e.causal_type,
                "condition_type": e.condition_type,
                "temporal_window": e.temporal_window,
                "decay_type": e.decay_type,
                "evidence_score": e.evidence_score,
                "bias_warnings": e.bias_warnings,
            })
            edge_db_ids.append(e.id)

        return edges, edge_db_ids

    async def run(
        self,
        project_id: str,
        text: str,
        event_callback: EventCallback = None,
        max_layers: int = 3,
        extra_context: str | None = None,
    ) -> dict[str, Any]:
        """Run the full pipeline with multi-layer discovery.

        Supports **checkpoint resume**: if the pipeline previously failed,
        it loads existing claims/edges from the database and skips
        already-completed stages.

        Args:
            project_id: The UUID of the project to associate results with.
            text: The input text to analyze.
            event_callback: Optional async callable to receive PipelineEvents.
            max_layers: Maximum number of discovery layers (default 3).
            extra_context: The intake answers, prepended to the extraction and
                inference prompts. Reaches both stages rather than only
                inference: a disambiguation arriving after extraction can only
                correct claims that were already split the wrong way, whereas
                one arriving before it stops them being split that way at all.

        Returns:
            A dict containing claims, edges, graph, critical_path, sensitivity.

        Raises:
            PipelineError: If any pipeline stage fails.
        """
        # Opened here so every model call underneath is attributed, including
        # ones made by stages added later that know nothing about this.
        ledger = usage_tracking.start_ledger(project_id)
        run_started = time.monotonic()
        logger.info("=== Pipeline started for project %s ===", project_id)

        project_uuid = uuid.UUID(project_id) if isinstance(project_id, str) else project_id

        # Check for existing checkpoint
        project = await self.session.get(Project, project_uuid)
        checkpoint = project.last_completed_stage if project else None
        resuming = checkpoint is not None

        if resuming:
            logger.info(
                "Resuming pipeline for project %s from checkpoint: %s",
                project_id, checkpoint,
            )

        anchor = await self._resolve_anchor(project, text)
        # The anchor reaches inference as well as extraction: the judge deciding
        # whether a claim drives an outcome needs to know what the outcome is for.
        inference_context = "\n".join(
            part for part in (render_anchor(anchor), extra_context) if part
        ) or None

        try:
            # ==================================================================
            # Layer 0: Seed
            # ==================================================================

            # Stage 1: Claim Extraction
            if self._stage_completed(STAGE_CLAIM_EXTRACTION, checkpoint):
                # Resume: load existing claims from DB
                logger.info("Skipping claim extraction (checkpoint)")
                claims, claim_db_ids = await self._load_claims_from_db(project_uuid)
                has_temporal = project.has_temporal if project else True
                await self._emit(
                    PipelineEvent(
                        STAGE_CLAIM_EXTRACTION, "completed",
                        data={"count": len(claims), "resumed": True},
                        progress=0.10, layer=0,
                    ),
                    event_callback,
                )
            else:
                # Fresh run: extract claims
                await self._emit(
                    PipelineEvent(STAGE_CLAIM_EXTRACTION, "started", progress=0.0, layer=0),
                    event_callback,
                )

                # Phase A: LLM extraction — fast, no embedding yet
                claims, has_temporal = await self.claim_extractor.extract(
                    text, extra_context=extra_context, anchor=anchor
                )

                if project is not None:
                    project.has_temporal = has_temporal
                    await self.session.flush()

                for c in claims:
                    c["layer"] = 0

                if not claims:
                    raise PipelineError("No claims were extracted from the input text")

                # Save claims to DB immediately (without embeddings)
                claim_db_ids = await self._save_claims(project_uuid, claims)
                await self.session.commit()
                logger.info("Claims saved (no embeddings yet): %d", len(claims))
                await self._emit_graph_updated(event_callback, "claims_extracted")

                # Phase B: Embed + deduplicate
                claims = await self.claim_extractor.embed_claims(claims)

                # Phase B2: collapse the same fact restated across documents.
                # Runs before evidence grounding so retrieval is not spent three
                # times on one fact, and before belief propagation so a repeated
                # claim does not shift the same prior repeatedly.
                # Who asserts a claim changes how much it should be believed.
                # Applied as an explicit, logged adjustment rather than left
                # inside the extractor's free-form estimate, so it is auditable.
                interest_report = apply_source_interest(claims)
                if interest_report["raised"] or interest_report["lowered"]:
                    logger.info(
                        "Source interest adjusted %d priors up, %d down",
                        interest_report["raised"], interest_report["lowered"],
                    )

                claims, dedup_report = dedup_claims(claims)
                if dedup_report["merged"]:
                    logger.info(
                        "Claim dedup merged %d restatements: %s",
                        dedup_report["merged"],
                        [g["kept"][:60] for g in dedup_report["groups"]],
                    )

                await self._update_claim_embeddings(project_uuid, claims, claim_db_ids)
                await self.session.commit()
                logger.info("Claims embedded and deduplicated: %d", len(claims))

                claim_db_ids = [
                    claim_db_ids[c["order_index"]] for c in claims
                ]

                # Outcome nodes join after dedup, so an extracted claim that
                # restates a success criterion is never merged into one.
                # order_index is sparse after dedup; start past the highest.
                outcome_claims = await self._outcome_claims(
                    anchor,
                    max((c.get("order_index", 0) for c in claims), default=-1) + 1,
                )
                if outcome_claims:
                    claim_db_ids.extend(
                        await self._save_claims(project_uuid, outcome_claims)
                    )
                    claims.extend(outcome_claims)
                    await self.session.commit()

                await self._save_checkpoint(project_uuid, STAGE_CLAIM_EXTRACTION)
                await self.session.commit()


            await self._emit(
                PipelineEvent(
                    STAGE_CLAIM_EXTRACTION, "completed",
                    data={
                        "count": len(claims),
                        # Surfaced so a run that dropped a third of its
                        # input says so on screen, not only in the log.
                        "metadata_dropped": getattr(
                            self.claim_extractor, "metadata_dropped", 0
                        ),
                        "claims": _lightweight_claims(claims),
                    },
                    progress=0.10, layer=0,
                ),
                event_callback,
            )
            await self._emit_graph_updated(event_callback, "claims_embedded")

            # Stage 2: Causal Inference
            if self._stage_completed(STAGE_CAUSAL_INFERENCE, checkpoint):
                logger.info("Skipping causal inference (checkpoint)")
                edges, edge_db_ids = await self._load_edges_from_db(project_uuid, claim_db_ids)
                await self._emit(
                    PipelineEvent(
                        STAGE_CAUSAL_INFERENCE, "completed",
                        data={"count": len(edges), "resumed": True},
                        progress=0.20, layer=0,
                    ),
                    event_callback,
                )
            else:
                await self._emit(
                    PipelineEvent(STAGE_CAUSAL_INFERENCE, "started", progress=0.10, layer=0),
                    event_callback,
                )

                edges = await self.causal_inferrer.infer(
                    claims, extra_context=inference_context
                )

                await self._emit(
                    PipelineEvent(
                        STAGE_CAUSAL_INFERENCE, "completed",
                        data={
                            "count": len(edges),
                            "edges": _lightweight_edges(claims, edges),
                        },
                        progress=0.20, layer=0,
                    ),
                    event_callback,
                )

                # Stage 2b: blind re-scoring. The call that proposed these edges
                # also scored them, so a vividly written mechanism buys strength
                # it has not earned. Re-rate them with the identifiers stripped.
                if not self._stage_completed(STAGE_BLIND_SCORING, checkpoint):
                    await self._emit(
                        PipelineEvent(STAGE_BLIND_SCORING, "started", progress=0.22, layer=0),
                        event_callback,
                    )
                    edges, blind_report = await self.blind_rescorer.rescore(edges, claims)
                    await self._emit(
                        PipelineEvent(
                            STAGE_BLIND_SCORING, "completed",
                            data=blind_report, progress=0.24, layer=0,
                        ),
                        event_callback,
                    )

                edge_db_ids = await self._save_edges(project_uuid, edges, claim_db_ids)
                await self._save_checkpoint(project_uuid, STAGE_BLIND_SCORING)
                await self.session.commit()
                logger.info("Edges committed: %d", len(edges))
                await self._emit_graph_updated(event_callback, "edges_inferred")

            # Stage 2.5: Bias Audit
            if self._stage_completed(STAGE_BIAS_AUDIT, checkpoint):
                logger.info("Skipping bias audit (checkpoint)")
                await self._emit(
                    PipelineEvent(
                        STAGE_BIAS_AUDIT, "completed",
                        data={"edges_audited": len(edges), "resumed": True},
                        progress=0.30, layer=0,
                    ),
                    event_callback,
                )
            else:
                await self._emit(
                    PipelineEvent(STAGE_BIAS_AUDIT, "started", progress=0.20, layer=0),
                    event_callback,
                )

                edges = await self.bias_auditor.audit(claims, edges)

                await self._emit(
                    PipelineEvent(
                        STAGE_BIAS_AUDIT, "completed",
                        data={
                            "edges_audited": len(edges),
                            "edges": _lightweight_edges(claims, edges),
                        },
                        progress=0.30, layer=0,
                    ),
                    event_callback,
                )

                await self._update_edges(edge_db_ids, edges)
                await self._save_checkpoint(project_uuid, STAGE_BIAS_AUDIT)
                await self.session.commit()
                logger.info("Bias audit committed for %d edges", len(edges))
                await self._emit_graph_updated(event_callback, "bias_audited")

            # Stage 3: Evidence Grounding
            if self._stage_completed(STAGE_EVIDENCE_GROUNDING, checkpoint):
                logger.info("Skipping evidence grounding (checkpoint)")
                await self._emit(
                    PipelineEvent(
                        STAGE_EVIDENCE_GROUNDING, "completed",
                        data={"resumed": True},
                        progress=0.40, layer=0,
                    ),
                    event_callback,
                )
            elif self.evidence_grounder and edges:
                await self._emit(
                    PipelineEvent(STAGE_EVIDENCE_GROUNDING, "started", progress=0.30, layer=0),
                    event_callback,
                )

                async def _evidence_progress_l0(completed: int, total: int, edge: dict[str, Any]) -> None:
                    """Report grounding progress on the first layer."""
                    frac = completed / total
                    await self._emit(
                        PipelineEvent(
                            STAGE_EVIDENCE_GROUNDING, "progress",
                            data={
                                "completed": completed,
                                "total": total,
                                "edge": _lightweight_edge(edge, claims),
                            },
                            progress=0.30 + frac * 0.10,  # 0.30 → 0.40
                            layer=0,
                        ),
                        event_callback,
                    )

                try:
                    edges = await asyncio.wait_for(
                        self.evidence_grounder.ground(
                            claims, edges, on_progress=_evidence_progress_l0
                        ),
                        timeout=EVIDENCE_GROUNDING_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    # Keep the edges as they are and carry on: an ungrounded
                    # edge still propagates, so the graph is weaker rather than
                    # wrong, and a graph that arrives beats one still waiting.
                    logger.warning(
                        "Evidence grounding exceeded %.0fs and was abandoned; "
                        "%d edge(s) remain ungrounded",
                        EVIDENCE_GROUNDING_TIMEOUT, len(edges),
                    )

                await self._emit(
                    PipelineEvent(
                        STAGE_EVIDENCE_GROUNDING, "completed",
                        data={
                            "edges_grounded": len(edges),
                            "edges": _lightweight_edges(claims, edges),
                        },
                        progress=0.40, layer=0,
                    ),
                    event_callback,
                )

                # Update edges with evidence scores and save evidence records
                await self._update_edges(edge_db_ids, edges)
                await self._save_evidences(edges, edge_db_ids)
                await self._save_checkpoint(project_uuid, STAGE_EVIDENCE_GROUNDING)
                await self.session.commit()
                logger.info("Evidence grounding committed for %d edges", len(edges))
                await self._emit_graph_updated(event_callback, "evidence_grounded")
            else:
                logger.info("Skipping evidence grounding (no search client or no edges)")
                await self._emit(
                    PipelineEvent(
                        STAGE_EVIDENCE_GROUNDING, "completed",
                        data={"skipped": True},
                        progress=0.40, layer=0,
                    ),
                    event_callback,
                )

            # ==================================================================
            # Stage 3.5: Statistical Validation
            # ==================================================================
            await self._emit(
                PipelineEvent(STAGE_STATISTICAL_VALIDATION, "started", progress=0.40),
                event_callback,
            )

            edges = self.statistical_validator.validate(claims, edges)

            stat_counts = {"confirmed": 0, "unsupported": 0, "contradicted": 0, "not_tested": 0}
            for e in edges:
                sv = e.get("statistical_validation", "not_tested")
                stat_counts[sv] = stat_counts.get(sv, 0) + 1

            await self._emit(
                PipelineEvent(
                    STAGE_STATISTICAL_VALIDATION, "completed",
                    data=stat_counts,
                    progress=0.42,
                ),
                event_callback,
            )

            # Update edges in DB with statistical validation results
            await self._update_edges(edge_db_ids, edges)
            await self.session.commit()
            logger.info(
                "Statistical validation committed: %d confirmed, %d unsupported, %d contradicted",
                stat_counts["confirmed"], stat_counts["unsupported"], stat_counts["contradicted"],
            )
            await self._emit_graph_updated(event_callback, "statistical_validated")

            # ==================================================================
            # Layers 1..N: Discovery
            # ==================================================================
            # Discovery layers share progress range 0.42 -> 0.70
            discovery_progress_range = 0.30  # 0.40 to 0.70
            progress_per_layer = discovery_progress_range / max_layers if max_layers > 0 else 0

            for layer in range(1, max_layers + 1):
                layer_start = 0.40 + (layer - 1) * progress_per_layer
                layer_end = 0.40 + layer * progress_per_layer

                # Discovery stage
                await self._emit(
                    PipelineEvent(
                        STAGE_DISCOVERY, "started",
                        progress=layer_start, layer=layer,
                    ),
                    event_callback,
                )

                # Discovery follows the decision rather than the documents:
                # only edges on a path to an outcome (or between relevant
                # claims) are expanded. Everything, without an anchor.
                expandable = anchored_edges(claims, edges)
                if len(expandable) < len(edges):
                    logger.info(
                        "Discovery layer %d: expanding %d of %d edge(s) that bear "
                        "on the decision", layer, len(expandable), len(edges),
                    )
                new_claims = await self.discovery_engine.discover(claims, expandable)

                if anchor and new_claims:
                    scores = await score_relevance(
                        self.llm, anchor, [c["text"] for c in new_claims]
                    )
                    for claim, score in zip(new_claims, scores):
                        if score:
                            claim.update(score)

                if len(new_claims) < 1:
                    logger.info("Discovery layer %d: no new claims, converging", layer)
                    await self._emit(
                        PipelineEvent(
                            STAGE_DISCOVERY, "completed",
                            data={"new_claims": 0, "converged": True},
                            progress=layer_end, layer=layer,
                        ),
                        event_callback,
                    )
                    break

                # Cap claims per layer to prevent combinatorial explosion
                if len(new_claims) > _MAX_CLAIMS_PER_LAYER:
                    # Keep the most relevant, then the most confident. Unscored
                    # claims all rank equal on relevance, which reduces to the
                    # old confidence ordering.
                    new_claims.sort(
                        key=lambda c: (
                            c.get("relevance") if c.get("relevance") is not None else 0.0,
                            c.get("confidence", 0.5),
                        ),
                        reverse=True,
                    )
                    new_claims = new_claims[:_MAX_CLAIMS_PER_LAYER]
                    logger.info(
                        "Discovery layer %d: capped to %d claims (from more)",
                        layer, _MAX_CLAIMS_PER_LAYER,
                    )

                # Tag new claims with layer number and assign order indices
                new_start_idx = len(claims)
                for i, c in enumerate(new_claims):
                    c["layer"] = layer
                    c["order_index"] = new_start_idx + i

                claims.extend(new_claims)
                new_indices = set(range(new_start_idx, len(claims)))

                logger.info(
                    "Discovery layer %d: found %d new claims",
                    layer, len(new_claims),
                )

                await self._emit(
                    PipelineEvent(
                        STAGE_DISCOVERY, "completed",
                        data={
                            "new_claims": len(new_claims),
                            "claims": _lightweight_claims(new_claims, start_index=new_start_idx),
                        },
                        progress=layer_start + progress_per_layer * 0.25, layer=layer,
                    ),
                    event_callback,
                )

                # Persist discovered claims immediately
                new_claim_db_ids = await self._save_claims(project_uuid, new_claims)
                claim_db_ids.extend(new_claim_db_ids)
                await self.session.commit()
                await self._emit_graph_updated(event_callback, f"discovery_L{layer}_claims")

                # Incremental causal inference
                await self._emit(
                    PipelineEvent(
                        STAGE_CAUSAL_INFERENCE, "started",
                        progress=layer_start + progress_per_layer * 0.25, layer=layer,
                    ),
                    event_callback,
                )

                new_edges = await self.causal_inferrer.infer_incremental(
                    claims, new_indices, extra_context=inference_context
                )

                # Enforce global edge budget: total edges ≤ claims × 2
                max_total_edges = max(10, len(claims) * 2)
                edge_room = max(0, max_total_edges - len(edges))
                if len(new_edges) > edge_room:
                    new_edges.sort(key=lambda e: edge_priority(e, claims), reverse=True)
                    new_edges = new_edges[:edge_room]
                    logger.info(
                        "Discovery L%d: pruned incremental edges to %d (budget: %d total)",
                        layer, edge_room, max_total_edges,
                    )

                await self._emit(
                    PipelineEvent(
                        STAGE_CAUSAL_INFERENCE, "completed",
                        data={
                            "count": len(new_edges),
                            "edges": _lightweight_edges(claims, new_edges),
                        },
                        progress=layer_start + progress_per_layer * 0.5, layer=layer,
                    ),
                    event_callback,
                )

                # Persist new edges immediately
                new_edge_db_ids = await self._save_edges(
                    project_uuid, new_edges, claim_db_ids,
                )
                edge_db_ids.extend(new_edge_db_ids)
                await self.session.commit()
                await self._emit_graph_updated(event_callback, f"discovery_L{layer}_edges")

                # Bias audit on new edges
                if new_edges:
                    await self._emit(
                        PipelineEvent(
                            STAGE_BIAS_AUDIT, "started",
                            progress=layer_start + progress_per_layer * 0.5, layer=layer,
                        ),
                        event_callback,
                    )

                    new_edges = await self.bias_auditor.audit(claims, new_edges)

                    await self._emit(
                        PipelineEvent(
                            STAGE_BIAS_AUDIT, "completed",
                            data={
                                "edges_audited": len(new_edges),
                                "edges": _lightweight_edges(claims, new_edges),
                            },
                            progress=layer_start + progress_per_layer * 0.75, layer=layer,
                        ),
                        event_callback,
                    )

                    # Update edges in DB with bias results
                    await self._update_edges(new_edge_db_ids, new_edges)
                    await self.session.commit()
                    await self._emit_graph_updated(event_callback, f"discovery_L{layer}_bias")

                # Evidence grounding on new edges
                if self.evidence_grounder and new_edges:
                    ev_start = layer_start + progress_per_layer * 0.75

                    await self._emit(
                        PipelineEvent(
                            STAGE_EVIDENCE_GROUNDING, "started",
                            progress=ev_start, layer=layer,
                        ),
                        event_callback,
                    )

                    async def _evidence_progress_ln(completed: int, total: int, edge: dict[str, Any]) -> None:
                        """Report grounding progress on a discovery layer."""
                        frac = completed / total
                        await self._emit(
                            PipelineEvent(
                                STAGE_EVIDENCE_GROUNDING, "progress",
                                data={
                                    "completed": completed,
                                    "total": total,
                                    "edge": _lightweight_edge(edge, claims),
                                },
                                progress=ev_start + frac * (layer_end - ev_start),
                                layer=layer,
                            ),
                            event_callback,
                        )

                    new_edges = await self.evidence_grounder.ground(
                        claims, new_edges, on_progress=_evidence_progress_ln,
                    )

                    await self._emit(
                        PipelineEvent(
                            STAGE_EVIDENCE_GROUNDING, "completed",
                            data={
                                "edges_grounded": len(new_edges),
                                "edges": _lightweight_edges(claims, new_edges),
                            },
                            progress=layer_end, layer=layer,
                        ),
                        event_callback,
                    )

                    # Update edges with evidence + save evidence records
                    await self._update_edges(new_edge_db_ids, new_edges)
                    await self._save_evidences(new_edges, new_edge_db_ids)
                    await self.session.commit()
                    await self._emit_graph_updated(event_callback, f"discovery_L{layer}_evidence")

                edges.extend(new_edges)
                logger.info(
                    "Layer %d fully committed: %d claims, %d edges",
                    layer, len(new_claims), len(new_edges),
                )

                # Convergence check
                if len(new_claims) < 2 and len(new_edges) < 1:
                    logger.info(
                        "Discovery layer %d: diminishing returns, converging", layer,
                    )
                    break

            # ==================================================================
            # Final: DAG Construction
            # ==================================================================
            await self._emit(
                PipelineEvent(STAGE_DAG_CONSTRUCTION, "started", progress=0.70),
                event_callback,
            )

            graph, logic_gate_map, feedback_edges = self.dag_builder.build(claims, edges)

            await self._update_claim_logic_gates(
                claim_db_ids, claims, logic_gate_map
            )
            await self._mark_feedback_edges(claim_db_ids, feedback_edges)
            await self.session.commit()
            logger.info("DAG construction committed: logic gates updated")
            await self._emit_graph_updated(event_callback, "dag_constructed")

            await self._emit(
                PipelineEvent(
                    STAGE_DAG_CONSTRUCTION, "completed",
                    data={
                        "nodes": graph.number_of_nodes(),
                        "edges": graph.number_of_edges(),
                    },
                    progress=0.85,
                ),
                event_callback,
            )

            # ==================================================================
            # Final: Belief Propagation + Analysis
            # ==================================================================
            await self._emit(
                PipelineEvent(STAGE_BELIEF_PROPAGATION, "started", progress=0.85),
                event_callback,
            )

            graph = propagate_beliefs(graph)
            critical_path = find_critical_path(graph)
            sensitivity = analyze_sensitivity(graph)

            await self._emit(
                PipelineEvent(
                    STAGE_BELIEF_PROPAGATION, "completed",
                    data={"critical_path_length": len(critical_path)},
                    progress=1.0,
                ),
                event_callback,
            )

            # Update project status and commit
            await self._update_project_status(project_uuid, "completed")
            await self.session.commit()

            elapsed = time.monotonic() - run_started
            logger.info(
                "=== Pipeline completed for project %s in %.0fs: "
                "%d claims, %d edges ===",
                project_id, elapsed, len(claims), len(edges),
            )
            # The cost of the run, on one line, where someone will see it.
            logger.info("    Spend: %s", ledger.summary_line())
            await self._save_usage(project_uuid, ledger)
            for name, spend in sorted(
                ledger.stages.items(), key=lambda kv: -kv[1].cost_usd
            )[:5]:
                if spend.calls:
                    logger.info(
                        "      %-24s %3d call(s)  %8s tokens  $%.3f",
                        name, spend.calls,
                        f"{spend.input_tokens + spend.output_tokens:,}",
                        spend.cost_usd,
                    )

            return {
                "claims": claims,
                "edges": edges,
                "graph": graph,
                "critical_path": critical_path,
                "sensitivity": sensitivity,
            }

        except PipelineError:
            await self._update_project_status(project_uuid, "failed")
            await self.session.commit()
            raise
        except Exception as exc:
            await self._update_project_status(project_uuid, "failed")
            await self.session.commit()
            await self._emit(
                PipelineEvent("pipeline", "error", data={"error": str(exc)}),
                event_callback,
            )
            raise PipelineError(f"Pipeline failed: {exc}") from exc

    async def _resolve_anchor(
        self, project: Project | None, text: str
    ) -> dict[str, Any] | None:
        """The decision anchor for this run, drafting one when only an objective exists.

        Drafted here as well as on the intake screen, so a run that skipped the
        screen — the intake switch, ``/analyze``, a resumed run — is anchored
        the same way. Without a stated objective there is no anchor, and the
        run is exactly the one it was before anchors existed.
        """
        if project is None:
            return None
        anchor = normalise_anchor(getattr(project, "decision_anchor", None))
        if anchor is not None:
            return anchor
        anchor = await draft_anchor(self.llm, project.decision_objective, text)
        if anchor is not None:
            project.decision_anchor = anchor
            await self.session.commit()
            logger.info(
                "Drafted a decision anchor for project %s: %d option(s), %d outcome(s)",
                project.id, len(anchor["options"]), len(anchor["outcomes"]),
            )
        return anchor

    async def _outcome_claims(
        self, anchor: dict[str, Any] | None, start_index: int
    ) -> list[dict[str, Any]]:
        """One claim per anchor outcome: the destinations causal inference aims at.

        A prior of 0.5 because nothing is known yet about whether success will
        be reached — that is what the graph is for. Embedded because the
        inferrer computes similarities for every node, though outcomes bypass
        its similarity filter.
        """
        outcomes = (anchor or {}).get("outcomes") or []
        if not outcomes:
            return []
        texts = [outcome_claim_text(o) for o in outcomes]
        try:
            embeddings = await self.embedder.embed_batch(texts)
        except Exception as exc:
            raise PipelineError(f"Failed to embed outcome nodes: {exc}") from exc
        return [
            {
                "text": text,
                "type": "PREDICTION",
                "confidence": 0.5,
                "prior": 0.5,
                "source_interest": "disinterested",
                "source_role": "the decision anchor",
                "source_sentence": "",
                "embedding": embedding,
                "order_index": start_index + i,
                "layer": 0,
                "origin": ORIGIN_FRAME,
                "decision_role": ROLE_OUTCOME,
                "relevance": 1.0,
                "bears_on": [outcome["key"]],
                "metadata": {"anchor_key": outcome["key"]},
            }
            for i, (outcome, text, embedding) in enumerate(zip(outcomes, texts, embeddings))
        ]

    async def _emit(
        self,
        event: PipelineEvent,
        callback: EventCallback,
    ) -> None:
        """Emit a pipeline event via the callback, if provided."""
        logger.debug("Pipeline event: %s", event)
        if event.status == "started":
            # Every stage announces itself here, so this is the one place cost
            # attribution can follow the run without each stage opting in.
            usage_tracking.set_stage(event.stage)
        if callback is not None:
            await callback(event)

    async def _emit_graph_updated(
        self,
        callback: EventCallback,
        reason: str,
    ) -> None:
        """Emit a graph_updated event after data has been committed to DB.

        The frontend listens for this to re-fetch the graph, providing
        real-time incremental updates as claims and edges are discovered.
        """
        await self._emit(
            PipelineEvent(
                STAGE_GRAPH_UPDATED, "completed",
                data={"reason": reason},
            ),
            callback,
        )

    async def _save_claims(
        self,
        project_id: uuid.UUID,
        claims: list[dict[str, Any]],
    ) -> list[uuid.UUID]:
        """Persist extracted claims to the database.

        Args:
            project_id: The project UUID.
            claims: List of claim dicts.

        Returns:
            List of generated claim UUIDs, in the same order as the input.
        """
        claim_ids: list[uuid.UUID] = []
        for claim_data in claims:
            claim_id = uuid.uuid4()
            claim = Claim(
                id=claim_id,
                project_id=project_id,
                text=claim_data["text"],
                claim_type=claim_data["type"],
                confidence=claim_data["confidence"],
                # Assertion firmness is NOT a probability; fall back to it only
                # when the extractor did not supply a separate prior.
                prior=claim_data.get("prior", claim_data["confidence"]),
                source_interest=claim_data.get("source_interest", "unknown"),
                source_role=(claim_data.get("source_role") or "").strip() or None,
                corroborated_by=claim_data.get("corroborated_by"),
                duplicate_count=claim_data.get("duplicate_count", 0),
                embedding=claim_data.get("embedding"),
                source_sentence=claim_data.get("source_sentence"),
                order_index=claim_data.get("order_index", 0),
                layer=claim_data.get("layer", 0),
                origin=claim_data.get("origin", "ai"),
                decision_role=claim_data.get("decision_role"),
                relevance=claim_data.get("relevance"),
                relevance_reason=claim_data.get("relevance_reason"),
                bears_on=claim_data.get("bears_on"),
                metadata_=claim_data.get("metadata"),
            )
            self.session.add(claim)
            claim_ids.append(claim_id)

        await self.session.flush()
        logger.info("Saved %d claims to database", len(claim_ids))
        return claim_ids

    async def _update_claim_embeddings(
        self,
        project_id: uuid.UUID,
        claims: list[dict[str, Any]],
        all_claim_db_ids: list[uuid.UUID],
    ) -> None:
        """Update claim embeddings and delete duplicates after deduplication.

        After embed_claims() runs, some original claims may have been removed
        as duplicates. This updates embeddings on kept claims and deletes
        the duplicates from the DB.
        """
        kept_indices = {c["order_index"] for c in claims}

        for claim_data in claims:
            idx = claim_data["order_index"]
            claim_id = all_claim_db_ids[idx]
            db_claim = await self.session.get(Claim, claim_id)
            if db_claim is None:
                continue
            if "embedding" in claim_data:
                db_claim.embedding = claim_data["embedding"]
            # Corroboration lift and merge provenance from semantic dedup.
            if claim_data.get("duplicate_count"):
                db_claim.corroborated_by = claim_data.get("corroborated_by")
                db_claim.duplicate_count = claim_data["duplicate_count"]
                db_claim.prior = claim_data.get("prior", db_claim.prior)

        # Delete duplicate claims from DB
        for idx, claim_id in enumerate(all_claim_db_ids):
            if idx not in kept_indices:
                db_claim = await self.session.get(Claim, claim_id)
                if db_claim is not None:
                    await self.session.delete(db_claim)

        await self.session.flush()
        logger.info(
            "Updated embeddings for %d claims, removed %d duplicates",
            len(claims), len(all_claim_db_ids) - len(claims),
        )

    async def _save_edges(
        self,
        project_id: uuid.UUID,
        edges: list[dict[str, Any]],
        claim_ids: list[uuid.UUID],
    ) -> list[uuid.UUID]:
        """Persist causal edges to the database.

        Args:
            project_id: The project UUID.
            edges: List of edge dicts.
            claim_ids: List of claim UUIDs (indexed by claim order).

        Returns:
            List of generated edge UUIDs, in the same order as the input.
        """
        edge_ids: list[uuid.UUID] = []
        for edge_data in edges:
            edge_id = uuid.uuid4()
            source_idx = edge_data["source_idx"]
            target_idx = edge_data["target_idx"]

            edge = CausalEdge(
                id=edge_id,
                project_id=project_id,
                source_claim_id=claim_ids[source_idx],
                target_claim_id=claim_ids[target_idx],
                mechanism=edge_data.get("mechanism", ""),
                effect=edge_data.get("effect", edge_data.get("strength", 0.5)),
                link_confidence=edge_data.get("link_confidence", 1.0),
                strength=edge_data.get("strength", 0.5),
                author_effect=edge_data.get("author_effect"),
                author_confidence=edge_data.get("author_confidence"),
                blind_scored=edge_data.get("blind_scored", False),
                time_delay=_bounded(edge_data.get("time_delay"), "time_delay"),
                conditions=edge_data.get("conditions"),
                reversible=edge_data.get("reversible", False),
                evidence_score=edge_data.get("evidence_score", 0.5),
                causal_type=edge_data.get("causal_type", "direct"),
                condition_type=edge_data.get("condition_type", "contributing"),
                temporal_window=_bounded(
                    edge_data.get("temporal_window"), "temporal_window"
                ),
                decay_type=edge_data.get("decay_type", "none"),
                bias_warnings=edge_data.get("bias_warnings"),
            )
            self.session.add(edge)
            edge_ids.append(edge_id)

        await self.session.flush()
        logger.info("Saved %d edges to database", len(edge_ids))
        return edge_ids

    async def _update_edges(
        self,
        edge_ids: list[uuid.UUID],
        edges: list[dict[str, Any]],
    ) -> None:
        """Update existing edges in the database with new data.

        Used after bias audit (updates strength, bias_warnings) and
        evidence grounding (updates evidence_score).
        """
        for edge_id, edge_data in zip(edge_ids, edges):
            db_edge = await self.session.get(CausalEdge, edge_id)
            if db_edge is None:
                continue
            db_edge.strength = edge_data.get("strength", db_edge.strength)
            db_edge.evidence_score = edge_data.get(
                "evidence_score", db_edge.evidence_score,
            )
            if "bias_warnings" in edge_data:
                db_edge.bias_warnings = edge_data["bias_warnings"]
            if "statistical_validation" in edge_data:
                db_edge.statistical_validation = edge_data["statistical_validation"]
            if "stat_p_value" in edge_data:
                db_edge.stat_p_value = edge_data.get("stat_p_value")
                db_edge.stat_f_statistic = edge_data.get("stat_f_statistic")
                db_edge.stat_effect_size = edge_data.get("stat_effect_size")
                db_edge.stat_lag = edge_data.get("stat_lag")
        await self.session.flush()

    async def _save_evidences(
        self,
        edges: list[dict[str, Any]],
        edge_ids: list[uuid.UUID],
    ) -> None:
        """Persist evidence items to the database.

        Args:
            edges: List of edge dicts (some may contain "evidences" lists).
            edge_ids: Corresponding edge UUIDs.
        """
        count = 0
        for edge_data, edge_id in zip(edges, edge_ids):
            evidences = edge_data.get("evidences", [])
            for ev_data in evidences:
                evidence = Evidence(
                    id=uuid.uuid4(),
                    edge_id=edge_id,
                    evidence_type=ev_data.get("evidence_type", "supporting"),
                    source_url=ev_data.get("source_url", ""),
                    source_title=ev_data.get("source_title", ""),
                    source_type=ev_data.get("source_type", "other"),
                    snippet=ev_data.get("snippet", ""),
                    relevance_score=ev_data.get("relevance_score", 0.0),
                    credibility_score=ev_data.get("credibility_score", 0.4),
                    source_tier=ev_data.get("source_tier", 4),
                    published_date=ev_data.get("published_date"),
                    freshness_score=ev_data.get("freshness_score", 0.5),
                )
                self.session.add(evidence)
                count += 1

        if count > 0:
            await self.session.flush()
        logger.info("Saved %d evidence items to database", count)

    async def _update_claim_logic_gates(
        self,
        claim_ids: list[uuid.UUID],
        claims: list[dict[str, Any]],
        logic_gate_map: dict[str, str],
    ) -> None:
        """Update logic_gate on Claim records based on DAG analysis.

        Args:
            claim_ids: List of claim UUIDs (indexed by claim order).
            claims: Original claim dicts.
            logic_gate_map: Mapping from node_id (str index) to "or"|"and".
        """
        updated = 0
        for idx, claim_id in enumerate(claim_ids):
            gate = logic_gate_map.get(str(idx), "or")
            if gate != "or":
                claim = await self.session.get(Claim, claim_id)
                if claim is not None:
                    claim.logic_gate = gate
                    updated += 1

        if updated > 0:
            await self.session.flush()
        logger.info("Updated logic gates for %d claims", updated)

    async def _mark_feedback_edges(
        self,
        claim_ids: list[uuid.UUID],
        feedback_edges: list[tuple[str, str]],
    ) -> None:
        """Mark edges removed during cycle-breaking as feedback edges in DB.

        Args:
            claim_ids: List of claim UUIDs (indexed by claim order).
            feedback_edges: List of (source_node_id, target_node_id) tuples
                where node IDs are string indices into the claims list.
        """
        if not feedback_edges:
            return

        from sqlalchemy import select, and_

        marked = 0
        for source_idx_str, target_idx_str in feedback_edges:
            source_uuid = claim_ids[int(source_idx_str)]
            target_uuid = claim_ids[int(target_idx_str)]
            # Every matching edge, not the first: a claim pair can carry
            # several edges (different mechanisms), and marking one of them
            # leaves the cycle intact — which is what made the graph read break
            # the same cycles again on every single request.
            result = await self.session.execute(
                select(CausalEdge).where(
                    and_(
                        CausalEdge.source_claim_id == source_uuid,
                        CausalEdge.target_claim_id == target_uuid,
                    )
                )
            )
            for db_edge in result.scalars().all():
                db_edge.is_feedback = True
                marked += 1

        if marked > 0:
            # Committed rather than flushed: this is the result of cycle
            # detection, and losing it means every later read of the graph
            # recomputes it — hundreds of log lines and a layout that never
            # settles because the edge set differs between requests.
            await self.session.commit()
        logger.info(
            "Marked %d feedback edge(s) from %d cycle break(s)",
            marked, len(feedback_edges),
        )

    async def _save_usage(self, project_id: uuid.UUID, ledger) -> None:
        """Persist what the run cost.

        Failures here are logged and swallowed: accounting must never be the
        reason an otherwise complete analysis is reported as failed.
        """
        try:
            summary = ledger.as_dict()
            self.session.add(AnalysisUsage(
                project_id=project_id,
                calls=summary["calls"],
                input_tokens=summary["input_tokens"],
                output_tokens=summary["output_tokens"],
                cost_usd=summary["cost_usd"],
                unpriced_calls=summary["unpriced_calls"],
                price_table_date=summary["price_table_date"],
                by_stage=summary["by_stage"],
            ))
            await self.session.commit()
        except Exception as exc:
            logger.warning("Could not record usage for %s: %s", project_id, exc)

    async def _update_project_status(
        self,
        project_id: uuid.UUID,
        status: str,
    ) -> None:
        """Update the project's status field.

        Args:
            project_id: The project UUID.
            status: The new status string.
        """
        try:
            project = await self.session.get(Project, project_id)
            if project is not None:
                project.status = status
                await self.session.flush()
        except Exception as exc:
            # The session is poisoned by whatever failed before this, so the
            # status write cannot land and every later statement would report
            # the same stale error instead of its own.
            #
            # Rolling back here is what lets the caller mark the project failed
            # and, more importantly, lets it be resumed: the stages already
            # committed are still there, so a resume picks up from the last
            # checkpoint rather than re-running twenty minutes of extraction.
            logger.warning("Could not update project status: %s", exc)
            try:
                await self.session.rollback()
                project = await self.session.get(Project, project_id)
                if project is not None:
                    project.status = status
                    await self.session.flush()
                    await self.session.commit()
                    logger.info("Project status set to '%s' after rollback", status)
            except Exception as retry_exc:
                logger.error(
                    "Project status could not be recorded even after rollback: %s",
                    retry_exc,
                )


def _lightweight_claims(
    claims: list[dict[str, Any]], start_index: int = 0,
) -> list[dict[str, Any]]:
    """Strip embeddings and other heavy fields for SSE transmission."""
    return [
        {
            "id": c.get("id", f"claim-{start_index + i}"),
            "text": c.get("text", ""),
            "claim_type": c.get("type", "OPINION"),
            "confidence": c.get("confidence", 0.5),
            "layer": c.get("layer", 0),
        }
        for i, c in enumerate(claims)
    ]


def _lightweight_edge(edge: dict[str, Any], claims: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Strip heavy fields from edge for SSE."""
    source_text = edge.get("source_text", "")
    target_text = edge.get("target_text", "")
    # Resolve from claim indices if text not directly on the edge
    if claims and not source_text:
        src_idx = edge.get("source_idx")
        tgt_idx = edge.get("target_idx")
        if src_idx is not None and src_idx < len(claims):
            source_text = claims[src_idx].get("text", "")
        if tgt_idx is not None and tgt_idx < len(claims):
            target_text = claims[tgt_idx].get("text", "")
    e: dict[str, Any] = {
        "source_text": source_text,
        "target_text": target_text,
        "mechanism": edge.get("mechanism", ""),
        "strength": edge.get("strength", 0),
        "causal_type": edge.get("causal_type", "direct"),
    }
    if "evidence_score" in edge:
        e["evidence_score"] = edge["evidence_score"]
    if "evidences" in edge:
        e["evidences"] = [
            {
                "evidence_type": ev.get("evidence_type"),
                "source_title": ev.get("source_title", ""),
                "source_url": ev.get("source_url", ""),
                "snippet": ev.get("snippet", "")[:200],
                "relevance_score": ev.get("relevance_score", 0),
            }
            for ev in edge.get("evidences", [])
        ]
    if "bias_warnings" in edge:
        e["bias_warnings"] = edge["bias_warnings"]
    return e


def _lightweight_edges(claims: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prepare all edges for SSE with source/target text resolved."""
    claim_map = {i: c.get("text", "") for i, c in enumerate(claims)}
    result = []
    for edge in edges:
        e = _lightweight_edge(edge)
        # Resolve source/target from indices if text not already set
        if not e.get("source_text"):
            src_idx = edge.get("source_idx")
            tgt_idx = edge.get("target_idx")
            if src_idx is not None:
                e["source_text"] = claim_map.get(src_idx, "")
            if tgt_idx is not None:
                e["target_text"] = claim_map.get(tgt_idx, "")
        result.append(e)
    return result
