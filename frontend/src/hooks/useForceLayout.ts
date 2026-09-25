import { useEffect, useRef, useMemo, useCallback } from 'react'
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCollide,
  forceX,
  forceY,
  type Simulation,
  type SimulationNodeDatum,
  type SimulationLinkDatum,
} from 'd3-force'
import type { CausalGraph, CausalNode, CausalEdge } from '../types/graph.ts'
import { computeDepths } from '../lib/graphUtils.ts'

// --- Constants ---

const DEPTH_BAND_HEIGHT = 120
const CONVERGENCE_SCALE = 1.3

// --- Types ---

export interface ForceNode extends SimulationNodeDatum {
  id: string
  data: CausalNode
  x: number
  y: number
  fx: number | null
  fy: number | null
  depth: number
  parentIds: string[]
  childIds: string[]
  isConvergencePoint: boolean
  vx: number
  vy: number
}

export interface ForceLink extends SimulationLinkDatum<ForceNode> {
  source: ForceNode
  target: ForceNode
  edges: CausalEdge[]
  primaryEdge: CausalEdge
  maxStrength: number
  maxEvidenceScore: number
  isConvergenceEdge: boolean
  isBundled: boolean
}

export interface ForceLayoutResult {
  nodes: ForceNode[]
  links: ForceLink[]
  rootId: string
  maxDepth: number
}

// --- Hook ---

