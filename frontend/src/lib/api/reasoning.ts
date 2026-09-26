/**
 * API client for the decision-reasoning endpoints.
 *
 * All transformation between the backend's snake_case wire format and the
 * app's camelCase types happens here, so components never see raw API shapes.
 */

import { apiGet, apiPatch, apiPost } from './client.ts'
import type {
  ApiChangeSummary,
  Debate,
  DebateRelation,
  DebateReport,
  ApiTheory,
  ChangeSummary,
  GraphOperationRecord,
  GraphRevisionInfo,
  ReviewPayload,
  ReviewResult,
  Theory,
  TheoryGenerationResult,
  TheoryRevisionInfo,
} from '../../types/reasoning.ts'

const base = (projectId: string) => `/api/v1/graph/${projectId}`

// --- Transformers ---

export function transformTheory(api: ApiTheory): Theory {
  return {
    id: api.id,
    projectId: api.project_id,
    theoryKey: api.theory_key,
    title: api.title,
    summary: api.summary,
    status: api.status,
    causalChain: (api.causal_chain ?? []).map((step) => ({
      claimId: step.claim_id ?? null,
      edgeId: step.edge_id ?? null,
      sourceClaimId: step.source_claim_id ?? null,
      targetClaimId: step.target_claim_id ?? null,
      label: step.label ?? null,
      // A link was dropped here for not joining its neighbours. Drawn as a
      // break: a broken chain rendered as continuous is the bug the whole
      // connectivity check exists to stop.
      gapBefore: step.gap_before ?? false,
    })),
    connectedLinks: api.connected_links ?? 0,
    citedLinks: api.cited_links ?? 0,
    supportingClaimIds: api.supporting_claim_ids ?? [],
    supportingEdgeIds: api.supporting_edge_ids ?? [],
    supportingEvidenceIds: api.supporting_evidence_ids ?? [],
    contradictingEvidenceIds: api.contradicting_evidence_ids ?? [],
    weakAssumptions: api.weak_assumptions ?? [],
    confidence: api.confidence,
    businessImpact: api.business_impact,
    recommendation: api.recommendation ?? '',
    openQuestionIds: api.open_question_ids ?? [],
    graphRevision: api.graph_revision,
    theoryRevision: api.theory_revision,
    version: api.version,
    isCurrent: api.is_current,
    isStale: api.is_stale,
    staleReason: api.stale_reason,
    changeKind: api.change_kind,
    changeExplanation: api.change_explanation,
    createdAt: api.created_at,
    objectionLoad: api.objection_load ?? 0,
    contested: api.contested ?? false,
    adjustedScore: api.adjusted_score ?? null,
    confidenceBand: api.confidence_band ?? 'unknown',
    outsideViewDelta: api.outside_view_delta ?? null,
    outsideViewNote: api.outside_view_note ?? null,
    optionKey: api.option_key ?? null,
    predictedEffect: api.predicted_effect ?? null,
    outcomeKeys: api.outcome_keys ?? [],
    reachesOutcome: api.reaches_outcome ?? false,
    conviction: api.conviction ?? null,
    convictionPrior: api.conviction_prior ?? null,
    objections: (api.objections ?? []).map((o) => ({ ...o })),
    tripwires: (api.tripwires ?? []).map((tw) => ({
      id: tw.id,
      observable: tw.observable,
      direction: tw.direction,
      horizonDays: tw.horizon_days,
      checkBy: tw.check_by,
      status: tw.status,
      observedAt: tw.observed_at,
      observedNote: tw.observed_note,
    })),
  }
}











// --- Manual authoring ---

export interface RecomputePlan {
  newClaimIds: string[]
  newEdgeIds: string[]
  needsCausalInference: boolean
  needsEvidenceGrounding: boolean
  estimatedLlmCalls: number
  skipped: string[]
}

function transformPlan(api: {
  new_claim_ids?: string[]
  new_edge_ids?: string[]
  needs_causal_inference?: boolean
  needs_evidence_grounding?: boolean
  estimated_llm_calls?: number
  skipped?: string[]
}): RecomputePlan {
  return {
    newClaimIds: api.new_claim_ids ?? [],
    newEdgeIds: api.new_edge_ids ?? [],
    needsCausalInference: api.needs_causal_inference ?? false,
    needsEvidenceGrounding: api.needs_evidence_grounding ?? false,
    estimatedLlmCalls: api.estimated_llm_calls ?? 0,
    skipped: api.skipped ?? [],
  }
}

