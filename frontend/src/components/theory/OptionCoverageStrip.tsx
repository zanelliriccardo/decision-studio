import { AlertTriangle } from 'lucide-react'
import { useT } from '../../i18n/index.tsx'
import { optionCoverage } from '../../lib/theoryValue.ts'
import type { DecisionAnchor } from '../../types/graph.ts'
import type { Theory } from '../../types/reasoning.ts'

/**
 * Which options the theories actually examine.
 *
 * The row that matters is the empty one: an option no theory argues for or
 * against is one the graph is silent about, and a comparison between options
 * where one was never examined is not a comparison.
 */
export default function OptionCoverageStrip({
  anchor,
  theories,
}: {
  anchor: DecisionAnchor | null | undefined
  theories: Theory[]
}) {
  const { t } = useT()
  const rows = optionCoverage(anchor, theories)
  if (rows.length === 0 || theories.length === 0) return null

  return (
    <section className="rounded-lg border border-surface-600 bg-surface-800/60 p-2.5 space-y-1.5" data-testid="option-coverage">
      <p className="text-[10px] uppercase tracking-wide text-text-muted">{t.theoryValue.coverageTitle}</p>
      {rows.map((row) => {
        const uncovered = row.achieves + row.threatens + row.unclear === 0
        return (
          <div key={row.key} className="flex items-start gap-2 text-[11px]" data-uncovered={uncovered}>
            <span className="font-mono text-[10px] text-text-muted w-6 shrink-0 mt-px">{row.key}</span>
            <div className="flex-1 min-w-0">
              <span className={uncovered ? 'text-amber-300' : 'text-text-secondary'}>{row.label}</span>
              {uncovered ? (
                <p className="text-[10px] text-amber-400/90 flex items-start gap-1 mt-0.5">
                  <AlertTriangle className="w-3 h-3 mt-px shrink-0" aria-hidden="true" />
                  {t.theoryValue.uncovered}
                </p>
              ) : (
                <span className="ml-2 text-[10px]">
                  <span className="text-emerald-400">{t.theoryValue.coverageFor.replace('{n}', String(row.achieves))}</span>
                  <span className="text-text-muted"> · </span>
                  <span className="text-red-400">{t.theoryValue.coverageAgainst.replace('{n}', String(row.threatens))}</span>
                </span>
              )}
            </div>
          </div>
        )
      })}
    </section>
  )
}
