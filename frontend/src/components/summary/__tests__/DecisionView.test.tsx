import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LanguageProvider } from '../../../i18n/index.tsx'
import * as reasoningApi from '../../../lib/api/reasoning.ts'
import type {
  InformationItem,
  MindOption,
  OptionComparison,
  PairRobustness,
  SensitivityDriver,
} from '../../../lib/api/reasoning.ts'
import DecisionPrioritiesCard from '../DecisionPrioritiesCard.tsx'
import OptionForecastCard from '../OptionForecastCard.tsx'
import RobustnessCard from '../RobustnessCard.tsx'
import MindChangersCard from '../MindChangersCard.tsx'
import InformationPriorityCard from '../InformationPriorityCard.tsx'

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const wrap = (ui: React.ReactElement) => render(<LanguageProvider>{ui}</LanguageProvider>)

const stats = (point: number) => ({ point, p10: point - 0.05, p50: point, p90: point + 0.05, pBest: 0.5 })

function pair(overrides: Partial<PairRobustness> = {}): PairRobustness {
  return {
    a: 'O1',
    b: 'O2',
    summary: 'mixed',
    outcomes: [
      { key: 'Y1', label: 'Ship by Q3', verdict: 'robust', higher: 'O2', share: 0.87,
        difference: -0.37, valueA: 0.35, valueB: 0.72, sentence: '' },
      { key: 'Y2', label: 'Stay within budget', verdict: 'sensitive', higher: 'O1', share: 0.61,
        difference: 0.33, valueA: 0.88, valueB: 0.55, sentence: '' },
    ],
    weighted: { verdict: 'robust', higher: 'O2', share: 0.83, difference: -0.1, valueA: 0.5,
      valueB: 0.6, sentence: '' },
    ...overrides,
  }
}

function driver(overrides: Partial<SensitivityDriver> = {}): SensitivityDriver {
  return {
    kind: 'link', key: 'a->b', edgeId: 'e1', claimId: null,
    label: 'Vendor delivery reliability → Ship by Q3', current: 0.6, low: 0.4, high: 0.8,
    uncertainty: 0.7, baseGap: -0.1, lowGap: -0.2, highGap: 0.03, impact: 0.23, flip: 'flips',
    flipsOutcomes: ['Y1'], explanation: 'At the low end Q4 leads; at the high end Q3 does.',
    ...overrides,
  }
}

function comparison(overrides: Partial<OptionComparison> = {}): OptionComparison {
  return {
    outcomes: [{ key: 'Y1', label: 'Ship by Q3' }, { key: 'Y2', label: 'Stay within budget' }],
    options: [
      { key: 'O1', label: 'Q3', status: 'modelled', leversOn: [], leversOff: [], reachesOutcome: true,
        outcomes: { Y1: stats(0.35), Y2: stats(0.88) }, score: 0.5, pBest: 0.17,
        weighted: { score: 0.5, contributions: { Y1: 0.23, Y2: 0.27 } } },
      { key: 'O2', label: 'Q4', status: 'modelled', leversOn: [], leversOff: [], reachesOutcome: true,
        outcomes: { Y1: stats(0.72), Y2: stats(0.55) }, score: 0.6, pBest: 0.83,
        weighted: { score: 0.6, contributions: { Y1: 0.47, Y2: 0.13 } } },
    ],
    decisive: true,
    leader: 'O2',
    runs: 200,
    unavailable: null,
    priorities: [
      { key: 'Y1', label: 'Ship by Q3', importance: 'critical', weight: 8, normalizedWeight: 0.67, isDefault: false },
      { key: 'Y2', label: 'Stay within budget', importance: 'high', weight: 4, normalizedWeight: 0.33, isDefault: false },
    ],
    robustness: [pair()],
    headlinePair: ['O2', 'O1'],
    drivers: [driver(), driver({ key: 'c', kind: 'claim', label: 'Team capacity', flip: 'no_flip', impact: 0.05 })],
    informationPriority: [],
    ...overrides,
  }
}

