/**
 * The decision anchor on the client: wire-format conversion, the decision
 * lens, and the small predicates the graph needs.
 *
 * Kept in one place because two different transforms build `CausalNode`s from
 * the API (GraphScreen and useGraphOperations) and a field added to one and
 * not the other is exactly how a node loses its anchor after an operation.
 */

import { apiGet, apiPost, apiPut } from './api/client.ts'
import type { CausalGraph, CausalNode, DecisionAnchor, DecisionRole } from '../types/graph.ts'

/** The anchor fields of a claim, from the snake_case API shape. */
export function anchorNodeFields(api: Record<string, unknown>): Partial<CausalNode> {
  return {
    origin: (api.origin as string | undefined) ?? 'ai',
    decisionRole: (api.decision_role as DecisionRole | null | undefined) ?? null,
    relevance: (api.relevance as number | null | undefined) ?? null,
    relevanceReason: (api.relevance_reason as string | null | undefined) ?? null,
    bearsOn: (api.bears_on as string[] | null | undefined) ?? null,
    anchorDistance: (api.anchor_distance as number | null | undefined) ?? null,
    effectiveRelevance: (api.effective_relevance as number | null | undefined) ?? null,
    isPeripheral: (api.is_peripheral as boolean | undefined) ?? false,
    // Absent means the server predates the lens: show the node.
    inLens: (api.in_lens as boolean | undefined) ?? true,
  }
}

export function toAnchor(api: unknown): DecisionAnchor | null {
  if (!api || typeof api !== 'object') return null
  const a = api as Record<string, unknown>
  if (typeof a.decision !== 'string' || !a.decision.trim()) return null
  return {
    decision: a.decision,
    options: Array.isArray(a.options) ? (a.options as DecisionAnchor['options']) : [],
    outcomes: Array.isArray(a.outcomes) ? (a.outcomes as DecisionAnchor['outcomes']) : [],
    deadline: typeof a.deadline === 'string' ? a.deadline : '',
    constraints: Array.isArray(a.constraints) ? (a.constraints as string[]) : [],
    status: a.status === 'confirmed' ? 'confirmed' : 'draft',
  }
}

export const isOutcomeNode = (node: CausalNode): boolean =>
  node.origin === 'frame' && node.decisionRole === 'outcome'

/** Whether the graph carries anything the lens could act on. */
export function isAnchored(graph: CausalGraph): boolean {
  return graph.nodes.some((n) => isOutcomeNode(n) || (n.relevance ?? null) !== null)
}

/**
 * The graph as the decision lens shows it: claims near an outcome or judged
 * relevant, plus every peripheral claim — those are the reason the lens is a
 * view and not a filter, so it never hides them.
 *
 * Returns the graph unchanged when it is not anchored.
 */
export function applyDecisionLens(graph: CausalGraph): CausalGraph {
  if (!isAnchored(graph)) return graph
  const visible = new Set(
    graph.nodes.filter((n) => n.inLens !== false || n.isPeripheral).map((n) => n.id),
  )
  return {
    ...graph,
    nodes: graph.nodes.filter((n) => visible.has(n.id)),
    edges: graph.edges.filter((e) => visible.has(e.sourceId) && visible.has(e.targetId)),
    criticalPath: graph.criticalPath.filter((id) => visible.has(id)),
  }
}

// --- API ---

const base = (projectId: string) => `/api/v1/graph/${projectId}/decision-anchor`

export interface AnchorSaveReport {
  outcomes_added?: number
  outcomes_updated?: number
  outcomes_retired?: number
  links_inferred?: number
  claims_rescored?: number
  claims_total?: number
}

export async function fetchDecisionAnchor(projectId: string): Promise<DecisionAnchor | null> {
  const res = await apiGet<{ anchor: unknown }>(base(projectId))
  return toAnchor(res.anchor)
}

export async function draftDecisionAnchor(projectId: string): Promise<DecisionAnchor | null> {
  const res = await apiPost<{ anchor: unknown }>(`${base(projectId)}/draft`, {})
  return toAnchor(res.anchor)
}

export async function saveDecisionAnchor(
  projectId: string,
  anchor: DecisionAnchor,
): Promise<{ anchor: DecisionAnchor | null; report: AnchorSaveReport }> {
  const res = await apiPut<{ anchor: unknown; report: AnchorSaveReport }>(
    base(projectId),
    cleanForSave(anchor),
  )
  return { anchor: toAnchor(res.anchor), report: res.report ?? {} }
}

/** Drop blank rows the editor leaves behind; the server would reject them. */
export function cleanForSave(anchor: DecisionAnchor): DecisionAnchor {
  return {
    ...anchor,
    decision: anchor.decision.trim(),
    options: anchor.options.filter((o) => o.label.trim()),
    outcomes: anchor.outcomes.filter((o) => o.label.trim()),
    constraints: anchor.constraints.map((c) => c.trim()).filter(Boolean),
    deadline: anchor.deadline.trim(),
  }
}
