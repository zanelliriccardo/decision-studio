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

import { apiGet, apiPatch, apiPost } from './api/client.ts'
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
  /** The real-world event the observation came from, when one was named. */
  event: string | null
  /** Set when another observation of the same event is the one counted. */
  duplicateOf: string | null
  /** Descriptive labels: recent, independent, decisive, ... (reasoning/evidence_quality.py) */
  quality: { key: string; text: string; tone: 'good' | 'neutral' | 'caution' }[]
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
    event?: string | null; duplicate_of?: string | null
    quality?: { key: string; text: string; tone: 'good' | 'neutral' | 'caution' }[]
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
    event: s.event ?? null, duplicateOf: s.duplicate_of ?? null,
    quality: s.quality ?? [],
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
  decisiveness: 'weak' | 'moderate' | 'decisive'
}

interface ApiHypothesis {
  id: string; theory_key: string; edge_id: string; statement: string; refuted_if: string
  cheapest_test: string; priority: number; leverage: number; uncertainty: number
  status: LinkHypothesis['status']; observed_note: string | null
  decisiveness?: LinkHypothesis['decisiveness']
}

const toHypothesis = (api: ApiHypothesis): LinkHypothesis => ({
  id: api.id, theoryKey: api.theory_key, edgeId: api.edge_id, statement: api.statement,
  refutedIf: api.refuted_if, cheapestTest: api.cheapest_test, priority: api.priority,
  leverage: api.leverage, uncertainty: api.uncertainty, status: api.status,
  observedNote: api.observed_note,
  decisiveness: api.decisiveness ?? 'moderate',
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
  likelihoodRatio?: number, note?: string, event?: string,
): Promise<LinkHypothesis> {
  return toHypothesis(await apiPost<ApiHypothesis>(
    `/api/v1/graph/${projectId}/hypotheses/${hypothesisId}/result`,
    { result, likelihood_ratio: likelihoodRatio, note, event: event?.trim() || undefined },
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
  note?: string, event?: string,
): Promise<void> {
  await apiPost(`/api/v1/graph/${projectId}/experiments/${experimentId}/result`, {
    result, note, event: event?.trim() || undefined,
  })
}

/** Event labels already used on observations in this project, most recent first. */
export async function fetchObservationEvents(projectId: string): Promise<string[]> {
  const res = await apiGet<{ events: string[] }>(`/api/v1/graph/${projectId}/observation-events`)
  return res.events ?? []
}

/**
 * How many of a theory's counted observations are independent: observations of
 * one event count once, so "3 observations, 2 independent" says why the third
 * did not move the number.
 */
export function independentCount(steps: ConvictionStep[]): { total: number; independent: number } {
  const total = steps.length
  const independent = steps.filter((s) => s.duplicateOf === null).length
  return { total, independent }
}

/** How much an open link test would count, stated before it is run. */
export async function setHypothesisDecisiveness(
  projectId: string, hypothesisId: string, decisiveness: LinkHypothesis['decisiveness'],
): Promise<LinkHypothesis> {
  return toHypothesis(await apiPatch<ApiHypothesis>(
    `/api/v1/graph/${projectId}/hypotheses/${hypothesisId}/decisiveness`, { decisiveness },
  ))
}

export interface DataTestResult {
  hypothesis: LinkHypothesis
  result: 'held' | 'refuted' | 'inconclusive'
  method: string
  n: number
  pValue: number | null
  summary: string
}

/**
 * Test a link against two pasted columns (cause, effect). The server picks the
 * test, and records the result like any other, so it moves conviction.
 */
export async function testHypothesisWithData(
  projectId: string, hypothesisId: string, table: string, timeOrdered: boolean, event?: string,
): Promise<DataTestResult> {
  const res = await apiPost<{
    hypothesis: ApiHypothesis; result: DataTestResult['result']; method: string; n: number
    p_value: number | null; summary: string
  }>(`/api/v1/graph/${projectId}/hypotheses/${hypothesisId}/data`, {
    table, time_ordered: timeOrdered, event: event?.trim() || undefined,
  })
  return {
    hypothesis: toHypothesis(res.hypothesis), result: res.result, method: res.method,
    n: res.n, pValue: res.p_value, summary: res.summary,
  }
}