export function useForceLayout(
  graph: CausalGraph | null,
  options: {
    depthLimit?: number | null
    collapsedNodes?: Set<string>
    width: number
    height: number
    onTick?: () => void
  },
): { layout: ForceLayoutResult | null; reheat: () => void } {
  const { depthLimit = null, collapsedNodes, width, height, onTick } = options
  const simulationRef = useRef<Simulation<ForceNode, ForceLink> | null>(null)
  const onTickRef = useRef(onTick)
  onTickRef.current = onTick
  // Use refs for width/height so topology & simulation don't restart on resize
  // A boolean rather than the width itself: the simulation must be created
  // once the container has a size, but re-creating it on every pixel of a
  // resize would throw away the settled layout each time a panel opens.
  //
  // This flips false→true exactly once per mount, provided the size source is
  // stable. `useResizeObserver` guarantees that by suppressing sub-pixel and
  // no-op updates — without it, the several observer callbacks that fire while
  // a page settles each rebuilt the simulation, and the graph visibly
  // re-animated three or four times before coming to rest.
  const hasSize = width > 0 && height > 0
  const widthRef = useRef(width)
  const heightRef = useRef(height)
  widthRef.current = width
  heightRef.current = height

  // Compute topology (memoized — width/height excluded to avoid restart on panel open/close)
  const topology = useMemo(() => {
    if (!graph || graph.nodes.length === 0) return null

    const { depths, parentIds, childIds, rootId } = computeDepths(graph.nodes, graph.edges)

    // Which nodes to draw.
    //
    // This used to walk out from `rootId` alone — a single root chosen as
    // `roots[0]`, which is the first node in extraction order and has nothing
    // to do with connectivity. Anything not reachable from that one node was
    // silently absent. On a typical graph most claims have no incoming edge, so
    // there are dozens of roots and most of them are isolated: picking the
    // first one usually meant drawing exactly one node out of thirty.
    //
    // The invariant now is simply that **every node is drawn** unless something
    // explicitly hides it — a depth limit or a collapsed ancestor. Traversal
    // still happens, because collapse and depth are inherited down the graph
    // and can only be worked out by walking it, but it starts from every root
    // rather than one, and anything still unreached afterwards is added
    // directly. A node cannot fall off the canvas by accident.
    const visibleNodeIds = new Set<string>()
    const collapsedSet = collapsedNodes ?? new Set<string>()

    const bfsQueue: string[] = graph.nodes
      .filter((n) => (parentIds.get(n.id) ?? []).length === 0)
      .map((n) => n.id)
    // A graph made entirely of cycles has no root at all; without this it would
    // draw nothing, which is the failure being fixed.
    if (bfsQueue.length === 0 && graph.nodes.length > 0) {
      bfsQueue.push(...graph.nodes.map((n) => n.id))
    }
    const visited = new Set<string>()

    while (bfsQueue.length > 0) {
      const id = bfsQueue.shift()!
      if (visited.has(id)) continue
      visited.add(id)

      const d = depths.get(id) ?? 0
      if (depthLimit !== null && d > depthLimit) continue

      visibleNodeIds.add(id)

      if (collapsedSet.has(id) && id !== rootId) continue

      for (const childId of childIds.get(id) ?? []) {
        if (!visited.has(childId)) {
          bfsQueue.push(childId)
        }
      }
    }

    // Anything the walk never reached: nodes in a cycle with no root above
    // them, or nodes whose edges were pruned away. They are part of the graph,
    // so they belong on the canvas.
    //
    // `visited` is the test, not `visibleNodeIds`. A node the walk reached and
    // then excluded on depth is in `visited` but not in `visibleNodeIds`, and
    // checking the latter would quietly undo the depth limit.
    for (const node of graph.nodes) {
      if (visited.has(node.id)) continue
      const d = depths.get(node.id) ?? 0
      if (depthLimit !== null && d > depthLimit) continue
      visibleNodeIds.add(node.id)
    }

    const nodeMap = new Map(graph.nodes.map((n) => [n.id, n]))
    const maxDepth = Math.max(...[...visibleNodeIds].map((id) => depths.get(id) ?? 0), 0)

    // Count nodes at each depth for initial x spread
    const depthBuckets = new Map<number, string[]>()
    for (const id of visibleNodeIds) {
      const d = depths.get(id) ?? 0
      const bucket = depthBuckets.get(d) ?? []
      bucket.push(id)
      depthBuckets.set(d, bucket)
    }

    const forceNodes: ForceNode[] = []
    for (const id of visibleNodeIds) {
      const nodeData = nodeMap.get(id)
      if (!nodeData) continue

      const d = depths.get(id) ?? 0
      const bucket = depthBuckets.get(d) ?? [id]
      const idxInBucket = bucket.indexOf(id)
      const spreadX = (idxInBucket - (bucket.length - 1) / 2) * 100

      const pIds = (parentIds.get(id) ?? []).filter((pid) => visibleNodeIds.has(pid))
      const cIds = (childIds.get(id) ?? []).filter((cid) => visibleNodeIds.has(cid))
      const isConvergence = pIds.length > 1

      // Spread initial positions more to give the simulation a better start
      const jitterX = (Math.random() - 0.5) * 200
      const jitterY = (Math.random() - 0.5) * 100

      forceNodes.push({
        id,
        data: nodeData,
        x: spreadX + widthRef.current / 2 + jitterX,
        y: d * DEPTH_BAND_HEIGHT + 80 + jitterY,
        fx: null,
        fy: null,
        vx: 0,
        vy: 0,
        depth: d,
        parentIds: pIds,
        childIds: cIds,
        isConvergencePoint: isConvergence,
      })
    }

    const nodeIdSet = new Set(forceNodes.map((n) => n.id))
    const forceNodeMap = new Map(forceNodes.map((n) => [n.id, n]))

    // Group edges by source->target pair, then create one ForceLink per group
    const edgeGroups = new Map<string, CausalEdge[]>()
    for (const edge of graph.edges) {
      if (!nodeIdSet.has(edge.sourceId) || !nodeIdSet.has(edge.targetId)) continue
      const key = `${edge.sourceId}->${edge.targetId}`
      const group = edgeGroups.get(key)
      if (group) group.push(edge)
      else edgeGroups.set(key, [edge])
    }

    const forceLinks: ForceLink[] = []
    for (const [, groupEdges] of edgeGroups) {
      const sourceNode = forceNodeMap.get(groupEdges[0].sourceId)!
      const targetNode = forceNodeMap.get(groupEdges[0].targetId)!
      const primaryEdge = groupEdges.reduce((best, e) => e.strength > best.strength ? e : best, groupEdges[0])
      forceLinks.push({
        source: sourceNode,
        target: targetNode,
        edges: groupEdges,
        primaryEdge,
        maxStrength: Math.max(...groupEdges.map((e) => e.strength)),
        maxEvidenceScore: Math.max(...groupEdges.map((e) => e.evidenceScore)),
        isConvergenceEdge: targetNode.isConvergencePoint,
        isBundled: groupEdges.length > 1,
      })
    }

    return { forceNodes, forceLinks, rootId, maxDepth }
  }, [graph, depthLimit, collapsedNodes])

  // Stable layout result — only changes when topology changes
  const layout = useMemo<ForceLayoutResult | null>(() => {
    if (!topology) return null
    return {
      nodes: topology.forceNodes,
      links: topology.forceLinks,
      rootId: topology.rootId,
      maxDepth: topology.maxDepth,
    }
  }, [topology])

  // Run simulation — only restarts when topology changes
  useEffect(() => {
    // The guard below is why `hasSize` is a dependency of this effect. Without
    // it, a topology that arrives before the container has been measured is
    // dropped here and never retried: the simulation is never created, so every
    // node keeps its seeded position and the graph shows a single overlapping
    // cluster. Which is what "30 nodes, I can see one" looks like.
    if (!topology || widthRef.current === 0 || heightRef.current === 0) {
      if (simulationRef.current) {
        simulationRef.current.stop()
        simulationRef.current = null
      }
      return
    }

    const { forceNodes, forceLinks } = topology

    // Stop old simulation
    if (simulationRef.current) {
      simulationRef.current.stop()
    }

    // Scale forces based on graph density to avoid overlapping nodes
    const nodeCount = forceNodes.length
    const edgeCount = forceLinks.length
    const density = nodeCount > 1 ? edgeCount / nodeCount : 0
    const scaleFactor = Math.max(1, Math.sqrt(nodeCount / 10))
    const linkDist = Math.round(80 * scaleFactor)
    const chargeStr = Math.round(-200 * scaleFactor)
    const chargeMax = Math.round(400 * scaleFactor)

    const sim = forceSimulation<ForceNode>(forceNodes)
      .force(
        'link',
        forceLink<ForceNode, ForceLink>(forceLinks)
          .id((d) => d.id)
          .distance(linkDist)
          .strength(density > 2 ? 0.15 : 0.3),
      )
      .force(
        'charge',
        forceManyBody<ForceNode>()
          .strength(chargeStr)
          .distanceMax(chargeMax),
      )
      .force(
        'collide',
        forceCollide<ForceNode>()
          .radius((d) => {
            const w = 160
            const h = 60
            if (d.data.logicGate === 'and') {
              // Diamond diagonal
              return Math.sqrt((w / 2) ** 2 + (h / 2) ** 2) + 4
            }
            const base = (w + h) / 4 + 4
            return d.isConvergencePoint ? base * CONVERGENCE_SCALE : base
          }),
      )
      .force(
        'depthY',
        forceY<ForceNode>()
          .y((d) => d.depth * DEPTH_BAND_HEIGHT + 80)
          .strength(0.35),
      )
      .force(
        'centerX',
        forceX<ForceNode>()
          .x(widthRef.current / 2)
          .strength(0.12),
      )
      .alpha(1)
      // Settle in roughly 130 ticks rather than 350.
      //
      // d3's default of 0.0228 is tuned for small graphs, where a long cooling
      // period is a pleasant unfolding. On several hundred nodes it is a minute
      // of drift that reads as the graph never finishing — and the extra ticks
      // buy very little, because the layout is substantially in place well
      // before alpha runs out.
      .alphaDecay(0.035)
      .alphaMin(0.005)
      // Higher friction, so nodes glide less on the way to their positions.
      .velocityDecay(0.45)
      .on('tick', () => {
        onTickRef.current?.()
      })

    simulationRef.current = sim

    return () => {
      sim.stop()
    }
  }, [topology, hasSize])

  // Update centering force target when width changes (e.g. panel open/close).
  // Do NOT restart the simulation — nodes should stay exactly where they are.
  useEffect(() => {
    const sim = simulationRef.current
    if (!sim || width === 0) return
    const centerForce = sim.force('centerX') as ReturnType<typeof forceX<ForceNode>> | undefined
    if (centerForce) {
      centerForce.x(width / 2)
    }
  }, [width])

  // Expose reheat for node dragging — brief burst, then settle
  const reheat = useCallback(() => {
    const sim = simulationRef.current
    if (sim) sim.alphaTarget(0).alpha(0.3).restart()
  }, [])

  return { layout, reheat }
}

export { DEPTH_BAND_HEIGHT, CONVERGENCE_SCALE }
