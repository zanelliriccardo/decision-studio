/**
 * The decision workspace: assumptions, timeline, scenarios and sub-decisions.
 * All read the reviewed graph and the existing option comparison; nothing here
 * calls a model. See docs/DECISION_VIEW.md.
 */
import { apiDelete, apiGet, apiPut } from './client.ts'
import type { QualityLabel } from '../../components/evidence/QualityChips.tsx'

const base = (projectId: string) => `/api/v1/graph/${projectId}`

// --- Assumption register ---

export interface AssumptionRow {
  claimId: string
  text: string
  decisionRole: string | null
  /** Current belief on the reviewed graph — not a conviction, not an outcome. */
  belief: number | null
  uncertainty: number
  options: string[]
  outcomes: string[]
  evidence: { count: number; supporting: number; contradicting: number; labels: QualityLabel[] }
  needsEvidence: boolean
  stale: boolean
  staleTheories: string[]
  driverRank: number | null
  impact: number
  canAlter: boolean
  flip: string
  affects: 'comparison' | 'all_options' | null
  influenceBasis: 'comparison' | 'relevance'
  priority: number
}

export interface AssumptionRegister {
  assumptions: AssumptionRow[]
  total: number
  influenceBasis: 'comparison' | 'relevance'
}

type Raw = Record<string, unknown>

export async function fetchAssumptions(projectId: string): Promise<AssumptionRegister> {
  const res = await apiGet<{ assumptions: Raw[]; total: number; influence_basis: AssumptionRegister['influenceBasis'] }>(
    `${base(projectId)}/assumptions`,
  )
  return {
    total: res.total,
    influenceBasis: res.influence_basis,
    assumptions: res.assumptions.map((a) => ({
      claimId: a.claim_id as string,
      text: a.text as string,
      decisionRole: (a.decision_role as string) ?? null,
      belief: (a.belief as number) ?? null,
      uncertainty: a.uncertainty as number,
      options: (a.options as string[]) ?? [],
      outcomes: (a.outcomes as string[]) ?? [],
      evidence: a.evidence as AssumptionRow['evidence'],
      needsEvidence: Boolean(a.needs_evidence),
      stale: Boolean(a.stale),
      staleTheories: (a.stale_theories as string[]) ?? [],
      driverRank: (a.driver_rank as number) ?? null,
      impact: a.impact as number,
      canAlter: Boolean(a.can_alter),
      flip: a.flip as string,
      affects: (a.affects as AssumptionRow['affects']) ?? null,
      influenceBasis: a.influence_basis as AssumptionRow['influenceBasis'],
      priority: a.priority as number,
    })),
  }
}

// --- Timeline ---

export interface TimelineEvent {
  at: string
  kind: string
  title: string
  detail: string | null
  /** What the event moved: a conviction, a strength, the comparison. */
  beliefChange: string | null
  material: boolean
}

export interface Timeline {
  events: TimelineEvent[]
  total: number
  material: number
}

export async function fetchTimeline(projectId: string): Promise<Timeline> {
  const res = await apiGet<{ events: Raw[]; total: number; material: number }>(`${base(projectId)}/timeline`)
  return {
    total: res.total,
    material: res.material,
    events: res.events.map((e) => ({
      at: e.at as string,
      kind: e.kind as string,
      title: e.title as string,
      detail: (e.detail as string) ?? null,
      beliefChange: (e.belief_change as string) ?? null,
      material: Boolean(e.material),
    })),
  }
}

// --- Scenarios ---

export interface ScenarioAssumption {
  kind: 'link' | 'claim'
  id: string
  label: string
  base: number
  value: number
}

export interface ScenarioCase {
  key: 'base' | 'upside' | 'downside'
  label: string
  source: 'base' | 'automatic' | 'user'
  assumptions: ScenarioAssumption[]
  options: {
    key: string
    label: string
    outcomes: Record<string, { point: number; p10: number; p90: number }>
    weighted: number | null
  }[]
  headline: { higher: string | null; verdict: string; share: number } | null
  unavailable: string | null
}

export interface Scenarios {
  outcomes: { key: string; label: string }[]
  cases: ScenarioCase[]
  unavailable: string | null
}

export async function fetchScenarios(projectId: string): Promise<Scenarios> {
  return apiGet<Scenarios>(`${base(projectId)}/decision-scenarios`)
}

export async function saveScenario(
  projectId: string,
  kase: 'upside' | 'downside',
  assumptions: { kind: 'link' | 'claim'; id: string; value: number }[],
): Promise<Scenarios> {
  return apiPut<Scenarios>(`${base(projectId)}/decision-scenarios/${kase}`, { assumptions })
}

export async function resetScenario(projectId: string, kase: 'upside' | 'downside'): Promise<Scenarios> {
  return apiDelete<Scenarios>(`${base(projectId)}/decision-scenarios/${kase}`)
}

// --- Sub-decisions ---

export interface SubDecisionChoice {
  key: string
  label: string
  claims: { id: string; text: string }[]
  reachesOutcome: boolean
  outcomes: Record<string, { point: number; p10: number; p90: number }>
  weighted: number | null
}

export interface SubDecision {
  key: string
  parent: string
  parentLabel: string
  label: string
  outcomes: { key: string; label: string }[]
  choices: SubDecisionChoice[]
  spread: number | null
  verdict: { verdict: string; higher: string | null; share: number; difference: number } | null
  sentence: string | null
  unavailable: string | null
}

export interface SubDecisionInput {
  parent: string
  label: string
  choices: { label: string; claim_ids: string[] }[]
}

function toSubDecisions(res: { sub_decisions: Raw[] }): SubDecision[] {
  return res.sub_decisions.map((s) => ({
    key: s.key as string,
    parent: s.parent as string,
    parentLabel: (s.parent_label as string) ?? '',
    label: s.label as string,
    outcomes: (s.outcomes as SubDecision['outcomes']) ?? [],
    choices: ((s.choices as Raw[]) ?? []).map((c) => ({
      key: c.key as string,
      label: c.label as string,
      claims: (c.claims as SubDecisionChoice['claims']) ?? [],
      reachesOutcome: Boolean(c.reaches_outcome),
      outcomes: (c.outcomes as SubDecisionChoice['outcomes']) ?? {},
      weighted: (c.weighted as number) ?? null,
    })),
    spread: (s.spread as number) ?? null,
    verdict: (s.verdict as SubDecision['verdict']) ?? null,
    sentence: (s.sentence as string) ?? null,
    unavailable: (s.unavailable as string) ?? null,
  }))
}

export async function fetchSubDecisions(projectId: string): Promise<SubDecision[]> {
  return toSubDecisions(await apiGet<{ sub_decisions: Raw[] }>(`${base(projectId)}/sub-decisions`))
}

export async function saveSubDecisions(projectId: string, items: SubDecisionInput[]): Promise<SubDecision[]> {
  return toSubDecisions(await apiPut<{ sub_decisions: Raw[] }>(`${base(projectId)}/sub-decisions`, { sub_decisions: items }))
}
