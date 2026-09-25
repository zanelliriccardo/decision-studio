import { describe, expect, it } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useForceLayout } from '../useForceLayout.ts'
import type { CausalGraph, CausalNode, CausalEdge } from '../../types/graph.ts'

/**
 * One invariant, and it is the whole file: **every node in the graph is laid
 * out**, unless a depth limit or a collapsed ancestor explicitly hides it.
 *
 * This exists because it was violated for a long time in a way that was easy to
 * miss. The layout walked out from a single root — `roots[0]`, the first node in
 * extraction order — and drew only what that walk reached. On a typical graph
 * most claims have no incoming edge, so there are dozens of roots and most are
 * isolated; picking the first one routinely meant drawing one node out of
 * thirty. The sidebar still showed depths for every node, because those are
 * computed before this filter, which made the canvas look broken rather than
 * empty and sent the search in the wrong direction.
 */

function node(id: string, orderIndex = 0): CausalNode {
  return {
    id,
    text: `Claim ${id}`,
    type: 'FACT',
    confidence: 0.8,
    belief: 0.7,
    orderIndex,
    depth: 0,
    isCriticalPath: false,
    logicGate: 'or',
    // Through `unknown`: the fixture supplies only the fields the layout reads,
    // and listing the rest would be noise that hides which ones matter here.
  } as unknown as CausalNode
}

function edge(sourceId: string, targetId: string): CausalEdge {
  return {
    id: `${sourceId}->${targetId}`,
    sourceId,
    targetId,
    strength: 0.6,
    evidenceScore: 0.5,
    mechanism: 'because',
    causalType: 'direct',
  } as unknown as CausalEdge
}

function graphOf(nodes: CausalNode[], edges: CausalEdge[]): CausalGraph {
  return { nodes, edges } as CausalGraph
}

function layoutOf(graph: CausalGraph, depthLimit: number | null = null) {
  const { result } = renderHook(() =>
    useForceLayout(graph, {
      depthLimit,
      collapsedNodes: new Set<string>(),
      width: 1200,
      height: 800,
    }),
  )
  return result.current.layout
}

describe('useForceLayout — every node reaches the canvas', () => {
  it('lays out nodes that no root can reach', () => {
    // The reported case: 30 claims, 17 edges, one visible node. The chain sits
    // in the middle of the order, so the first root is an isolated claim.
    const nodes = Array.from({ length: 30 }, (_, i) => node(`n${i}`, i))
    const edges = Array.from({ length: 17 }, (_, i) => edge(`n${i + 5}`, `n${i + 6}`))

    expect(layoutOf(graphOf(nodes, edges))?.nodes).toHaveLength(30)
  })

  it('lays out a graph with no edges at all', () => {
    const nodes = Array.from({ length: 8 }, (_, i) => node(`n${i}`, i))
    expect(layoutOf(graphOf(nodes, []))?.nodes).toHaveLength(8)
  })

  it('lays out a graph that is entirely a cycle', () => {
    // No node has zero parents, so there is no root to start from.
    const nodes = Array.from({ length: 5 }, (_, i) => node(`c${i}`, i))
    const edges = nodes.map((n, i) => edge(n.id, nodes[(i + 1) % 5].id))

    expect(layoutOf(graphOf(nodes, edges))?.nodes).toHaveLength(5)
  })

  it('lays out several disconnected components', () => {
    const nodes = ['a1', 'a2', 'b1', 'b2', 'c1'].map((id, i) => node(id, i))
    const edges = [edge('a1', 'a2'), edge('b1', 'b2')]

    const laid = layoutOf(graphOf(nodes, edges))?.nodes.map((n) => n.id) ?? []
    expect(laid.sort()).toEqual(['a1', 'a2', 'b1', 'b2', 'c1'])
  })

  it('keeps the links it was given', () => {
    const nodes = Array.from({ length: 6 }, (_, i) => node(`n${i}`, i))
    const edges = [edge('n0', 'n1'), edge('n1', 'n2'), edge('n4', 'n5')]

    expect(layoutOf(graphOf(nodes, edges))?.links).toHaveLength(3)
  })

  it('still honours an explicit depth limit', () => {
    /** The invariant is "nothing disappears by accident" — not "nothing can be
        hidden". A depth limit is a deliberate act and must still work. */
    const nodes = ['r', 'd1', 'd2'].map((id, i) => node(id, i))
    const edges = [edge('r', 'd1'), edge('d1', 'd2')]

    const laid = layoutOf(graphOf(nodes, edges), 1)?.nodes.map((n) => n.id) ?? []
    expect(laid).not.toContain('d2')
    expect(laid).toContain('r')
  })
})
