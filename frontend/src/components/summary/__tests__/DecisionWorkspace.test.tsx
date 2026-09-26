import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { LanguageProvider } from '../../../i18n/index.tsx'
import * as workspace from '../../../lib/api/workspace.ts'
import type {
  AssumptionRegister,
  Scenarios,
  SubDecision,
  Timeline,
} from '../../../lib/api/workspace.ts'
import AssumptionsCard from '../AssumptionsCard.tsx'
import TimelineCard from '../TimelineCard.tsx'
import ScenariosCard from '../ScenariosCard.tsx'
import SubDecisionsCard from '../SubDecisionsCard.tsx'
import QualityChips from '../../evidence/QualityChips.tsx'

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const wrap = (ui: React.ReactElement) => render(<LanguageProvider>{ui}</LanguageProvider>)

beforeEach(() => {
  vi.restoreAllMocks()
  vi.mocked(toast.error).mockClear()
})

describe('Evidence quality', () => {
  it('shows descriptive labels with their tone', () => {
    wrap(<QualityChips labels={[
      { key: 'recent', text: 'Recent', tone: 'good' },
      { key: 'same_source', text: 'Same source as 1 other(s)', tone: 'caution' },
    ]} />)
    expect(screen.getByText('Recent')).toHaveAttribute('data-tone', 'good')
    expect(screen.getByText('Same source as 1 other(s)')).toHaveAttribute('data-tone', 'caution')
  })

  it('renders nothing without labels', () => {
    const { container } = wrap(<QualityChips labels={[]} />)
    expect(container.querySelector('[data-testid="quality-chips"]')).toBeNull()
  })
})

const register = (overrides: Partial<AssumptionRegister> = {}): AssumptionRegister => ({
  total: 3,
  influenceBasis: 'comparison',
  assumptions: [
    {
      claimId: 'c1', text: 'Vendor delivers on 1 August', decisionRole: 'contingency', belief: 0.55,
      uncertainty: 0.99, options: ['O1'], outcomes: ['Y1'],
      evidence: { count: 2, supporting: 1, contradicting: 1, labels: [
        { key: 'contradicting', text: '1 contradicting', tone: 'caution' },
      ] },
      needsEvidence: true, stale: true, staleTheories: ['Q3 is safe'], driverRank: 1, impact: 0.12,
      canAlter: true, flip: 'flips', affects: 'comparison', influenceBasis: 'comparison', priority: 0.5,
    },
    {
      claimId: 'c2', text: 'Market grows', decisionRole: 'contingency', belief: 0.8, uncertainty: 0.64,
      options: [], outcomes: ['Y1', 'Y2'], evidence: { count: 0, supporting: 0, contradicting: 0, labels: [] },
      needsEvidence: false, stale: false, staleTheories: [], driverRank: null, impact: 0.0,
      canAlter: false, flip: 'no_flip', affects: 'all_options', influenceBasis: 'comparison', priority: 0.1,
    },
  ],
  ...overrides,
})

