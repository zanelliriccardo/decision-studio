import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import TheoryPanel from '../TheoryPanel.tsx'
import { LanguageProvider } from '../../../i18n/index.tsx'
import { makeGraph, makeTheory } from '../../../test/fixtures.ts'

function renderPanel(props: Partial<React.ComponentProps<typeof TheoryPanel>> = {}) {
  const defaults: React.ComponentProps<typeof TheoryPanel> = {
    graph: makeGraph(),
    theories: [],
    changeSummary: null,
    loading: false,
    generating: false,
    error: null,
    staleCount: 0,
    graphRevision: 3,
    selectedTheoryId: null,
    onSelectTheory: vi.fn(),
    onGenerate: vi.fn(),
    onRegenerate: vi.fn(),
    onDismissChangeSummary: vi.fn(),
    onClose: vi.fn(),
  }
  const merged = { ...defaults, ...props }
  return {
    ...render(
      <LanguageProvider>
        <TheoryPanel {...merged} />
      </LanguageProvider>,
    ),
    props: merged,
  }
}

describe('TheoryPanel states', () => {
  it('shows a loading indicator while fetching', () => {
    renderPanel({ loading: true })
    expect(screen.getByTestId('theories-loading')).toBeInTheDocument()
  })

  it('shows an error message with an alert role', () => {
    renderPanel({ error: 'The reviewed graph has no active claims.' })
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('no active claims')
  })

  it('shows an empty state prompting generation', () => {
    renderPanel()
    expect(screen.getByTestId('theories-empty')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /generate theories/i })).toBeInTheDocument()
  })

  it('offers regeneration once theories exist', () => {
    renderPanel({ theories: [makeTheory()] })
    expect(
      screen.getByRole('button', { name: /regenerate theories/i }),
    ).toBeInTheDocument()
  })

  it('disables the generate button while generating', () => {
    renderPanel({ generating: true })
    expect(screen.getByRole('button', { name: /generating/i })).toBeDisabled()
  })

  it('calls onGenerate when the button is pressed', async () => {
    const onGenerate = vi.fn()
    renderPanel({ onGenerate })
    await userEvent.click(screen.getByRole('button', { name: /generate theories/i }))
    expect(onGenerate).toHaveBeenCalledOnce()
  })
})

describe('TheoryPanel content', () => {
  it('renders a theory with its recommendation and a confidence band', () => {
    renderPanel({ theories: [makeTheory()] })
    expect(screen.getByText(/schedule exposure driven by vendor readiness/i)).toBeInTheDocument()
    expect(screen.getByText(/confirm vendor readiness/i)).toBeInTheDocument()
    // A band, not "72%": nothing here has been calibrated, so a percentage
    // would assert a resolution the pipeline does not have.
    expect(screen.getByTestId('confidence-band')).toHaveTextContent('High')
    expect(screen.queryByText('72%')).not.toBeInTheDocument()
  })

  it('shows evidence, weak assumptions and provenance counts when expanded', async () => {
    renderPanel({ theories: [makeTheory()] })
    await userEvent.click(screen.getByRole('button', { name: /details/i }))

    const card = screen.getByTestId('theory-card')
    expect(within(card).getByText(/late vendor confirmation correlates/i)).toBeInTheDocument()
    expect(within(card).getByText(/parallel workstreams absorbed/i)).toBeInTheDocument()
    expect(within(card).getByText(/critical-path exposure/i)).toBeInTheDocument()
    expect(within(card).getByText(/graph revision 3/i)).toBeInTheDocument()
  })


  it('explains what changed between versions', async () => {
    const theory = makeTheory({
      changeKind: 'changed',
      changeExplanation: 'confidence fell from 0.72 to 0.35',
      version: 2,
    })
    renderPanel({ theories: [theory] })
    await userEvent.click(screen.getByRole('button', { name: /details/i }))

    expect(screen.getByText(/confidence fell from 0.72 to 0.35/i)).toBeInTheDocument()
    expect(screen.getByText(/version 2/i)).toBeInTheDocument()
  })
})

describe('TheoryPanel staleness', () => {
  it('marks a stale theory and explains why', () => {
    const theory = makeTheory({
      isStale: true,
      staleReason: 'Graph edited at revision 4',
    })
    renderPanel({ theories: [theory], staleCount: 1 })

    const card = screen.getByTestId('theory-card')
    expect(card).toHaveAttribute('data-stale', 'true')
    expect(within(card).getByTestId('stale-indicator')).toHaveTextContent(
      /graph edited at revision 4/i,
    )
  })

  it('shows a banner counting stale theories', () => {
    renderPanel({ theories: [makeTheory({ isStale: true })], staleCount: 1 })
    // The panel-level banner, not the per-card indicator.
    const banners = screen.getAllByRole('status')
    expect(banners.some((el) => /1 theory/i.test(el.textContent ?? ''))).toBe(true)
  })

  it('does not show the stale banner when everything is current', () => {
    renderPanel({ theories: [makeTheory()], staleCount: 0 })
    expect(screen.queryByTestId('stale-indicator')).not.toBeInTheDocument()
  })
})

