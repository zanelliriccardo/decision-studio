import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import NodeDetailPanel from '../NodeDetailPanel.tsx'
import EvidencePanel from '../EvidencePanel.tsx'
import { LanguageProvider } from '../../../i18n/index.tsx'
import { makeGraph } from '../../../test/fixtures.ts'
import type { CausalGraph } from '../../../types/graph.ts'

/**
 * Items 1, 2 and 5 in the UI: the two components of a score must both be
 * visible, or splitting them in the backend buys the user nothing.
 */

function renderNode(graph: CausalGraph = makeGraph(), nodeId = 'claim-1') {
  return render(
    <LanguageProvider>
      <NodeDetailPanel
        graph={graph}
        nodeId={nodeId}
        onClose={() => {}}
        onNodeClick={() => {}}
        onEdgeClick={() => {}}
      />
    </LanguageProvider>,
  )
}

function renderEdge(graph: CausalGraph = makeGraph(), edgeId = 'edge-1') {
  return render(
    <LanguageProvider>
      <EvidencePanel
        graph={graph}
        edgeId={edgeId}
        onClose={() => {}}
        onStrengthChange={() => {}}
      />
    </LanguageProvider>,
  )
}

describe('Claim panel: assertion firmness vs truth probability', () => {
  it('shows both numbers, not one blended score', () => {
    renderNode()
    expect(screen.getByText('Asserted')).toBeInTheDocument()
    expect(screen.getByText('Likely true')).toBeInTheDocument()
  })

  it('renders the truth prior distinctly from the asserted confidence', () => {
    const graph = makeGraph()
    graph.nodes[0].confidence = 0.95
    graph.nodes[0].prior = 0.35
    renderNode(graph)

    expect(screen.getByText(/95%/)).toBeInTheDocument()
    expect(screen.getByText(/35%/)).toBeInTheDocument()
  })

  it('warns when a claim is stated far more firmly than the evidence supports', () => {
    const graph = makeGraph()
    graph.nodes[0].confidence = 0.95
    graph.nodes[0].prior = 0.35
    renderNode(graph)

    expect(
      screen.getByText(/stated far more firmly than the evidence supports/i),
    ).toBeInTheDocument()
  })

  it('stays quiet when firmness and truth agree', () => {
    const graph = makeGraph()
    graph.nodes[0].confidence = 0.6
    graph.nodes[0].prior = 0.55
    renderNode(graph)

    expect(
      screen.queryByText(/stated far more firmly/i),
    ).not.toBeInTheDocument()
  })
})

describe('Claim panel: corroboration', () => {
  it('shows how many sources attest a merged fact', () => {
    renderNode()
    expect(screen.getByText(/corroborated by 3 sources/i)).toBeInTheDocument()
  })

  it('explains that repeats were counted once', () => {
    renderNode()
    expect(
      screen.getByText(/stated in several documents, counted once/i),
    ).toBeInTheDocument()
  })

  it('shows nothing for a claim with no duplicates', () => {
    renderNode(makeGraph(), 'claim-2')
    expect(screen.queryByText(/corroborated by/i)).not.toBeInTheDocument()
  })
})

describe('Edge panel: effect vs link confidence', () => {
  it('shows both components', () => {
    renderEdge()
    expect(screen.getByText('Effect')).toBeInTheDocument()
    expect(screen.getByText('Confidence')).toBeInTheDocument()
  })

  it('explains what each component means', () => {
    renderEdge()
    expect(screen.getByText(/how much gets through if the link is real/i)).toBeInTheDocument()
    expect(screen.getByText(/certainty the link exists at all/i)).toBeInTheDocument()
  })

  it('labels the operative weight as the product', () => {
    renderEdge()
    expect(screen.getByText(/effect x confidence/i)).toBeInTheDocument()
  })

  it('distinguishes a weak-but-certain edge from a strong-but-speculative one', () => {
    const weakCertain = makeGraph()
    weakCertain.edges[0].effect = 0.25
    weakCertain.edges[0].linkConfidence = 0.95
    weakCertain.edges[0].blindScored = false
    const { unmount } = renderEdge(weakCertain)
    expect(screen.getByText('0.25')).toBeInTheDocument()
    expect(screen.getByText('0.95')).toBeInTheDocument()
    unmount()

    const strongSpeculative = makeGraph()
    strongSpeculative.edges[0].effect = 0.85
    strongSpeculative.edges[0].linkConfidence = 0.30
    strongSpeculative.edges[0].blindScored = false
    renderEdge(strongSpeculative)
    expect(screen.getByText('0.85')).toBeInTheDocument()
    expect(screen.getByText('0.30')).toBeInTheDocument()
  })
})

describe('Edge panel: blind scoring provenance', () => {
  it('marks a blind-scored edge and shows the author score', () => {
    renderEdge()
    expect(screen.getByText(/blind-scored/i)).toBeInTheDocument()
    expect(screen.getByText(/author scored/i)).toBeInTheDocument()
  })

  it('explains what blind scoring means', () => {
    renderEdge()
    expect(
      screen.getByText(/could not see which argument this serves/i),
    ).toBeInTheDocument()
  })

  it('flags a materially over-scored edge', () => {
    const graph = makeGraph()
    graph.edges[0].inflation = 0.31
    renderEdge(graph)
    expect(screen.getByText(/author over-scored by 0.31/i)).toBeInTheDocument()
  })

  it('does not flag inflation within noise', () => {
    const graph = makeGraph()
    graph.edges[0].inflation = 0.04
    renderEdge(graph)
    expect(screen.queryByText(/over-scored/i)).not.toBeInTheDocument()
  })

  it('shows no blind-score block for an edge that was never rescored', () => {
    const graph = makeGraph()
    graph.edges[0].blindScored = false
    renderEdge(graph)
    expect(screen.queryByText(/blind-scored/i)).not.toBeInTheDocument()
  })
})
