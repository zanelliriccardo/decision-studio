import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DecisionAnchorCard from '../DecisionAnchorCard.tsx'
import { LanguageProvider } from '../../../i18n/index.tsx'
import type { DecisionAnchor } from '../../../types/graph.ts'

const ANCHOR: DecisionAnchor = {
  decision: 'Whether to commit to Q3',
  options: [{ key: 'O1', label: 'Commit to Q3' }, { key: 'O2', label: 'Commit to Q4' }],
  outcomes: [{ key: 'Y1', label: 'Ship on time', measure: 'within 3 weeks' }],
  deadline: '',
  constraints: [],
  status: 'draft',
}

function renderCard(props: Partial<React.ComponentProps<typeof DecisionAnchorCard>> = {}) {
  return render(
    <LanguageProvider>
      <DecisionAnchorCard anchor={ANCHOR} {...props} />
    </LanguageProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('DecisionAnchorCard', () => {
  it('shows the decision, options and outcomes, and marks a draft', () => {
    renderCard()
    expect(screen.getByText('Whether to commit to Q3')).toBeInTheDocument()
    expect(screen.getByText('Commit to Q4')).toBeInTheDocument()
    expect(screen.getByText('Ship on time')).toBeInTheDocument()
    expect(screen.getByText(/drafted from your objective/i)).toBeInTheDocument()
  })

  it('renders nothing without an anchor, and a spinner while drafting', () => {
    const { container, rerender } = renderCard({ anchor: null })
    expect(container).toBeEmptyDOMElement()
    rerender(
      <LanguageProvider>
        <DecisionAnchorCard anchor={null} loading />
      </LanguageProvider>,
    )
    expect(screen.getByText(/drafting the decision/i)).toBeInTheDocument()
  })

  it('lifts every edit to the parent in intake mode, saving nothing', async () => {
    const onChange = vi.fn()
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    renderCard({ onChange })
    await userEvent.click(screen.getByRole('button', { name: /edit the decision/i }))
    await userEvent.click(screen.getByRole('button', { name: /add an option/i }))
    const inputs = screen.getAllByRole('textbox', { name: /options on the table/i })
    await userEvent.type(inputs[2], 'Delay')
    const last = onChange.mock.calls.at(-1)?.[0] as DecisionAnchor
    expect(last.options.map((o) => o.label)).toEqual(['Commit to Q3', 'Commit to Q4', 'Delay'])
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('saves through the API in summary mode', async () => {
    const saved = { ...ANCHOR, status: 'confirmed', decision: 'Commit to Q3 or not' }
    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ anchor: saved, report: { claims_total: 10, claims_rescored: 10 } }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchSpy)
    const onSaved = vi.fn()
    renderCard({ projectId: 'p1', onSaved })
    await userEvent.click(screen.getByRole('button', { name: /edit the decision/i }))
    const decision = screen.getByRole('textbox', { name: /the decision/i })
    await userEvent.clear(decision)
    await userEvent.type(decision, 'Commit to Q3 or not')
    await userEvent.click(screen.getByRole('button', { name: /save and re-score/i }))

    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/v1/graph/p1/decision-anchor',
      expect.objectContaining({ method: 'PUT' }),
    )
    const body = JSON.parse(fetchSpy.mock.calls[0][1].body as string)
    expect(body.decision).toBe('Commit to Q3 or not')
    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ status: 'confirmed' }))
  })
})
