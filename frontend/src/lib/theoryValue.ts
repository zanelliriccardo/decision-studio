/**
 * Theories of value on the client: conviction elicitation, the evidence scale,
 * option coverage and the API for conviction, link hypotheses and field results.
 *
 * Conviction is the decider's belief that a theory holds — not the model's
 * confidence. It is elicited with lottery comparisons rather than a slider:
 * "how sure are you, 0 to 1" is the question known to produce bad numbers,
 * while "would you rather bet on this, or on a draw you win 70% of the time"
 * is one people answer consistently. Four answers bisect the interval to about
 * ±3%, which is finer than anyone's belief actually is.
 */

import { apiGet, apiPost } from './api/client.ts'
import type { DecisionAnchor } from '../types/graph.ts'
import type { Theory } from '../types/reasoning.ts'

// --- Lottery elicitation ---

export const LOTTERY_STEPS = 4

export type LotteryChoice = 'theory' | 'draw' | 'same'

export interface LotteryState {
  lo: number
  hi: number
  answers: Array<{ p: number; choice: LotteryChoice }>
  done: boolean
}

export const startLottery = (): LotteryState => ({ lo: 0, hi: 1, answers: [], done: false })

/** The draw's winning probability to offer next. */
export const lotteryProbe = (state: LotteryState): number =>
  Math.round(((state.lo + state.hi) / 2) * 100) / 100

export function answerLottery(state: LotteryState, choice: LotteryChoice): LotteryState {
  if (state.done) return state
  const p = lotteryProbe(state)
  const answers = [...state.answers, { p, choice }]
  if (choice === 'same') return { lo: p, hi: p, answers, done: true }
  // Preferring the bet on the theory means believing it more likely than p.
  const next = choice === 'theory' ? { lo: p, hi: state.hi } : { lo: state.lo, hi: p }
  return { ...next, answers, done: answers.length >= LOTTERY_STEPS }
}

/** The elicited conviction, never 0 or 1: certainty cannot be updated. */
export function lotteryEstimate(state: LotteryState): number {
  const mid = (state.lo + state.hi) / 2
  return Math.min(0.99, Math.max(0.01, Math.round(mid * 100) / 100))
}

/** A readable record of the answers, stored with the prior so it can be audited. */
export function describeLottery(state: LotteryState): string {
  return state.answers
    .map((a) => `${Math.round(a.p * 100)}%: ${a.choice === 'theory' ? 'theory' : a.choice === 'draw' ? 'draw' : 'same'}`)
    .join(', ')
}

// --- Evidence scale (mirrors reasoning/theory_value.py) ---

export const LIKELIHOOD_SCALE = {
  strongly_for: 4,
  for: 2,
  neutral: 1,
  against: 0.5,
  strongly_against: 0.25,
} as const

export type LikelihoodKey = keyof typeof LIKELIHOOD_SCALE

/** The verbal step nearest a likelihood ratio, for showing history. */
export function likelihoodKey(ratio: number): LikelihoodKey {
  let best: LikelihoodKey = 'neutral'
  for (const key of Object.keys(LIKELIHOOD_SCALE) as LikelihoodKey[]) {
    if (Math.abs(Math.log(LIKELIHOOD_SCALE[key]) - Math.log(ratio)) <
        Math.abs(Math.log(LIKELIHOOD_SCALE[best]) - Math.log(ratio))) best = key
  }
  return best
}

// --- Option coverage (mirrors theory_value.option_coverage) ---

export interface OptionCoverageRow {
  key: string
  label: string
  achieves: number
  threatens: number
  unclear: number
  reachingOutcome: number
}

export function optionCoverage(anchor: DecisionAnchor | null | undefined, theories: Theory[]): OptionCoverageRow[] {
  return (anchor?.options ?? []).map((option) => {
    const bound = theories.filter((t) => t.optionKey === option.key)
    return {
      key: option.key,
      label: option.label,
      achieves: bound.filter((t) => t.predictedEffect === 'achieves').length,
      threatens: bound.filter((t) => t.predictedEffect === 'threatens').length,
      unclear: bound.filter((t) => t.predictedEffect !== 'achieves' && t.predictedEffect !== 'threatens').length,
      reachingOutcome: bound.filter((t) => t.reachesOutcome).length,
    }
  })
}

// --- API ---

export interface ConvictionStep {
  id: string
  likelihoodRatio: number
  source: 'tripwire' | 'field_experiment' | 'link_hypothesis' | string
  note: string | null
  createdAt: string | null
  /** False when recorded before the latest prior: already reflected in it. */
  applied: boolean
  after: number | null
}

export interface Conviction {
  theoryKey: string
  prior: number | null
  priorMethod: string | null
  current: number | null
  steps: ConvictionStep[]
}

interface ApiConviction {
  theory_key: string
  prior: number | null
  prior_method: string | null
  current: number | null
  steps: Array<{
    id: string; likelihood_ratio: number; source: string; note: string | null
    created_at: string | null; applied: boolean; after: number | null
  }>
}

