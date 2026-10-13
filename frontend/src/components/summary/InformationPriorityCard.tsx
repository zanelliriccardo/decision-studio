import { Search } from 'lucide-react'
import { useT } from '../../i18n/index.tsx'
import type { InformationItem } from '../../lib/api/reasoning.ts'

/**
 * Where more information is worth getting before deciding.
 *
 * A heuristic priority (uncertainty × impact on the comparison × whether it can
 * reverse it), each item with the reason it is listed. Not a money value.
 */
export default function InformationPriorityCard({ items }: { items: InformationItem[] }) {
  const { t } = useT()
  return (
    <section
      className="rounded-xl border border-surface-700 bg-surface-800 p-4 space-y-2.5"
      data-testid="information-priority"
    >
      <h2 className="text-xs font-semibold text-text-primary flex items-center gap-1.5">
        <Search className="w-3.5 h-3.5 text-text-muted" aria-hidden="true" />
        {t.decisionView.infoTitle}
      </h2>
      <p className="text-[11px] text-text-muted leading-relaxed">{t.decisionView.infoHint}</p>
      {items.length === 0 ? (
        <p className="text-[11px] text-text-muted" data-testid="info-empty">{t.decisionView.infoEmpty}</p>
      ) : (
        <ol className="space-y-2 list-decimal list-inside">
          {items.map((item) => (
            <li key={item.key} className="text-xs text-text-primary" data-testid="info-item">
              {item.action}
              <span className="block pl-4 mt-0.5 space-x-1.5">
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-700 border border-surface-600 text-text-secondary">
                  {t.decisionView.uncertaintyBand.replace('{band}', t.decisionView.bands[item.uncertaintyBand])}
                </span>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-700 border border-surface-600 text-text-secondary">
                  {t.decisionView.impactBand.replace('{band}', t.decisionView.bands[item.impactBand])}
                </span>
                {item.canFlip && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded border text-amber-300 bg-amber-500/10 border-amber-500/30">
                    {t.decisionView.canFlip}
                  </span>
                )}
              </span>
              <span className="block pl-4 text-[10px] text-text-muted mt-0.5">{item.why}</span>
              {item.how && (
                <span className="block pl-4 text-[10px] text-text-secondary">
                  {t.decisionView.how}: {item.how}
                </span>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