describe('Decision priorities', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('shows each criterion, and which are still at the default', () => {
    const c = comparison({
      priorities: [
        { key: 'Y1', label: 'Ship by Q3', importance: 'critical', weight: 8, normalizedWeight: 0.8, isDefault: false },
        { key: 'Y2', label: 'Stay within budget', importance: 'medium', weight: 2, normalizedWeight: 0.2, isDefault: true },
      ],
    })
    wrap(<DecisionPrioritiesCard projectId="p1" priorities={c.priorities} onChanged={vi.fn()} />)
    const rows = screen.getAllByTestId('priority-row')
    expect(within(rows[0]).getByText('80% of the weight')).toBeInTheDocument()
    expect(within(rows[0]).getByRole('button', { name: 'Critical' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(rows[1]).getByText(/not set — Medium/)).toBeInTheDocument()
    expect(within(rows[1]).getByRole('button', { name: 'Medium' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('sends only what was set, plus the new choice, and hands back the recomputed comparison', async () => {
    const recomputed = comparison()
    const save = vi.spyOn(reasoningApi, 'setDecisionPriorities').mockResolvedValue(recomputed)
    const onChanged = vi.fn()
    const priorities = comparison().priorities.map((p, i) => (i === 1 ? { ...p, isDefault: true, importance: 'medium' as const } : p))
    wrap(<DecisionPrioritiesCard projectId="p1" priorities={priorities} onChanged={onChanged} />)
    const rows = screen.getAllByTestId('priority-row')
    await userEvent.click(within(rows[1]).getByRole('button', { name: 'Not a factor' }))
    expect(save).toHaveBeenCalledWith('p1', { Y1: 'critical', Y2: 'none' })
    expect(onChanged).toHaveBeenCalledWith(recomputed)
  })

  it('explains the mapping', () => {
    wrap(<DecisionPrioritiesCard projectId="p1" priorities={comparison().priorities} onChanged={vi.fn()} />)
    expect(screen.getByText(/Critical 8, High 4, Medium 2, Low 1, Not a factor 0/)).toBeInTheDocument()
  })
})

describe('What each option implies', () => {
  it('keeps model-implied outcomes and the weighted view apart', () => {
    wrap(<OptionForecastCard comparison={comparison()} />)
    const rows = screen.getAllByTestId('forecast-row')
    expect(within(rows[0]).getByText('35%')).toBeInTheDocument()
    expect(within(rows[1]).getByText('72%')).toBeInTheDocument()
    const weighted = within(rows[1]).getByTestId('weighted-cell')
    expect(weighted).toHaveTextContent('60')
    expect(weighted).toHaveTextContent('Y1: 47 pts + Y2: 13 pts')
    const headline = screen.getByTestId('option-forecast-headline')
    expect(headline).toHaveTextContent(/Based on the priorities you entered, the weighted model view is higher for O2 \(Q4\)/)
    expect(headline).toHaveTextContent(/The decision itself stays with you/)
    for (const word of ['best option', 'recommend', 'correct choice']) {
      expect(headline.textContent?.toLowerCase()).not.toContain(word)
    }
  })

  it('says so when no criterion carries weight', () => {
    const c = comparison({ options: comparison().options.map((o) => ({ ...o, weighted: null })) })
    wrap(<OptionForecastCard comparison={c} />)
    expect(screen.getByTestId('option-forecast-headline')).toHaveTextContent(/no weighted view/)
    expect(screen.queryByTestId('weighted-cell')).not.toBeInTheDocument()
  })
})

describe('Robustness & sensitivity', () => {
  it('shows a robust result', () => {
    wrap(<RobustnessCard comparison={comparison({ robustness: [pair({ summary: 'consistent' })] })} />)
    const verdicts = screen.getAllByTestId('verdict')
    expect(verdicts[0]).toHaveAttribute('data-verdict', 'robust')
    expect(verdicts[0]).toHaveTextContent('O2 robustly higher')
    expect(screen.getAllByText(/higher in 87% of simulations/)).toHaveLength(1)
    expect(screen.getByTestId('pair-summary')).toHaveTextContent(/higher on every criterion/)
  })

  it('shows a mixed result as a trade-off', () => {
    wrap(<RobustnessCard comparison={comparison()} />)
    expect(screen.getByTestId('pair-summary')).toHaveTextContent(/A trade-off/)
    expect(screen.getAllByTestId('verdict')[1]).toHaveAttribute('data-verdict', 'sensitive')
  })

  it('shows an unresolved result', () => {
    const unresolved = pair({
      summary: 'unresolved',
      outcomes: [{ key: 'Y1', label: 'Ship by Q3', verdict: 'unresolved', higher: 'O2', share: 0.55,
        difference: -0.03, valueA: 0.4, valueB: 0.43, sentence: '' }],
      weighted: null,
    })
    wrap(<RobustnessCard comparison={comparison({ robustness: [unresolved] })} />)
    expect(screen.getByTestId('verdict')).toHaveAttribute('data-verdict', 'unresolved')
    expect(screen.getByTestId('pair-summary')).toHaveTextContent(/cannot separate/)
  })

  it('renders the top drivers, flagging those that can reverse the comparison', () => {
    wrap(<RobustnessCard comparison={comparison()} />)
    const drivers = screen.getAllByTestId('driver')
    expect(drivers).toHaveLength(2)
    expect(drivers[0]).toHaveTextContent('Vendor delivery reliability → Ship by Q3')
    expect(within(drivers[0]).getByTestId('driver-flip')).toHaveTextContent('can reverse the comparison')
    expect(drivers[0]).toHaveTextContent('60% now · plausible 40%–80%')
    expect(within(drivers[1]).queryByTestId('driver-flip')).not.toBeInTheDocument()
    expect(screen.getByText(/not an empirical forecast/)).toBeInTheDocument()
  })

  it('labels a root claim\'s range as a what-if, and explains no drivers without a weighted view', () => {
    const claimDriver = driver({ kind: 'claim', key: 'c', label: 'Team capacity', flip: 'no_flip' })
    wrap(<RobustnessCard comparison={comparison({ drivers: [claimDriver] })} />)
    expect(screen.getByTestId('driver')).toHaveTextContent('60% now · what-if 40%–80%')
    const unweighted = comparison({ drivers: [], options: comparison().options.map((o) => ({ ...o, weighted: null })) })
    wrap(<RobustnessCard comparison={unweighted} />)
    expect(screen.getByTestId('no-drivers')).toHaveTextContent(/no weighted view for the drivers to explain/)
  })

  it('says a simulation share is not a chance of success', () => {
    wrap(<RobustnessCard comparison={comparison()} />)
    expect(screen.getByText(/not the chance that either option succeeds/)).toBeInTheDocument()
  })

  it('has an empty sensitivity state', () => {
    wrap(<RobustnessCard comparison={comparison({ drivers: [] })} />)
    expect(screen.getByTestId('no-drivers')).toBeInTheDocument()
  })
})

describe('What would change my mind', () => {
  const options: MindOption[] = [
    {
      key: 'O1',
      label: 'Q3',
      theories: [{ id: 't1', title: 'Vendor slippage decides Q3', predictedEffect: 'achieves',
        conviction: 0.68, modelSupport: 0.6, reachesOutcome: true, isStale: false }],
      weaken: [
        { kind: 'tripwire', id: 'tw1', theoryId: 't1', theoryTitle: 'x', text: 'Vendor misses Aug 15',
          condition: 'if it happens', effect: 'weaken', decisiveness: 'decisive', status: 'pending',
          resolved: false, fired: null, detail: null },
        { kind: 'link_test', id: 'h1', theoryId: 't1', theoryTitle: 'x', text: 'Integration takes > 3 weeks',
          condition: 'if the link is refuted', effect: 'weaken', decisiveness: 'moderate',
          status: 'not_tested', resolved: false, fired: null, detail: null },
      ],
      strengthen: [
        { kind: 'tripwire', id: 'tw2', theoryId: 't1', theoryTitle: 'x', text: 'Vendor commits to Aug 1',
          condition: 'if it happens', effect: 'strengthen', decisiveness: 'decisive', status: 'happened',
          resolved: true, fired: true, detail: null },
      ],
    },
    { key: 'O2', label: 'Q4', theories: [], weaken: [], strengthen: [] },
  ]

  it('shows conviction, and the signals each way with their status', () => {
    wrap(<MindChangersCard projectId="p1" options={options} />)
    const [q3, q4] = screen.getAllByTestId('mind-option')
    expect(q3).toHaveTextContent('Your conviction: 68%')
    const weaken = within(q3).getByTestId('mind-weaken')
    expect(within(weaken).getAllByTestId('mind-signal')).toHaveLength(2)
    expect(weaken).toHaveTextContent('Vendor misses Aug 15')
    expect(weaken).toHaveTextContent('Decisive')
    expect(weaken).toHaveTextContent('Not observed yet')
    expect(weaken).toHaveTextContent('Not tested')
    const strengthen = within(q3).getByTestId('mind-strengthen')
    expect(strengthen).toHaveTextContent('Happened')
    expect(within(strengthen).getByTestId('mind-signal').className).toContain('opacity-60')
    expect(q4).toHaveTextContent('No theory argues about this option.')
  })
})

describe('Information priority', () => {
  const item: InformationItem = {
    kind: 'link', key: 'a->b', edgeId: 'e1', claimId: null, subject: 'Vendor → date',
    action: 'Confirm vendor API delivery date', how: 'Ask the vendor lead', hypothesisId: 'h1',
    uncertainty: 0.7, uncertaintyBand: 'high', impact: 0.8, impactBand: 'high', canFlip: true,
    score: 0.56, why: 'High uncertainty; high impact on Q3 vs Q4 — and can reverse the comparison.',
  }

  it('lists what to find out, and why', () => {
    wrap(<InformationPriorityCard items={[item]} />)
    const entry = screen.getByTestId('info-item')
    expect(entry).toHaveTextContent('Confirm vendor API delivery date')
    expect(entry).toHaveTextContent('High uncertainty')
    expect(entry).toHaveTextContent('High impact')
    expect(entry).toHaveTextContent('How: Ask the vendor lead')
    expect(entry).toHaveTextContent(/can reverse the comparison/)
  })

  it('has an empty state', () => {
    wrap(<InformationPriorityCard items={[]} />)
    expect(screen.getByTestId('info-empty')).toBeInTheDocument()
  })
})
