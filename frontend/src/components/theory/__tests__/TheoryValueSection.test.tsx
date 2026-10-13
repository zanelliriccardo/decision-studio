import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import TheoryValueSection from '../TheoryValueSection.tsx'
import { LanguageProvider } from '../../../i18n/index.tsx'
import { makeTheory } from '../../../test/fixtures.ts'
import type { DecisionAnchor } from '../../../types/graph.ts'

const ANCHOR: DecisionAnchor = {
  decision: 'Whether to commit to Q3', deadline: '', constraints: [], status: 'confirmed',
  options: [{ key: 'O1', label: 'Commit to Q3' }, { key: 'O2', label: 'Commit to Q4' }],
  outcomes: [{ key: 'Y1', label: 'Ship on time', measure: '' }],
}

const json = (body: unknown) =>
  new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })

afterEach(() => vi.unstubAllGlobals())

function renderSection(overrides = {}) {
  const theory = makeTheory({
    optionKey: 'O1', predictedEffect: 'threatens', outcomeKeys: ['Y1'], reachesOutcome: true,
    conviction: null, convictionPrior: null, ...overrides,
  })
  render(
    <LanguageProvider>
      <TheoryValueSection theory={theory} anchor={ANCHOR} />
    </LanguageProvider>,
  )
  return theory
}

describe('TheoryValueSection', () => {
  it('names the option and what the theory predicts for it', () => {
    renderSection()
    expect(screen.getByText('Commit to Q3')).toBeInTheDocument()
    expect(screen.getByTestId('predicted-effect')).toHaveTextContent(/threatens the outcome · Y1/)
    expect(screen.queryByTestId('no-outcome')).not.toBeInTheDocument()
  })

  it('says when the chain never reaches an outcome', () => {
    renderSection({ reachesOutcome: false })
    expect(screen.getByTestId('no-outcome')).toBeInTheDocument()
  })

  it('shows conviction apart from confidence, with where it started', () => {
    renderSection({ conviction: 0.2, convictionPrior: 0.5 })
    expect(screen.getByTestId('conviction-value')).toHaveTextContent('20%')
    expect(screen.getByText(/you said 50%/)).toBeInTheDocument()
  })

  it('elicits a prior with lottery questions and saves it', async () => {
    const fetchSpy = vi.fn().mockResolvedValue(json({
      theory_key: 'k', prior: 0.69, prior_method: 'lottery', current: 0.69, steps: [],
    }))
    vi.stubGlobal('fetch', fetchSpy)
    const theory = renderSection()
    await userEvent.click(screen.getByRole('button', { name: /state your conviction/i }))
    for (const choice of [/win if this theory holds/i, /win a draw/i, /win if this theory holds/i, /win if this theory holds/i]) {
      await userEvent.click(screen.getByRole('button', { name: choice }))
    }
    await userEvent.click(screen.getByRole('button', { name: /^save$/i }))

    const [url, init] = fetchSpy.mock.calls[0]
    expect(url).toBe(`/api/v1/graph/${theory.projectId}/theory-keys/${theory.theoryKey}/conviction`)
    const body = JSON.parse(init.body as string)
    expect(body.method).toBe('lottery')
    expect(body.value).toBeGreaterThan(0.63)
    expect(body.value).toBeLessThan(0.75)
    expect(body.note).toMatch(/^lottery: 50%: theory/)
    expect(await screen.findByTestId('conviction-value')).toHaveTextContent('69%')
  })
})
