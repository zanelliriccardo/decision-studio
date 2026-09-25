import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import TheoryPanel from '../TheoryPanel.tsx'
import { LanguageProvider } from '../../../i18n/index.tsx'
import { makeGraph, makeTheory } from '../../../test/fixtures.ts'
import type { Objection, Tripwire } from '../../../types/reasoning.ts'

function renderTheories(
  props: Partial<React.ComponentProps<typeof TheoryPanel>> = {},
) {
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

function objection(overrides: Partial<Objection> = {}): Objection {
  return {
    id: 'obj-1',
    objection: 'The whole chain rests on one vendor email from March.',
    kind: 'single_source',
    severity: 0.8,
    dismissed: false,
    ...overrides,
  }
}

function tripwire(overrides: Partial<Tripwire> = {}): Tripwire {
  return {
    id: 'tw-1',
    observable: 'Vendor confirms the integration date in writing',
    direction: 'falsifies',
    horizonDays: 30,
    checkBy: '2026-08-25T00:00:00Z',
    status: 'pending',
    observedAt: null,
    observedNote: null,
    ...overrides,
  }
}


describe('Theory panel: calibration hygiene', () => {
  it('shows a band rather than a percentage', () => {
    renderTheories({ theories: [makeTheory({ confidenceBand: 'moderate' })] })
    expect(screen.getByTestId('confidence-band')).toHaveTextContent('Moderate')
  })

  it('explains why a band and not a number', () => {
    renderTheories({ theories: [makeTheory()] })
    expect(screen.getByTestId('confidence-band')).toHaveAttribute(
      'title',
      expect.stringContaining('never been calibrated'),
    )
  })

  it('does not print two-decimal confidence anywhere', () => {
    const { container } = renderTheories({
      theories: [makeTheory({ confidence: 0.7234 })],
    })
    expect(container.textContent).not.toContain('0.72')
    expect(container.textContent).not.toContain('72%')
  })
})

describe('Theory panel: objections', () => {
  it('shows objections with their kind and severity band', async () => {
    renderTheories({ theories: [makeTheory({ objections: [objection()] })] })
    await userEvent.click(screen.getByRole('button', { name: /details/i }))

    const block = screen.getByTestId('objections')
    expect(within(block).getByText(/one vendor email from march/i)).toBeInTheDocument()
    expect(within(block).getByText('Single source')).toBeInTheDocument()
    expect(within(block).getByText(/severity: very high/i)).toBeInTheDocument()
  })

  it('flags a contested theory', () => {
    renderTheories({
      theories: [makeTheory({ contested: true, objectionLoad: 0.8 })],
    })
    expect(screen.getByTestId('contested-flag')).toHaveTextContent(/reduced this theory/i)
  })

  it('does not flag an unobjected theory', () => {
    renderTheories({ theories: [makeTheory()] })
    expect(screen.queryByTestId('contested-flag')).not.toBeInTheDocument()
  })

  it('lets the user judge an objection unfounded', async () => {
    const onDismissObjection = vi.fn()
    renderTheories({
      theories: [makeTheory({ objections: [objection()] })],
      onDismissObjection,
    })
    await userEvent.click(screen.getByRole('button', { name: /details/i }))
    await userEvent.click(screen.getByRole('button', { name: /unfounded/i }))

    expect(onDismissObjection).toHaveBeenCalledWith('obj-1')
  })

  it('shows a dismissed objection as struck through, not hidden', async () => {
    renderTheories({
      theories: [makeTheory({ objections: [objection({ dismissed: true })] })],
    })
    await userEvent.click(screen.getByRole('button', { name: /details/i }))

    const block = screen.getByTestId('objections')
    expect(within(block).getByText(/dismissed/i)).toBeInTheDocument()
  })
})

describe('Theory panel: tripwires', () => {
  it('shows the tripwire, its direction and its date', async () => {
    renderTheories({ theories: [makeTheory({ tripwires: [tripwire()] })] })
    await userEvent.click(screen.getByRole('button', { name: /details/i }))

    const block = screen.getByTestId('tripwires')
    expect(within(block).getByText(/vendor confirms the integration date/i)).toBeInTheDocument()
    expect(within(block).getByText(/would disprove/i)).toBeInTheDocument()
    expect(within(block).getByText(/2026-08-25/)).toBeInTheDocument()
  })

  it('explains why tripwires exist', async () => {
    renderTheories({ theories: [makeTheory({ tripwires: [tripwire()] })] })
    await userEvent.click(screen.getByRole('button', { name: /details/i }))
    expect(
      screen.getByText(/commit in advance to what would prove you wrong/i),
    ).toBeInTheDocument()
  })

  it('records an observation', async () => {
    const onObserveTripwire = vi.fn()
    renderTheories({
      theories: [makeTheory({ tripwires: [tripwire()] })],
      onObserveTripwire,
    })
    await userEvent.click(screen.getByRole('button', { name: /details/i }))
    await userEvent.click(screen.getByRole('button', { name: /it happened/i }))

    expect(onObserveTripwire).toHaveBeenCalledWith('tw-1', true)
  })

  it('shows an already-observed tripwire without action buttons', async () => {
    renderTheories({
      theories: [makeTheory({ tripwires: [tripwire({ status: 'observed' })] })],
    })
    await userEvent.click(screen.getByRole('button', { name: /details/i }))

    const block = screen.getByTestId('tripwires')
    expect(within(block).getByText(/Observed/)).toBeInTheDocument()
    expect(within(block).queryByRole('button', { name: /it happened/i })).not.toBeInTheDocument()
  })
})

describe('Theory panel: adversary and tripwire actions', () => {
  it('offers to challenge existing theories', async () => {
    const onChallenge = vi.fn()
    renderTheories({ theories: [makeTheory()], onChallenge })
    await userEvent.click(screen.getByRole('button', { name: /challenge these theories/i }))
    expect(onChallenge).toHaveBeenCalledOnce()
  })

  it('offers to add tripwires', async () => {
    const onGenerateTripwires = vi.fn()
    renderTheories({ theories: [makeTheory()], onGenerateTripwires })
    await userEvent.click(screen.getByRole('button', { name: /add tripwires/i }))
    expect(onGenerateTripwires).toHaveBeenCalledOnce()
  })

  it('hides both actions when there are no theories to attack', () => {
    renderTheories({ onChallenge: vi.fn(), onGenerateTripwires: vi.fn() })
    expect(
      screen.queryByRole('button', { name: /challenge these theories/i }),
    ).not.toBeInTheDocument()
  })
})

describe('Theory panel: outside view', () => {
  it('shows how the theory compares with past cases', () => {
    renderTheories({
      theories: [
        makeTheory({
          outsideViewDelta: -0.28,
          outsideViewNote:
            'This theory is more pessimistic than your own experience: you recalled 2 of 2 comparable cases where the schedule slipped.',
        }),
      ],
    })
    expect(screen.getByTestId('outside-view')).toHaveTextContent(/2 of 2 comparable cases/i)
  })

  it('warns in amber when the theory departs materially', () => {
    const { container } = renderTheories({
      theories: [makeTheory({ outsideViewDelta: -0.4, outsideViewNote: 'Departs.' })],
    })
    expect(
      container.querySelector('[data-testid="outside-view"]')?.className,
    ).toContain('amber')
  })

  it('stays neutral when the theory is consistent with experience', () => {
    const { container } = renderTheories({
      theories: [makeTheory({ outsideViewDelta: 0.03, outsideViewNote: 'Consistent.' })],
    })
    expect(
      container.querySelector('[data-testid="outside-view"]')?.className,
    ).not.toContain('amber')
  })

  it('shows nothing when the outside view has not been run', () => {
    renderTheories({ theories: [makeTheory()] })
    expect(screen.queryByTestId('outside-view')).not.toBeInTheDocument()
  })

  it('offers to run the comparison', async () => {
    const onRunOutsideView = vi.fn()
    renderTheories({ theories: [makeTheory()], onRunOutsideView })
    await userEvent.click(screen.getByRole('button', { name: /compare with past cases/i }))
    expect(onRunOutsideView).toHaveBeenCalledOnce()
  })
})
