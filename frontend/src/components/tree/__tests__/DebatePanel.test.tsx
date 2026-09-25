import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DebatePanel from '../DebatePanel.tsx'
import { LanguageProvider } from '../../../i18n/index.tsx'
import { makeDebate, makeTheory } from '../../../test/fixtures.ts'

/**
 * The three relations must not look alike. `competing` produces work,
 * `orthogonal` warns about a case a ranked list hides, and `same_story` is a
 * non-result that should stay quiet.
 */

function renderPanel(props: Partial<React.ComponentProps<typeof DebatePanel>> = {}) {
  const defaults: React.ComponentProps<typeof DebatePanel> = {
    debates: [],
    theories: [
      makeTheory({ id: 'theory-1', title: 'Vendor readiness gates integration' }),
      makeTheory({ id: 'theory-2', theoryKey: 'key-2', title: 'Quality is the constraint' }),
    ],
    loading: false,
    running: false,
    promoting: false,
    error: null,
    selectedDebateId: null,
    onSelectDebate: vi.fn(),
    onRun: vi.fn(),
    onPromote: vi.fn(),
    onClose: vi.fn(),
  }
  const merged = { ...defaults, ...props }
  return {
    ...render(
      <LanguageProvider>
        <DebatePanel {...merged} />
      </LanguageProvider>,
    ),
    props: merged,
  }
}

describe('DebatePanel states', () => {
  it('shows loading, error and empty states', () => {
    const a = renderPanel({ loading: true })
    expect(screen.getByTestId('debates-loading')).toBeInTheDocument()
    a.unmount()

    const b = renderPanel({ error: 'Comparison failed' })
    expect(screen.getByRole('alert')).toHaveTextContent('Comparison failed')
    b.unmount()

    renderPanel()
    expect(screen.getByTestId('debates-empty')).toBeInTheDocument()
  })

  it('cannot run with fewer than two theories', () => {
    renderPanel({ theories: [makeTheory()] })
    expect(screen.getByRole('button', { name: /compare theories/i })).toBeDisabled()
    expect(screen.getByTestId('need-two-theories')).toBeInTheDocument()
  })

  it('runs the comparison', async () => {
    const onRun = vi.fn()
    renderPanel({ onRun })
    await userEvent.click(screen.getByRole('button', { name: /compare theories/i }))
    expect(onRun).toHaveBeenCalledOnce()
  })
})

describe('DebatePanel: competing pairs', () => {
  it('names both theories and shows the crux', () => {
    renderPanel({ debates: [makeDebate()] })
    const card = screen.getByTestId('debate-card')
    expect(within(card).getByText(/vendor readiness gates integration/i)).toBeInTheDocument()
    expect(within(card).getByText(/quality is the constraint/i)).toBeInTheDocument()
    expect(within(card).getByText(/both accept the integration window/i)).toBeInTheDocument()
  })

  it('shows the discriminator with its horizon', () => {
    renderPanel({ debates: [makeDebate()] })
    const block = screen.getByTestId('discriminator')
    expect(within(block).getByText(/staging defect rate/i)).toBeInTheDocument()
    expect(within(block).getByText(/21 days/i)).toBeInTheDocument()
  })

  it('reports the computed overlap as a percentage', () => {
    renderPanel({ debates: [makeDebate({ overlapJaccard: 0.29 })] })
    expect(screen.getByText(/shared links: 29%/i)).toBeInTheDocument()
  })

  it('warns when nothing separates them in time', () => {
    renderPanel({
      debates: [makeDebate({ discriminatorFeasible: false, discriminator: null })],
    })
    expect(screen.getByTestId('no-discriminator')).toHaveTextContent(
      /pick the option that holds up either way/i,
    )
    expect(screen.queryByTestId('discriminator')).not.toBeInTheDocument()
  })
})