describe('TheoryPanel path highlighting', () => {
  it('hands the theory to the caller when highlighting', async () => {
    const onSelectTheory = vi.fn()
    const theory = makeTheory()
    renderPanel({ theories: [theory], onSelectTheory })

    await userEvent.click(screen.getByRole('button', { name: /highlight path/i }))

    expect(onSelectTheory).toHaveBeenCalledWith(theory)
  })

  it('clears the highlight when the selected theory is toggled off', async () => {
    const onSelectTheory = vi.fn()
    const theory = makeTheory()
    renderPanel({ theories: [theory], selectedTheoryId: theory.id, onSelectTheory })

    await userEvent.click(screen.getByRole('button', { name: /clear highlight/i }))

    expect(onSelectTheory).toHaveBeenCalledWith(null)
  })

  it('marks the selected theory as pressed for assistive tech', () => {
    const theory = makeTheory()
    renderPanel({ theories: [theory], selectedTheoryId: theory.id })
    expect(screen.getByRole('button', { name: /clear highlight/i })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })
})

describe('TheoryPanel filtering', () => {
  it('filters by status', async () => {
    renderPanel({
      theories: [
        makeTheory({ id: 't1', title: 'Supported theory', status: 'supported' }),
        makeTheory({
          id: 't2',
          theoryKey: 'key-2',
          title: 'Contested theory',
          status: 'contested',
          supportingEdgeIds: ['edge-2'],
        }),
      ],
    })

    await userEvent.selectOptions(screen.getByLabelText(/filter by status/i), 'contested')

    expect(screen.getByText('Contested theory')).toBeInTheDocument()
    expect(screen.queryByText('Supported theory')).not.toBeInTheDocument()
  })

  it('filters by business impact', async () => {
    renderPanel({
      theories: [
        makeTheory({ id: 't1', title: 'High impact', businessImpact: 'high' }),
        makeTheory({ id: 't2', title: 'Low impact', businessImpact: 'low' }),
      ],
    })

    await userEvent.selectOptions(screen.getByLabelText(/filter by impact/i), 'low')

    expect(screen.getByText('Low impact')).toBeInTheDocument()
    expect(screen.queryByText('High impact')).not.toBeInTheDocument()
  })

  it('explains when filters hide everything', async () => {
    renderPanel({ theories: [makeTheory({ status: 'supported' })] })
    await userEvent.selectOptions(screen.getByLabelText(/filter by status/i), 'contested')
    expect(screen.getByText(/no theories match these filters/i)).toBeInTheDocument()
  })
})

describe('TheoryPanel regeneration comparison', () => {
  it('summarizes new, changed, unchanged and superseded counts', () => {
    renderPanel({
      theories: [makeTheory()],
      changeSummary: {
        newTheoryIds: ['a'],
        changedTheoryIds: ['b', 'c'],
        unchangedTheoryIds: [],
        supersededTheoryIds: ['d'],
      },
    })

    const summary = screen.getByTestId('change-summary')
    expect(within(summary).getByText('New: 1')).toBeInTheDocument()
    expect(within(summary).getByText('Changed: 2')).toBeInTheDocument()
    expect(within(summary).getByText('Unchanged: 0')).toBeInTheDocument()
    expect(within(summary).getByText('Superseded: 1')).toBeInTheDocument()
  })

  it('can dismiss the change summary', async () => {
    const onDismissChangeSummary = vi.fn()
    renderPanel({
      theories: [makeTheory()],
      changeSummary: {
        newTheoryIds: ['a'],
        changedTheoryIds: [],
        unchangedTheoryIds: [],
        supersededTheoryIds: [],
      },
      onDismissChangeSummary,
    })

    const summary = screen.getByTestId('change-summary')
    await userEvent.click(within(summary).getByRole('button', { name: /close/i }))

    expect(onDismissChangeSummary).toHaveBeenCalledOnce()
  })
})

describe('TheoryPanel accessibility', () => {
  it('conveys status with text, not colour alone', () => {
    renderPanel({ theories: [makeTheory({ status: 'contested' })] })
    const card = screen.getByTestId('theory-card')
    expect(within(card).getByText('Contested')).toBeInTheDocument()
  })

  it('conveys business impact with a text label as well as bars', () => {
    renderPanel({ theories: [makeTheory({ businessImpact: 'critical' })] })
    expect(screen.getByTitle(/business impact: critical/i)).toBeInTheDocument()
  })

  it('labels supporting and contradicting evidence for screen readers', async () => {
    renderPanel({ theories: [makeTheory()] })
    await userEvent.click(screen.getByRole('button', { name: /details/i }))
    expect(screen.getByText('Supporting:')).toBeInTheDocument()
    expect(screen.getByText('Contradicting:')).toBeInTheDocument()
  })
})
