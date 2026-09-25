/**
 * Decision-reasoning types.
 *
 * `Api*` interfaces mirror the backend's snake_case wire format; the plain
 * interfaces are the camelCase shapes used inside the app. Transformers live in
 * `lib/api/reasoning.ts`.
 */

export type ReviewStatus =
  | 'accepted'
  | 'rejected'
  | 'uncertain'
  | 'business_critical'
  | 'not_relevant'
  | 'needs_evidence'

export type TheoryStatus =
  | 'hypothesis'
  | 'supported'
  | 'contested'
  | 'insufficient_evidence'
  | 'superseded'

export type BusinessImpact = 'low' | 'medium' | 'high' | 'critical'

export type AnswerType =
  | 'free_text'
  | 'single_choice'
  | 'multi_choice'
  | 'yes_no'
  | 'number'
  | 'date'

export type QuestionStatus = 'open' | 'answered' | 'dismissed' | 'skipped'

export type ChangeKind = 'new' | 'changed' | 'unchanged' | 'superseded'

/** Verbal bands. The decimals were never calibrated, so they are not shown. */
export type ConfidenceBand =
  | 'unknown' | 'very_low' | 'low' | 'moderate' | 'high' | 'very_high'

export type ObjectionKind =
  | 'common_cause' | 'single_source' | 'reversal'
  | 'scope' | 'timing' | 'incentive' | 'other'

export interface Objection {
  id: string
  objection: string
  kind: ObjectionKind
  severity: number
  dismissed: boolean
}

export interface Tripwire {
  id: string
  observable: string
  direction: 'falsifies' | 'confirms'
  horizonDays: number
  checkBy: string | null
  status: 'pending' | 'observed' | 'not_observed' | 'expired'
  observedAt: string | null
  observedNote: string | null
}

/** One question from the framing questionnaire. */

/** The answers that hold across analyses. */


/** One hop of a theory's causal chain: a claim node or a causal edge. */
export interface CausalChainStep {
  /** A link was dropped here for not joining its neighbours. */
  gapBefore?: boolean
  claimId?: string | null
  edgeId?: string | null
  sourceClaimId?: string | null
  targetClaimId?: string | null
  label?: string | null
}

export interface Theory {
  id: string
  projectId: string
  theoryKey: string
  title: string
  summary: string
  status: TheoryStatus
  causalChain: CausalChainStep[]
  /** Chain links whose endpoints match their neighbours, over links cited.
      Shown rather than folded into the score. */
  connectedLinks: number
  citedLinks: number
  supportingClaimIds: string[]
  supportingEdgeIds: string[]
  supportingEvidenceIds: string[]
  contradictingEvidenceIds: string[]
  weakAssumptions: string[]
  confidence: number
  businessImpact: BusinessImpact
  recommendation: string
  openQuestionIds: string[]
  graphRevision: number
  theoryRevision: number
  version: number
  isCurrent: boolean
  isStale: boolean
  staleReason: string | null
  changeKind: ChangeKind | null
  changeExplanation: string | null
  createdAt: string | null
  /** Mean severity of live objections, 0-1. */
  objectionLoad: number
  contested: boolean
  /** Confidence discounted by objectionLoad. This is what ordering uses. */
  adjustedScore: number | null
  objections: Objection[]
  tripwires: Tripwire[]
  confidenceBand: ConfidenceBand
  /** confidence minus the base rate of the matching reference class. */
  outsideViewDelta: number | null
  outsideViewNote: string | null
}

/** How two theories relate, computed from the graph rather than judged. */
export type DebateRelation = 'same_story' | 'competing' | 'orthogonal'

export interface Debate {
  id: string
  theoryAId: string
  theoryBId: string
  /** Overlap of the two supporting EDGE sets. Claims overlap by construction. */
  overlapJaccard: number
  relation: DebateRelation
  sharedClaimIds: string[]
  sharedEdgeIds: string[]
  divergentClaimIds: string[]
  divergentEdgeIds: string[]
  crux: string | null
  /** An observation whose outcome differs by theory. Already tripwire-shaped. */
  discriminator: string | null
  discriminatorFeasible: boolean
  discriminatorHorizonDays: number | null
  evidenceFavours: 'a' | 'b' | 'neither' | null
  /** The two are not mutually exclusive — a ranked list hides this. */
  bothPossible: boolean
  isStale: boolean
  promotedTripwireAt: string | null
  createdAt: string | null
}