export async function addEdge(
  projectId: string,
  sourceClaimId: string,
  targetClaimId: string,
  mechanism: string,
  effect = 0.5,
  linkConfidence = 0.5,
): Promise<{ elementId: string; graphRevision: number; plan: RecomputePlan }> {
  const res = await apiPost<{
    element_id: string
    graph_revision: number
    plan: Parameters<typeof transformPlan>[0]
  }>(`${base(projectId)}/edges`, {
    source_claim_id: sourceClaimId,
    target_claim_id: targetClaimId,
    mechanism,
    effect,
    link_confidence: linkConfidence,
  })
  return {
    elementId: res.element_id,
    graphRevision: res.graph_revision,
    plan: transformPlan(res.plan),
  }
}

export async function addClaim(
  projectId: string,
  text: string,
  claimType = 'ASSUMPTION',
): Promise<{ elementId: string; graphRevision: number; plan: RecomputePlan }> {
  const res = await apiPost<{
    element_id: string
    graph_revision: number
    plan: Parameters<typeof transformPlan>[0]
  }>(`${base(projectId)}/claims`, { text, claim_type: claimType })
  return {
    elementId: res.element_id,
    graphRevision: res.graph_revision,
    plan: transformPlan(res.plan),
  }
}

/** Infer links between new claims and the existing graph. Costs LLM calls. */
export async function inferLinks(
  projectId: string,
  claimIds: string[],
): Promise<{ newEdgeIds: string[] }> {
  const res = await apiPost<{ new_edge_ids: string[] }>(
    `${base(projectId)}/infer-links`,
    claimIds,
  )
  return { newEdgeIds: res.new_edge_ids ?? [] }
}

/** Rebuild the DAG and re-propagate. Pure computation — no LLM. */
export async function recompute(projectId: string): Promise<void> {
  await apiPost(`${base(projectId)}/recompute`, {})
}

// --- Theory debate ---

interface ApiDebate {
  id: string
  theory_a_id: string
  theory_b_id: string
  overlap_jaccard: number
  relation: DebateRelation
  shared_claim_ids: string[]
  shared_edge_ids: string[]
  divergent_claim_ids: string[]
  divergent_edge_ids: string[]
  crux: string | null
  discriminator: string | null
  discriminator_feasible: boolean
  discriminator_horizon_days: number | null
  evidence_favours: 'a' | 'b' | 'neither' | null
  both_possible: boolean
  is_stale: boolean
  promoted_tripwire_at: string | null
  created_at: string | null
}

export function transformDebate(api: ApiDebate): Debate {
  return {
    id: api.id,
    theoryAId: api.theory_a_id,
    theoryBId: api.theory_b_id,
    overlapJaccard: api.overlap_jaccard,
    relation: api.relation,
    sharedClaimIds: api.shared_claim_ids ?? [],
    sharedEdgeIds: api.shared_edge_ids ?? [],
    divergentClaimIds: api.divergent_claim_ids ?? [],
    divergentEdgeIds: api.divergent_edge_ids ?? [],
    crux: api.crux,
    discriminator: api.discriminator,
    discriminatorFeasible: api.discriminator_feasible,
    discriminatorHorizonDays: api.discriminator_horizon_days,
    evidenceFavours: api.evidence_favours,
    bothPossible: api.both_possible,
    isStale: api.is_stale,
    promotedTripwireAt: api.promoted_tripwire_at,
    createdAt: api.created_at,
  }
}

export async function fetchDebates(projectId: string): Promise<Debate[]> {
  const res = await apiGet<{ debates: ApiDebate[] }>(`${base(projectId)}/debates`)
  return (res.debates ?? []).map(transformDebate)
}

export async function runDebates(projectId: string): Promise<DebateReport> {
  const res = await apiPost<{
    pairs: number
    same_story: number
    competing: number
    orthogonal: number
    model_calls: number
    with_discriminator: number
  }>(`${base(projectId)}/debates`, {})
  return {
    pairs: res.pairs ?? 0,
    sameStory: res.same_story ?? 0,
    competing: res.competing ?? 0,
    orthogonal: res.orthogonal ?? 0,
    modelCalls: res.model_calls ?? 0,
    withDiscriminator: res.with_discriminator ?? 0,
  }
}

export async function promoteDiscriminator(
  projectId: string,
  debateId: string,
): Promise<void> {
  await apiPost(`${base(projectId)}/debates/${debateId}/tripwire`, {})
}





// --- Adversarial review and tripwires ---

export async function challengeTheories(
  projectId: string,
): Promise<{ theories: number; objections: number; contested: number }> {
  return apiPost(`${base(projectId)}/theories/challenge`, {})
}

export async function generateTripwires(
  projectId: string,
): Promise<{ theories: number; tripwires: number }> {
  return apiPost(`${base(projectId)}/theories/tripwires`, {})
}

