import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import DivergenceStabilityBadge from '../DivergenceStabilityBadge.tsx'
import { LanguageProvider } from '../../../i18n/index.tsx'
import type { NodeDivergenceStability } from '../../../types/api.ts'

/**
 * Item 4 in the UI: a difference between two model-produced estimates is only a
 * finding if it survives noise on those estimates. The comparison bar has to
 * say so, or the number goes in front of an executive unqualified.
 */

function stabilityRow(
  overrides: Partial<NodeDivergenceStability> = {},
): NodeDivergenceStability {
  return {
    node_id: 'claim-1',
    belief_a: 0.62,
    belief_b: 0.44,
    delta: 0.18,
    agreement: 0.97,
    material_rate: 0.88,
    robust: true,
    ...overrides,
  }
}

type BadgeProps = React.ComponentProps<typeof DivergenceStabilityBadge>

function makeProps(overrides: Partial<BadgeProps> = {}): BadgeProps {
  return {
    divergentCount: 2,
    stability: [
      stabilityRow(),
      stabilityRow({ node_id: 'claim-2', robust: false, agreement: 0.55 }),
    ],
    robustNodeIds: ['claim-1'],
    simulationRuns: 200,
    ...overrides,
  }
}

function renderComparison(props: BadgeProps) {
  return render(
    <LanguageProvider>
      <DivergenceStabilityBadge {...props} />
    </LanguageProvider>,
  )
}

describe('Comparison stability', () => {
  it('reports how many divergences survived the simulation', () => {
    renderComparison(makeProps())
    expect(screen.getByTestId('robust-divergence-count')).toHaveTextContent(
      '1/2 survive noise',
    )
  })

  it('explains what the number means, including the run count', () => {
    renderComparison(makeProps())
    expect(screen.getByTestId('robust-divergence-count')).toHaveAttribute(
      'title',
      expect.stringContaining('200 simulations'),
    )
  })

  it('warns in amber when some divergences did not survive', () => {
    const el = renderComparison(makeProps()).container.querySelector(
      '[data-testid="robust-divergence-count"]',
    )
    expect(el?.className).toContain('amber')
  })

  it('is not alarming when every divergence held up', () => {
    const props = makeProps({
      divergentCount: 1,
      stability: [stabilityRow()],
      robustNodeIds: ['claim-1'],
    })
    const el = renderComparison(props).container.querySelector(
      '[data-testid="robust-divergence-count"]',
    )
    expect(el?.className).toContain('confidence-high')
  })

  it('falls back to counting rows when the server omits the id list', () => {
    renderComparison(makeProps({ robustNodeIds: undefined }))
    expect(screen.getByTestId('robust-divergence-count')).toHaveTextContent('1/2')
  })

  it('shows nothing when the server did not compute stability', () => {
    renderComparison(makeProps({ stability: undefined, robustNodeIds: undefined }))
    expect(screen.queryByTestId('robust-divergence-count')).not.toBeInTheDocument()
  })

  it('renders nothing at all when there is no stability data', () => {
    const { container } = renderComparison(
      makeProps({ stability: [], robustNodeIds: undefined }),
    )
    expect(container).toBeEmptyDOMElement()
  })
})