describe('Assumption register', () => {
  it('shows each assumption with what is known about it', () => {
    wrap(<AssumptionsCard projectId="p1" register={register()} />)
    const [first, second] = screen.getAllByTestId('assumption')
    expect(first).toHaveTextContent('Vendor delivers on 1 August')
    expect(first).toHaveTextContent('55%')
    expect(first).toHaveTextContent('Options: O1')
    expect(first).toHaveTextContent('Sensitivity driver #1')
    expect(within(first).getByTestId('can-alter')).toBeInTheDocument()
    expect(first).toHaveTextContent('Cited by an out-of-date theory')
    expect(first).toHaveTextContent('Marked as needing evidence')
    expect(first).toHaveTextContent('1 contradicting')
    expect(second).toHaveTextContent('Affects all options similarly')
    expect(within(second).queryByTestId('can-alter')).not.toBeInTheDocument()
    expect(screen.getByText('1 more in the map')).toBeInTheDocument()
  })

  it('has an empty state, and says when influence is only the relevance score', () => {
    wrap(<AssumptionsCard projectId="p1" register={register({ assumptions: [], total: 0, influenceBasis: 'relevance' })} />)
    expect(screen.getByTestId('assumptions-empty')).toBeInTheDocument()
    expect(screen.getByText(/influence is the model's relevance score/)).toBeInTheDocument()
  })
})

describe('Decision journal', () => {
  const timeline: Timeline = {
    total: 3,
    material: 2,
    events: [
      { at: '2026-09-01T10:00:00Z', kind: 'created', title: 'Analysis created', detail: null, beliefChange: null, material: true },
      { at: '2026-09-02T10:00:00Z', kind: 'graph', title: 'Claim added', detail: 'x', beliefChange: null, material: false },
      { at: '2026-09-03T10:00:00Z', kind: 'tripwire', title: 'Tripwire happened: Vendor misses 15 August',
        detail: 'marked out of date', beliefChange: 'conviction in “Q3 is safe” 60% → 13%', material: true },
    ],
  }

  it('shows material events, newest first, with the belief they moved', async () => {
    wrap(<TimelineCard projectId="p1" timeline={timeline} />)
    const events = screen.getAllByTestId('timeline-event')
    expect(events).toHaveLength(2)
    expect(events[0]).toHaveTextContent('Tripwire happened')
    expect(within(events[0]).getByTestId('belief-change')).toHaveTextContent('60% → 13%')
    await userEvent.click(screen.getByRole('button', { name: 'Show all 3 events' }))
    expect(screen.getAllByTestId('timeline-event')).toHaveLength(3)
  })
})

const scenarios = (downsideSource: 'automatic' | 'user' = 'automatic'): Scenarios => {
  const options = (y1: number[]) => [
    { key: 'O1', label: 'Q3', outcomes: { Y1: { point: y1[0], p10: 0, p90: 1 } }, weighted: y1[0] },
    { key: 'O2', label: 'Q4', outcomes: { Y1: { point: y1[1], p10: 0, p90: 1 } }, weighted: y1[1] },
  ]
  return {
    outcomes: [{ key: 'Y1', label: 'Ship' }],
    unavailable: null,
    cases: [
      { key: 'base', label: 'Base case', source: 'base', assumptions: [], options: options([0.35, 0.72]),
        headline: { higher: 'O2', verdict: 'robust', share: 0.9 }, unavailable: null },
      { key: 'upside', label: 'Upside', source: 'automatic',
        assumptions: [{ kind: 'link', id: 'e1', label: 'Vendor → date', base: 0.6, value: 0.8 }],
        options: options([0.5, 0.8]), headline: { higher: 'O2', verdict: 'robust', share: 0.9 }, unavailable: null },
      { key: 'downside', label: 'Downside', source: downsideSource,
        assumptions: [{ kind: 'link', id: 'e1', label: 'Vendor → date', base: 0.6, value: 0.4 }],
        options: options([0.15, 0.51]), headline: { higher: 'O2', verdict: 'sensitive', share: 0.7 }, unavailable: null },
    ],
  }
}

describe('Scenarios', () => {
  it('shows each case with the inputs it changed', () => {
    wrap(<ScenariosCard projectId="p1" scenarios={scenarios()} />)
    const [q3] = screen.getAllByTestId('scenario-row')
    expect(within(q3).getByTestId('cell-base')).toHaveTextContent('Y1 35%')
    expect(within(q3).getByTestId('cell-downside')).toHaveTextContent('Y1 15%')
    const downside = screen.getByTestId('case-downside')
    expect(downside).toHaveTextContent('Vendor → date: 60% → 40%')
    expect(within(downside).getByTestId('case-source')).toHaveTextContent(/Automatic/)
    expect(screen.getByText(/scenario assumptions, not forecasts/)).toBeInTheDocument()
  })

  it('lets the decider set their own assumptions, and reset them', async () => {
    const save = vi.spyOn(workspace, 'saveScenario').mockResolvedValue(scenarios('user'))
    const reset = vi.spyOn(workspace, 'resetScenario').mockResolvedValue(scenarios())
    wrap(<ScenariosCard projectId="p1" scenarios={scenarios()} />)
    const downside = screen.getByTestId('case-downside')
    await userEvent.click(within(downside).getByRole('button', { name: 'Edit assumptions' }))
    const input = within(downside).getByLabelText('Vendor → date')
    await userEvent.clear(input)
    await userEvent.type(input, '25')
    await userEvent.click(within(downside).getByRole('button', { name: 'Save' }))
    expect(save).toHaveBeenCalledWith('p1', 'downside', [{ kind: 'link', id: 'e1', value: 0.25 }])
    const updated = screen.getByTestId('case-downside')
    expect(within(updated).getByTestId('case-source')).toHaveTextContent('Your assumptions')
    await userEvent.click(within(updated).getByRole('button', { name: 'Back to automatic' }))
    expect(reset).toHaveBeenCalledWith('p1', 'downside')
  })
})

const subDecision = (overrides: Partial<SubDecision> = {}): SubDecision => ({
  key: 'S1', parent: 'O1', parentLabel: 'Q3', label: 'Staffing',
  outcomes: [{ key: 'Y1', label: 'Ship' }],
  choices: [
    { key: 'S1a', label: 'Contractors', claims: [{ id: 'c1', text: 'x' }], reachesOutcome: true,
      outcomes: { Y1: { point: 0.58, p10: 0.5, p90: 0.6 } }, weighted: 0.58 },
    { key: 'S1b', label: 'Internal team', claims: [{ id: 'c2', text: 'y' }], reachesOutcome: true,
      outcomes: { Y1: { point: 0.42, p10: 0.4, p90: 0.45 } }, weighted: 0.42 },
  ],
  spread: 0.16, verdict: { verdict: 'robust', higher: 'S1a', share: 0.86, difference: 0.16 },
  sentence: 'Under O1 Q3, the staffing choice moves the weighted view from 42 to 58 points.',
  unavailable: null,
  ...overrides,
})

const OPTIONS = [{ key: 'O1', label: 'Q3' }, { key: 'O2', label: 'Q4' }]
const CLAIMS = [{ id: 'c1', text: 'Contractors are available in August' }, { id: 'c2', text: 'The team can absorb the work' }]

describe('Sub-decisions', () => {
  it('shows how the option depends on each choice', () => {
    wrap(<SubDecisionsCard projectId="p1" options={OPTIONS} claims={CLAIMS} subDecisions={[subDecision()]} />)
    const sd = screen.getByTestId('sub-decision')
    expect(sd).toHaveTextContent('Q3 → Staffing')
    const [contractors, internal] = within(sd).getAllByTestId('sub-choice')
    expect(contractors).toHaveTextContent('Contractors')
    expect(contractors).toHaveTextContent('58%')
    expect(internal).toHaveTextContent('42 / 100')
    expect(within(sd).getByTestId('sub-sentence')).toHaveTextContent('from 42 to 58 points')
  })

  it('says when the map cannot tell the choices apart', () => {
    wrap(<SubDecisionsCard projectId="p1" options={OPTIONS} claims={CLAIMS}
      subDecisions={[subDecision({ unavailable: 'the map cannot tell them apart' })]} />)
    expect(screen.getByTestId('sub-unavailable')).toHaveTextContent('cannot tell them apart')
  })

  it('refuses an incomplete sub-decision, and saves a complete one with the existing ones', async () => {
    const save = vi.spyOn(workspace, 'saveSubDecisions').mockResolvedValue([subDecision(), subDecision({ key: 'S2' })])
    wrap(<SubDecisionsCard projectId="p1" options={OPTIONS} claims={CLAIMS} subDecisions={[subDecision()]} />)
    await userEvent.click(screen.getByRole('button', { name: /Add a sub-decision/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Save sub-decisions' }))
    expect(toast.error).toHaveBeenCalled()
    expect(save).not.toHaveBeenCalled()

    const editor = screen.getByTestId('sub-editor')
    await userEvent.type(within(editor).getByLabelText('Sub-decision (e.g. Staffing)'), 'Vendor')
    const [first, second] = within(editor).getAllByTestId('choice-editor')
    await userEvent.type(within(first).getByLabelText('Choice 1'), 'Keep vendor')
    await userEvent.click(within(first).getByLabelText('Contractors are available in August'))
    await userEvent.type(within(second).getByLabelText('Choice 2'), 'Switch vendor')
    await userEvent.click(within(second).getByLabelText('The team can absorb the work'))
    await userEvent.click(screen.getByRole('button', { name: 'Save sub-decisions' }))
    expect(save).toHaveBeenCalledWith('p1', [
      { parent: 'O1', label: 'Staffing', choices: [
        { label: 'Contractors', claim_ids: ['c1'] }, { label: 'Internal team', claim_ids: ['c2'] }] },
      { parent: 'O1', label: 'Vendor', choices: [
        { label: 'Keep vendor', claim_ids: ['c1'] }, { label: 'Switch vendor', claim_ids: ['c2'] }] },
    ])
    expect(screen.getAllByTestId('sub-decision')).toHaveLength(2)
  })
})