export interface DebateReport {
  pairs: number
  sameStory: number
  competing: number
  orthogonal: number
  /** Fewer than `pairs`: same-story pairs never reach the model. */
  modelCalls: number
  withDiscriminator: number
}

/** A base rate drawn from the user's own experience of comparable cases. */


export interface ChangeSummary {
  newTheoryIds: string[]
  changedTheoryIds: string[]
  unchangedTheoryIds: string[]
  supersededTheoryIds: string[]
}

export interface TheoryGenerationResult {
  graphRevision: number
  theoryRevision: number
  theories: Theory[]
  changeSummary: ChangeSummary
  validation: Record<string, unknown>
}

export interface TheoryRevisionInfo {
  id: string
  revision: number
  graphRevision: number
  trigger: string
  changeSummary: ChangeSummary | null
  createdAt: string | null
}

export interface GraphOperationRecord {
  id: string
  operationType: string
  targetType: 'claim' | 'edge'
  claimId: string | null
  edgeId: string | null
  revisionBefore: number
  revisionAfter: number
  source: string
  note: string | null
  undoneAt: string | null
  createdAt: string | null
}

export interface ReviewState {
  id: string
  targetType: 'claim' | 'edge'
  reviewStatus: ReviewStatus
  isActive: boolean
  userNote: string | null
  strengthOverride: number | null
  reviewedAt: string | null
}

export interface ReviewResult {
  element: ReviewState
  operation: GraphOperationRecord
  graphRevision: number
  staleTheoryCount: number
}

export interface GraphRevisionInfo {
  projectId: string
  graphRevision: number
  activeClaimCount: number
  activeEdgeCount: number
  totalClaimCount: number
  totalEdgeCount: number
  decisionObjective: string | null
}



/** Payload for a review request; every field is optional. */
export interface ReviewPayload {
  review_status?: ReviewStatus
  is_active?: boolean
  user_note?: string
  strength_override?: number
  clear_strength_override?: boolean
  mechanism?: string
  note?: string
  expected_graph_revision?: number
}

// --- Wire formats ---

export interface ApiTheory {
  id: string
  project_id: string
  theory_key: string
  title: string
  summary: string
  status: TheoryStatus
  connected_links?: number
  cited_links?: number
  causal_chain: Array<{
    gap_before?: boolean
    claim_id?: string | null
    edge_id?: string | null
    source_claim_id?: string | null
    target_claim_id?: string | null
    label?: string | null
  }>
  supporting_claim_ids: string[]
  supporting_edge_ids: string[]
  supporting_evidence_ids: string[]
  contradicting_evidence_ids: string[]
  weak_assumptions: string[]
  confidence: number
  business_impact: BusinessImpact
  recommendation: string
  open_question_ids: string[]
  graph_revision: number
  theory_revision: number
  version: number
  is_current: boolean
  is_stale: boolean
  stale_reason: string | null
  change_kind: ChangeKind | null
  change_explanation: string | null
  created_at: string | null
  objection_load?: number
  contested?: boolean
  adjusted_score?: number | null
  confidence_band?: ConfidenceBand
  outside_view_delta?: number | null
  outside_view_note?: string | null
  objections?: Array<{
    id: string
    objection: string
    kind: ObjectionKind
    severity: number
    dismissed: boolean
  }>
  tripwires?: Array<{
    id: string
    observable: string
    direction: 'falsifies' | 'confirms'
    horizon_days: number
    check_by: string | null
    status: 'pending' | 'observed' | 'not_observed' | 'expired'
    observed_at: string | null
    observed_note: string | null
  }>
}

export interface ApiClarificationQuestion {
  id: string
  project_id: string
  question: string
  reason: string
  expected_information_gain: 'low' | 'medium' | 'high'
  priority: 'low' | 'medium' | 'high' | 'critical'
  answer_type: AnswerType
  options: string[] | null
  linked_theory_ids: string[]
  linked_claim_ids: string[]
  linked_edge_ids: string[]
  status: QuestionStatus
  answer?: unknown
  answer_note: string | null
  graph_revision: number
  answered_at: string | null
  applied_at: string | null
  created_at: string | null
}

export interface ApiChangeSummary {
  new_theory_ids: string[]
  changed_theory_ids: string[]
  unchanged_theory_ids: string[]
  superseded_theory_ids: string[]
}