describe('DebatePanel: orthogonal pairs', () => {
  it('warns that both may hold — the case a ranked list hides', () => {
    renderPanel({
      debates: [makeDebate({ relation: 'orthogonal', bothPossible: true })],
    })
    expect(screen.getByTestId('both-possible')).toHaveTextContent(
      /exposure is greater than either suggests/i,
    )
  })

  it('labels the relation as different things, not disagreement', () => {
    renderPanel({ debates: [makeDebate({ relation: 'orthogonal' })] })
    expect(screen.getByText('Different things')).toBeInTheDocument()
  })
})

describe('DebatePanel: restatements stay quiet', () => {
  it('collapses a same-story pair to one line', () => {
    renderPanel({
      debates: [makeDebate({ relation: 'same_story', overlapJaccard: 1.0 })],
    })
    expect(screen.getByTestId('debate-same-story')).toHaveTextContent(
      /same theory in two wordings/i,
    )
    expect(screen.queryByTestId('debate-card')).not.toBeInTheDocument()
  })

  it('groups restatements below the substantive comparisons', () => {
    renderPanel({
      debates: [
        makeDebate({ id: 'd1', relation: 'same_story' }),
        makeDebate({ id: 'd2', relation: 'competing' }),
      ],
    })
    expect(screen.getByTestId('debate-card')).toBeInTheDocument()
    expect(screen.getByText(/restatements \(1\)/i)).toBeInTheDocument()
  })
})

describe('DebatePanel: promotion', () => {
  it('asks for confirmation before creating dated commitments', async () => {
    const onPromote = vi.fn()
    renderPanel({ debates: [makeDebate()], onPromote })

    await userEvent.click(screen.getByRole('button', { name: /add as a tripwire/i }))

    expect(screen.getByText(/dated commitment on both theories/i)).toBeInTheDocument()
    expect(onPromote).not.toHaveBeenCalled()
  })

  it('promotes once confirmed', async () => {
    const onPromote = vi.fn()
    renderPanel({ debates: [makeDebate()], onPromote })

    await userEvent.click(screen.getByRole('button', { name: /add as a tripwire/i }))
    await userEvent.click(screen.getByRole('button', { name: /yes, add it/i }))

    expect(onPromote).toHaveBeenCalledWith('debate-1')
  })

  it('can back out', async () => {
    const onPromote = vi.fn()
    renderPanel({ debates: [makeDebate()], onPromote })

    await userEvent.click(screen.getByRole('button', { name: /add as a tripwire/i }))
    await userEvent.click(screen.getByRole('button', { name: /^cancel$/i }))

    expect(onPromote).not.toHaveBeenCalled()
  })

  it('shows an already-promoted discriminator as done', () => {
    renderPanel({
      debates: [makeDebate({ promotedTripwireAt: '2026-07-26T00:00:00Z' })],
    })
    expect(screen.getByText(/already added as a tripwire/i)).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /add as a tripwire/i }),
    ).not.toBeInTheDocument()
  })

  it('offers no promotion when nothing separates the two', () => {
    renderPanel({
      debates: [makeDebate({ discriminatorFeasible: false, discriminator: null })],
    })
    expect(
      screen.queryByRole('button', { name: /add as a tripwire/i }),
    ).not.toBeInTheDocument()
  })
})

describe('DebatePanel: highlighting', () => {
  it('hands the comparison to the caller', async () => {
    const onSelectDebate = vi.fn()
    const debate = makeDebate()
    renderPanel({ debates: [debate], onSelectDebate })

    await userEvent.click(screen.getByRole('button', { name: /highlight both paths/i }))

    expect(onSelectDebate).toHaveBeenCalledWith(debate)
  })

  it('clears the highlight when toggled off', async () => {
    const onSelectDebate = vi.fn()
    renderPanel({ debates: [makeDebate()], selectedDebateId: 'debate-1', onSelectDebate })

    await userEvent.click(screen.getByRole('button', { name: /clear highlight/i }))

    expect(onSelectDebate).toHaveBeenCalledWith(null)
  })
})
