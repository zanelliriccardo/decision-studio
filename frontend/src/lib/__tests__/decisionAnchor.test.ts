import { describe, expect, it } from 'vitest'
import { makeGraph } from '../../test/fixtures.ts'
import {
  anchorNodeFields,
  applyDecisionLens,
  cleanForSave,
  isAnchored,
  toAnchor,
} from '../decisionAnchor.ts'
import type { CausalGraph, CausalNode } from '../../types/graph.ts'

function anchoredGraph(): CausalGraph {
  const base = makeGraph()
  const [a, b] = base.nodes
  const outcome: CausalNode = {
    ...a, id: 'Y1', text: 'Success criterion met: ship on time',
    origin: 'frame', decisionRole: 'outcome', relevance: 1, anchorDistance: 0, inLens: true,
  }
  const nodes: CausalNode[] = [
    { ...a, relevance: 0.9, anchorDistance: 1, inLens: true },
    { ...b, relevance: 0.0, anchorDistance: null, inLens: false },
    { ...b, id: 'far', relevance: 0.1, anchorDistance: 5, inLens: false, isPeripheral: true },
    outcome,
  ]
  return {
    ...base,
    nodes,
    edges: [
      { ...base.edges[0], id: 'e1', sourceId: 'claim-1', targetId: 'Y1' },
      { ...base.edges[0], id: 'e2', sourceId: 'claim-1', targetId: 'claim-2' },
    ],
    criticalPath: ['claim-1', 'claim-2'],
  }
}

describe('applyDecisionLens', () => {
  it('leaves an unanchored graph untouched', () => {
    const graph = makeGraph()
    expect(isAnchored(graph)).toBe(false)
    expect(applyDecisionLens(graph)).toBe(graph)
  })

  it('keeps lens claims and every peripheral claim, and drops dangling edges', () => {
    const lensed = applyDecisionLens(anchoredGraph())
    expect(lensed.nodes.map((n) => n.id)).toEqual(['claim-1', 'far', 'Y1'])
    expect(lensed.edges.map((e) => e.id)).toEqual(['e1'])
    expect(lensed.criticalPath).toEqual(['claim-1'])
  })
})

describe('wire conversion', () => {
  it('defaults a node from an older server to visible and unanchored', () => {
    expect(anchorNodeFields({})).toMatchObject({
      origin: 'ai', relevance: null, inLens: true, isPeripheral: false,
    })
  })

  it('maps snake_case anchor fields', () => {
    expect(anchorNodeFields({
      origin: 'frame', decision_role: 'outcome', relevance: 1, bears_on: ['Y1'],
      anchor_distance: 0, is_peripheral: false, in_lens: true,
    })).toMatchObject({
      origin: 'frame', decisionRole: 'outcome', bearsOn: ['Y1'], anchorDistance: 0,
    })
  })

  it('rejects an anchor without a decision', () => {
    expect(toAnchor(null)).toBeNull()
    expect(toAnchor({ decision: '  ' })).toBeNull()
    expect(toAnchor({ decision: 'd', status: 'confirmed' })).toMatchObject({
      decision: 'd', options: [], outcomes: [], status: 'confirmed',
    })
  })

  it('drops blank rows before saving', () => {
    const cleaned = cleanForSave({
      decision: ' d ', deadline: ' ', status: 'draft',
      options: [{ key: 'O1', label: 'A' }, { key: '', label: '  ' }],
      outcomes: [{ key: '', label: '', measure: '' }],
      constraints: ['', ' budget '],
    })
    expect(cleaned).toEqual({
      decision: 'd', deadline: '', status: 'draft',
      options: [{ key: 'O1', label: 'A' }], outcomes: [], constraints: ['budget'],
    })
  })
})
