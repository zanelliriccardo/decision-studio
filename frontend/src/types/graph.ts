export type ClaimType = 'FACT' | 'ASSUMPTION' | 'PREDICTION' | 'OPINION'
export type LogicGate = 'or' | 'and'
export type CausalType = 'direct' | 'indirect' | 'probabilistic' | 'enabling' | 'inhibiting' | 'triggering'
export type ConditionType = 'sufficient' | 'necessary' | 'contributing'
export type BiasSeverity = 'low' | 'medium' | 'high'

export type { ReviewStatus } from './reasoning.ts'
import type { ReviewStatus } from './reasoning.ts'

export interface BiasWarning {
  type: string
  explanation: string
  severity: BiasSeverity
}

export interface CausalNode {
  id: string
  text: string
  claimType: ClaimType
  confidence: number
  belief: number | null
  sensitivity: number | null
  isCriticalPath: boolean
  isConvergencePoint?: boolean
  logicGate: LogicGate
  orderIndex: number
  sourceSentence: string | null
  beliefLow: number | null
  beliefHigh: number | null
  // Human review state
  reviewStatus: ReviewStatus
  isActive: boolean
  userNote: string | null
  /** How firmly the SOURCE asserts this. A property of the text, not the world. */
  confidence_isAssertion?: never
  /** Probability the claim is actually true. What propagation is seeded with. */
  prior: number
  /** Source sentences of duplicate claims merged into this one. */
  corroboratedBy: string[] | null
  duplicateCount: number
  // Layout computed
  x?: number
  y?: number
  depth?: number
  collapsed?: boolean
}

export interface CausalEdge {
  id: string
  sourceId: string
  targetId: string
  mechanism: string
  strength: number
  timeDelay: string | null
  conditions: string[] | null
  reversible: boolean
  evidenceScore: number
  causalType: CausalType
  conditionType: ConditionType
  temporalWindow: string | null
  decayType: string
  biasWarnings: BiasWarning[]
  consensusLevel: string
  sensitivity: number | null
  isFeedback: boolean
  evidences: Evidence[]
  // Human review state
  reviewStatus: ReviewStatus
  isActive: boolean
  userNote: string | null
  strengthOverride: number | null
  /** strengthOverride when set, otherwise strength. */
  effectiveStrength: number
  /** Size of the effect if the link is real. */
  effect: number
  /** Certainty the link exists at all. `strength` is effect x this. */
  linkConfidence: number
  /** What the proposing call scored, before blind re-scoring. */
  authorEffect: number | null
  authorConfidence: number | null
  blindScored: boolean
  /** author weight minus blind weight; positive means the author over-scored. */
  inflation: number | null
}

export interface Evidence {
  id: string
  evidenceType: 'supporting' | 'contradicting'
  sourceUrl: string
  sourceTitle: string
  sourceType: string
  snippet: string
  relevanceScore: number
  credibilityScore: number
  sourceTier: number
}


export interface CausalGraph {
  projectId: string
  nodes: CausalNode[]
  edges: CausalEdge[]
  criticalPath: string[]
  hasTemporal: boolean
  graphRevision: number
  decisionObjective: string | null
}

export interface BeliefChange {
  oldBelief: number
  newBelief: number
  delta: number
}

export interface PathInfo {
  path: string[]
  compoundProbability: number
}

export interface TemporalBeliefSample {
  time: number    // days from origin
  belief: number  // 0..1
}

export type ViewMode = 'panorama' | 'focus' | 'compare' | 'timeline'
