import { describe, expect, it } from 'vitest'
import {
  LOTTERY_STEPS,
  answerLottery,
  describeLottery,
  likelihoodKey,
  lotteryEstimate,
  lotteryProbe,
  optionCoverage,
  startLottery,
  type LotteryChoice,
} from '../theoryValue.ts'
import { makeTheory } from '../../test/fixtures.ts'

const run = (choices: LotteryChoice[]) => choices.reduce(answerLottery, startLottery())

describe('lottery elicitation', () => {
  it('starts at even odds and bisects towards the preferred bet', () => {
    const s = startLottery()
    expect(lotteryProbe(s)).toBe(0.5)
    expect(lotteryProbe(answerLottery(s, 'theory'))).toBe(0.75)
    expect(lotteryProbe(answerLottery(s, 'draw'))).toBe(0.25)
  })

  it('finishes after the fixed number of questions', () => {
    const s = run(['theory', 'draw', 'theory', 'theory'])
    expect(s.answers).toHaveLength(LOTTERY_STEPS)
    expect(s.done).toBe(true)
    // (0.5, 0.75) -> (0.63, 0.75) -> (0.69, 0.75)
    expect(lotteryEstimate(s)).toBeGreaterThan(0.63)
    expect(lotteryEstimate(s)).toBeLessThan(0.75)
  })

  it('stops at the offered chance when both bets feel the same', () => {
    const s = run(['theory', 'same'])
    expect(s.done).toBe(true)
    expect(lotteryEstimate(s)).toBe(0.75)
  })

  it('never elicits certainty', () => {
    expect(lotteryEstimate(run(['theory', 'theory', 'theory', 'theory']))).toBeLessThanOrEqual(0.99)
    expect(lotteryEstimate(run(['draw', 'draw', 'draw', 'draw']))).toBeGreaterThanOrEqual(0.01)
  })

  it('records the answers so the prior can be audited', () => {
    expect(describeLottery(run(['theory', 'draw']))).toBe('50%: theory, 75%: draw')
  })
})

describe('evidence scale', () => {
  it('maps a ratio to the nearest verbal step', () => {
    expect(likelihoodKey(4)).toBe('strongly_for')
    expect(likelihoodKey(1.5)).toBe('for')
    expect(likelihoodKey(1)).toBe('neutral')
    expect(likelihoodKey(0.25)).toBe('strongly_against')
  })
})

describe('option coverage', () => {
  it('counts for and against per option and leaves silent options empty', () => {
    const anchor = {
      decision: 'd', deadline: '', constraints: [], status: 'draft' as const, outcomes: [],
      options: [{ key: 'O1', label: 'Q3' }, { key: 'O2', label: 'Q4' }],
    }
    const rows = optionCoverage(anchor, [
      makeTheory({ optionKey: 'O1', predictedEffect: 'achieves', reachesOutcome: true }),
      makeTheory({ id: 't2', optionKey: 'O1', predictedEffect: 'threatens' }),
    ])
    expect(rows[0]).toMatchObject({ key: 'O1', achieves: 1, threatens: 1, reachingOutcome: 1 })
    expect(rows[1]).toMatchObject({ key: 'O2', achieves: 0, threatens: 0, unclear: 0 })
  })
})