export async function observeTripwire(
  projectId: string,
  tripwireId: string,
  observed: boolean,
  note?: string,
): Promise<void> {
  await apiPost(`${base(projectId)}/tripwires/${tripwireId}/observe`, {
    observed,
    note,
  })
}

export async function dismissObjection(
  projectId: string,
  objectionId: string,
): Promise<void> {
  await apiPatch(`${base(projectId)}/objections/${objectionId}/dismiss`, {})
}


function transformChangeSummary(api: ApiChangeSummary | null): ChangeSummary {
  return {
    newTheoryIds: api?.new_theory_ids ?? [],
    changedTheoryIds: api?.changed_theory_ids ?? [],
    unchangedTheoryIds: api?.unchanged_theory_ids ?? [],
    supersededTheoryIds: api?.superseded_theory_ids ?? [],
  }
}

// --- Theories ---

export async function fetchTheories(projectId: string): Promise<{
  theories: Theory[]
  graphRevision: number
  staleCount: number
}> {
  const res = await apiGet<{
    theories: ApiTheory[]
    graph_revision: number
    stale_count: number
  }>(`${base(projectId)}/theories`)
  return {
    theories: (res.theories ?? []).map(transformTheory),
    graphRevision: res.graph_revision,
    staleCount: res.stale_count ?? 0,
  }
}

async function runGeneration(
  projectId: string,
  action: 'generate' | 'regenerate',
): Promise<TheoryGenerationResult> {
  const res = await apiPost<{
    graph_revision: number
    theory_revision: number
    theories: ApiTheory[]
    change_summary: ApiChangeSummary
    validation: Record<string, unknown>
  }>(`${base(projectId)}/theories/${action}`, {})
  return {
    graphRevision: res.graph_revision,
    theoryRevision: res.theory_revision,
    theories: (res.theories ?? []).map(transformTheory),
    changeSummary: transformChangeSummary(res.change_summary),
    validation: res.validation ?? {},
  }
}

export const generateTheories = (projectId: string) =>
  runGeneration(projectId, 'generate')

export const regenerateTheories = (projectId: string) =>
  runGeneration(projectId, 'regenerate')

export async function fetchTheoryVersions(
  projectId: string,
  theoryId: string,
): Promise<Theory[]> {
  const res = await apiGet<{ versions: ApiTheory[] }>(
    `${base(projectId)}/theories/${theoryId}/versions`,
  )
  return (res.versions ?? []).map(transformTheory)
}

export async function fetchTheoryRevisions(
  projectId: string,
): Promise<TheoryRevisionInfo[]> {
  const res = await apiGet<{
    revisions: Array<{
      id: string
      revision: number
      graph_revision: number
      trigger: string
      change_summary: ApiChangeSummary | null
      created_at: string | null
    }>
  }>(`${base(projectId)}/theory-revisions`)
  return (res.revisions ?? []).map((r) => ({
    id: r.id,
    revision: r.revision,
    graphRevision: r.graph_revision,
    trigger: r.trigger,
    changeSummary: r.change_summary ? transformChangeSummary(r.change_summary) : null,
    createdAt: r.created_at,
  }))
}

// --- Graph review ---

interface ApiReviewResult {
  element: {
    id: string
    target_type: 'claim' | 'edge'
    review_status: ReviewResult['element']['reviewStatus']
    is_active: boolean
    user_note: string | null
    strength_override: number | null
    reviewed_at: string | null
  }
  operation: ApiGraphOperation
  graph_revision: number
  stale_theory_count: number
}

interface ApiGraphOperation {
  id: string
  operation_type: string
  target_type: 'claim' | 'edge'
  claim_id: string | null
  edge_id: string | null
  revision_before: number
  revision_after: number
  source: string
  note: string | null
  undone_at: string | null
  created_at: string | null
}

function transformOperation(api: ApiGraphOperation): GraphOperationRecord {
  return {
    id: api.id,
    operationType: api.operation_type,
    targetType: api.target_type,
    claimId: api.claim_id,
    edgeId: api.edge_id,
    revisionBefore: api.revision_before,
    revisionAfter: api.revision_after,
    source: api.source,
    note: api.note,
    undoneAt: api.undone_at,
    createdAt: api.created_at,
  }
}

function transformReviewResult(api: ApiReviewResult): ReviewResult {
  return {
    element: {
      id: api.element.id,
      targetType: api.element.target_type,
      reviewStatus: api.element.review_status,
      isActive: api.element.is_active,
      userNote: api.element.user_note,
      strengthOverride: api.element.strength_override,
      reviewedAt: api.element.reviewed_at,
    },
    operation: transformOperation(api.operation),
    graphRevision: api.graph_revision,
    staleTheoryCount: api.stale_theory_count,
  }
}