const toConviction = (api: ApiConviction): Conviction => ({
  theoryKey: api.theory_key,
  prior: api.prior,
  priorMethod: api.prior_method,
  current: api.current,
  steps: api.steps.map((s) => ({
    id: s.id, likelihoodRatio: s.likelihood_ratio, source: s.source, note: s.note,
    createdAt: s.created_at, applied: s.applied, after: s.after,
  })),
})

const convictionPath = (projectId: string, theoryKey: string) =>
  `/api/v1/graph/${projectId}/theory-keys/${theoryKey}/conviction`

export async function fetchConviction(projectId: string, theoryKey: string): Promise<Conviction> {
  return toConviction(await apiGet<ApiConviction>(convictionPath(projectId, theoryKey)))
}

export async function statePrior(
  projectId: string, theoryKey: string, value: number, method: 'lottery' | 'direct', note?: string,
): Promise<Conviction> {
  return toConviction(
    await apiPost<ApiConviction>(convictionPath(projectId, theoryKey), { value, method, note }),
  )
}

export interface LinkHypothesis {
  id: string
  theoryKey: string
  edgeId: string
  statement: string
  refutedIf: string
  cheapestTest: string
  priority: number
  leverage: number
  uncertainty: number
  status: 'open' | 'held' | 'refuted' | 'inconclusive'
  observedNote: string | null
}

interface ApiHypothesis {
  id: string; theory_key: string; edge_id: string; statement: string; refuted_if: string
  cheapest_test: string; priority: number; leverage: number; uncertainty: number
  status: LinkHypothesis['status']; observed_note: string | null
}

const toHypothesis = (api: ApiHypothesis): LinkHypothesis => ({
  id: api.id, theoryKey: api.theory_key, edgeId: api.edge_id, statement: api.statement,
  refutedIf: api.refuted_if, cheapestTest: api.cheapest_test, priority: api.priority,
  leverage: api.leverage, uncertainty: api.uncertainty, status: api.status,
  observedNote: api.observed_note,
})

export async function fetchHypotheses(projectId: string, theoryKey: string): Promise<LinkHypothesis[]> {
  const res = await apiGet<{ hypotheses: ApiHypothesis[] }>(
    `/api/v1/graph/${projectId}/hypotheses?theory_key=${encodeURIComponent(theoryKey)}`,
  )
  return res.hypotheses.map(toHypothesis)
}

export async function proposeHypotheses(projectId: string, theoryId: string): Promise<LinkHypothesis[]> {
  const res = await apiPost<{ hypotheses: ApiHypothesis[] }>(
    `/api/v1/graph/${projectId}/theories/${theoryId}/hypotheses`, {},
  )
  return res.hypotheses.map(toHypothesis)
}

export async function recordHypothesisResult(
  projectId: string, hypothesisId: string, result: 'held' | 'refuted' | 'inconclusive',
  likelihoodRatio?: number, note?: string,
): Promise<LinkHypothesis> {
  return toHypothesis(await apiPost<ApiHypothesis>(
    `/api/v1/graph/${projectId}/hypotheses/${hypothesisId}/result`,
    { result, likelihood_ratio: likelihoodRatio, note },
  ))
}

// --- Field tests: the only experiment allowed to move conviction ---

export interface FieldTest {
  id: string
  hypothesis: string
  design: string
  measure: string | null
  costEstimate: string | null
  durationDays: number | null
  status: 'designed' | 'executed' | 'abandoned'
  summary: string | null
}

interface ApiExperiment {
  id: string; kind: 'synthetic' | 'field'; hypothesis: string; design: string
  measure: string | null; cost_estimate: string | null; duration_days: number | null
  status: FieldTest['status']; summary: string | null
}

const toFieldTest = (api: ApiExperiment): FieldTest => ({
  id: api.id, hypothesis: api.hypothesis, design: api.design, measure: api.measure,
  costEstimate: api.cost_estimate, durationDays: api.duration_days, status: api.status,
  summary: api.summary,
})

export async function fetchFieldTests(projectId: string, theoryId: string): Promise<FieldTest[]> {
  const res = await apiGet<{ experiments: ApiExperiment[] }>(
    `/api/v1/graph/${projectId}/experiments?theory_id=${encodeURIComponent(theoryId)}`,
  )
  return res.experiments.filter((e) => e.kind === 'field').map(toFieldTest)
}

export async function designFieldTest(projectId: string, theoryId: string): Promise<FieldTest> {
  return toFieldTest(await apiPost<ApiExperiment>(
    `/api/v1/graph/${projectId}/theories/${theoryId}/experiments/field`, {},
  ))
}

export async function recordFieldResult(
  projectId: string, experimentId: string, result: 'supports' | 'refutes' | 'inconclusive',
  note?: string,
): Promise<void> {
  await apiPost(`/api/v1/graph/${projectId}/experiments/${experimentId}/result`, { result, note })
}
