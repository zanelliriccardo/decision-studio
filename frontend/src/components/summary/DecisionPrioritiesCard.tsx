import { useState } from 'react'
import { SlidersHorizontal } from 'lucide-react'
import { toast } from 'sonner'
import { useT } from '../../i18n/index.tsx'
import {
  setDecisionPriorities,
  type DecisionPriority,
  type Importance,
  type OptionComparison,
} from '../../lib/api/reasoning.ts'

const LEVELS: Importance[] = ['critical', 'high', 'medium', 'low', 'none']

/**
 * How much each success criterion matters to the decider.
 *
 * Changes only the weighted view (and its robustness and drivers), never the
 * causal map: the server stores priorities apart from the anchor and returns
 * the comparison recomputed under them.
 */
export default function DecisionPrioritiesCard({
  projectId,
  priorities,
  onChanged,
}: {
  projectId: string
  priorities: DecisionPriority[]
  onChanged: (comparison: OptionComparison) => void
}) {
  const { t } = useT()
  const [saving, setSaving] = useState<string | null>(null)

  if (priorities.length === 0) return null

  async function choose(key: string, importance: Importance) {
    // Only what the decider has set is sent; the rest stays at the default.
    const next: Record<string, Importance> = {}
    for (const p of priorities) {
      if (!p.isDefault) next[p.key] = p.importance
    }
    next[key] = importance
    setSaving(key)
    try {
      onChanged(await setDecisionPriorities(projectId, next))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t.decisionView.saveFailed)
    } finally {
      setSaving(null)
    }
  }

  return (
    <section
      className="rounded-xl border border-surface-700 bg-surface-800 p-4 space-y-2.5"
      data-testid="decision-priorities"
    >
      <h2 className="text-xs font-semibold text-text-primary flex items-center gap-1.5">
        <SlidersHorizontal className="w-3.5 h-3.5 text-text-muted" aria-hidden="true" />
        {t.decisionView.prioritiesTitle}
      </h2>
      <p className="text-[11px] text-text-muted leading-relaxed">{t.decisionView.prioritiesHint}</p>
      <ul className="space-y-2">
        {priorities.map((p) => (
          <li key={p.key} className="flex flex-wrap items-center justify-between gap-2" data-testid="priority-row">
            <span className="text-xs text-text-primary">
              <span className="font-mono text-text-muted mr-1">{p.key}</span>
              {p.label}
              <span className="block text-[10px] text-text-muted">
                {p.isDefault
                  ? t.decisionView.defaultMark
                  : t.decisionView.shareOfWeight.replace('{p}', `${Math.round(p.normalizedWeight * 100)}%`)}
              </span>
            </span>
            <span className="inline-flex flex-wrap gap-1" role="group" aria-label={`${p.key} ${p.label}`}>
              {LEVELS.map((level) => (
                <button
                  key={level}
                  type="button"
                  aria-pressed={!p.isDefault && p.importance === level}
                  disabled={saving !== null}
                  onClick={() => void choose(p.key, level)}
                  className={`text-[10px] px-2 py-1 rounded-md border transition-colors disabled:opacity-60 ${
                    p.importance === level
                      ? p.isDefault
                        ? 'bg-surface-600 text-text-secondary border-surface-500 border-dashed'
                        : 'bg-ocean-500/20 text-ocean-300 border-ocean-500/40'
                      : 'bg-surface-700 text-text-muted border-surface-600 hover:bg-surface-600'
                  }`}
                >
                  {t.decisionView.importance[level]}
                </button>
              ))}
            </span>
          </li>
        ))}
      </ul>
      <details className="text-[10px] text-text-muted">
        <summary className="cursor-pointer">{t.decisionView.mappingTitle}</summary>
        <p className="mt-1 leading-relaxed">{t.decisionView.mapping}</p>
      </details>
    </section>
  )
}