export async function reviewClaim(
  projectId: string,
  claimId: string,
  payload: ReviewPayload,
): Promise<ReviewResult> {
  const res = await apiPatch<ApiReviewResult>(
    `${base(projectId)}/claims/${claimId}/review`,
    payload,
  )
  return transformReviewResult(res)
}

export async function reviewEdge(
  projectId: string,
  edgeId: string,
  payload: ReviewPayload,
): Promise<ReviewResult> {
  const res = await apiPatch<ApiReviewResult>(
    `${base(projectId)}/edges/${edgeId}/review`,
    payload,
  )
  return transformReviewResult(res)
}

export async function fetchGraphOperations(
  projectId: string,
): Promise<GraphOperationRecord[]> {
  const res = await apiGet<{ operations: ApiGraphOperation[] }>(
    `${base(projectId)}/graph-operations`,
  )
  return (res.operations ?? []).map(transformOperation)
}

export async function undoGraphOperation(
  projectId: string,
  operationId: string,
): Promise<ReviewResult> {
  const res = await apiPost<ApiReviewResult>(
    `${base(projectId)}/graph-operations/${operationId}/undo`,
    {},
  )
  return transformReviewResult(res)
}

export async function fetchGraphRevision(
  projectId: string,
): Promise<GraphRevisionInfo> {
  const res = await apiGet<{
    project_id: string
    graph_revision: number
    active_claim_count: number
    active_edge_count: number
    total_claim_count: number
    total_edge_count: number
    decision_objective: string | null
  }>(`${base(projectId)}/graph-revision`)
  return {
    projectId: res.project_id,
    graphRevision: res.graph_revision,
    activeClaimCount: res.active_claim_count,
    activeEdgeCount: res.active_edge_count,
    totalClaimCount: res.total_claim_count,
    totalEdgeCount: res.total_edge_count,
    decisionObjective: res.decision_objective,
  }
}

export async function setDecisionObjective(
  projectId: string,
  objective: string,
): Promise<GraphRevisionInfo> {
  await apiPatch(`${base(projectId)}/decision-objective`, {
    decision_objective: objective,
  })
  return fetchGraphRevision(projectId)
}

// --- The recommendation ---

export interface Recommendation {
  recommendation: string
  reasoning: string
  dependsOn: string[]
  againstIt: string | null
  nextStep: string | null
  confidence: 'low' | 'moderate' | 'high'
  /** The theories were regenerated after this was written. */
  isStale: boolean
}

/** Null when none has been generated — a 404 here is a state, not a fault. */
export async function fetchRecommendation(
  projectId: string,
): Promise<Recommendation | null> {
  try {
    const res = await apiGet<{
      recommendation: string
      reasoning: string
      depends_on: string[]
      against_it: string | null
      next_step: string | null
      confidence: Recommendation['confidence']
      is_stale: boolean
    }>(`${base(projectId)}/recommendation`)
    return {
      recommendation: res.recommendation,
      reasoning: res.reasoning ?? '',
      dependsOn: res.depends_on ?? [],
      againstIt: res.against_it,
      nextStep: res.next_step,
      confidence: res.confidence ?? 'moderate',
      isStale: res.is_stale ?? false,
    }
  } catch {
    return null
  }
}

export async function generateRecommendation(
  projectId: string,
): Promise<Recommendation | null> {
  await apiPost(`${base(projectId)}/recommendation`, {})
  return fetchRecommendation(projectId)
}

// --- Token and cost accounting ---

export interface StageUsage {
  calls: number
  total_tokens: number
  cost_usd: number
}

export interface AnalysisUsage {
  totalCostUsd: number
  totalTokens: number
  runs: {
    calls: number
    input_tokens: number
    output_tokens: number
    total_tokens: number
    cost_usd: number
    unpriced_calls: number
    price_table_date: string | null
    by_stage: Record<string, StageUsage>
  }[]
}

/** Null when nothing was recorded — a project analysed before this existed. */
export async function fetchUsage(projectId: string): Promise<AnalysisUsage | null> {
  try {
    const res = await apiGet<{
      runs: AnalysisUsage['runs']
      total_cost_usd: number
      total_tokens: number
    }>(`${base(projectId)}/usage`)
    if (!res.runs?.length) return null
    return {
      totalCostUsd: res.total_cost_usd ?? 0,
      totalTokens: res.total_tokens ?? 0,
      runs: res.runs,
    }
  } catch {
    return null
  }
}
