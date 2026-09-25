import { Radar, Target } from 'lucide-react'
import { useT } from '../../i18n/index.tsx'
import { isOutcomeNode } from '../../lib/decisionAnchor.ts'
import type { CausalNode, DecisionAnchor } from '../../types/graph.ts'

/**
 * How one claim bears on the decision: its role, the model's relevance score,
 * the options and outcomes it affects, and its causal distance to an outcome.
 *
 * Renders nothing on an unanchored claim — an empty section would suggest a
 * judgement was made and came back blank.
 */
export default function NodeAnchorSection({
  node,
  anchor,
}: {
  node: CausalNode
  anchor: DecisionAnchor | null | undefined
}) {
  const { t } = useT()

  if (isOutcomeNode(node)) {
    return (
      <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-300 flex items-center gap-2">
        <Target className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
        {t.anchor.outcomeNode}
      </div>
    )
  }

  const hasAnything =
    node.decisionRole || node.relevance != null || node.anchorDistance != null || node.isPeripheral
  if (!hasAnything) return null

  const label = (key: string): string => {
    const option = anchor?.options.find((o) => o.key === key)
    const outcome = anchor?.outcomes.find((o) => o.key === key)
    return option?.label ?? outcome?.label ?? key
  }

  return (
    <div className="space-y-1.5" data-testid="node-anchor-section">
      <label className="text-xs font-medium text-text-muted block">{t.anchor.sectionTitle}</label>
      {node.isPeripheral && (
        <p className="text-[11px] text-violet-300 flex items-start gap-1.5 leading-relaxed">
          <Radar className="w-3 h-3 mt-0.5 shrink-0" aria-hidden="true" />
          {t.anchor.peripheralHint}
        </p>
      )}
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        {node.decisionRole && (
          <>
            <dt className="text-text-muted">{t.anchor.role}</dt>
            <dd className="text-text-secondary">{t.anchor.roles[node.decisionRole]}</dd>
          </>
        )}
        {node.relevance != null && (
          <>
            <dt className="text-text-muted">{t.anchor.relevance}</dt>
            <dd className="text-text-secondary">{Math.round(node.relevance * 100)}%</dd>
          </>
        )}
        <dt className="text-text-muted">{t.anchor.distance}</dt>
        <dd className="text-text-secondary">
          {node.anchorDistance != null
            ? t.anchor.hops.replace('{n}', String(node.anchorDistance))
            : t.anchor.noPath}
        </dd>
        {node.bearsOn && node.bearsOn.length > 0 && (
          <>
            <dt className="text-text-muted">{t.anchor.bearsOn}</dt>
            <dd className="text-text-secondary">
              {node.bearsOn.map((key) => `${key} ${label(key)}`).join(' · ')}
            </dd>
          </>
        )}
      </dl>
      {node.relevanceReason && (
        <p className="text-[11px] text-text-muted italic leading-relaxed">{node.relevanceReason}</p>
      )}
    </div>
  )
}
