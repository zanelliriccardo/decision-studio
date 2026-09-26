import { Activity, RotateCcw } from 'lucide-react'
import { useT } from '../../i18n/index.tsx'
import type { OptionComparison, RobustnessVerdict } from '../../lib/api/reasoning.ts'

const pct = (p: number) => `${Math.round(p * 100)}%`

const VERDICT_CLASS: Record<RobustnessVerdict, string> = {
  robust: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30',
  sensitive: 'text-amber-300 bg-amber-500/10 border-amber-500/30',
  unresolved: 'text-text-secondary bg-surface-700 border-surface-600',
  no_difference: 'text-text-muted bg-surface-700 border-surface-600',
}

/**
 * How robust the comparison is, and which inputs it depends on.
 *
 * Both come from the model's own uncertainty: the robustness shares from the
 * Monte Carlo comparison, the drivers from moving one input at a time. The
 * card says so, because neither is an empirical forecast.
 */
export default function RobustnessCard({ comparison }: { comparison: OptionComparison }) {
  const { t } = useT()
  if (comparison.options.length < 2 || comparison.unavailable) return null

  const labels = Object.fromEntries(comparison.options.map((o) => [o.key, o.label]))
  const name = (key: string | null) => (key ? `${key} ${labels[key] ?? ''}`.trim() : '')
  const [a, b] = comparison.headlinePair ?? [null, null]

  return (
    <section
      className="rounded-xl border border-surface-700 bg-surface-800 p-4 space-y-3"
      data-testid="robustness"
    >
      <h2 className="text-xs font-semibold text-text-primary flex items-center gap-1.5">
        <Activity className="w-3.5 h-3.5 text-text-muted" aria-hidden="true" />
        {t.decisionView.robustnessTitle}
      </h2>
      <p className="text-[11px] text-text-muted leading-relaxed">{t.decisionView.robustnessHint}</p>

      <div className="space-y-2">
        <h3 className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
          {t.decisionView.robustnessLabel}
        </h3>
        {comparison.robustness.map((pair) => (
          <div key={`${pair.a}-${pair.b}`} className="space-y-1" data-testid="robustness-pair">
            <p className="text-xs text-text-primary">
              {name(pair.a)} <span className="text-text-muted">vs</span> {name(pair.b)}
              <span className="block text-[10px] text-text-muted" data-testid="pair-summary">
                {t.decisionView.pairSummary[pair.summary]}
              </span>
            </p>
            <ul className="space-y-1">
              {[...pair.outcomes.map((o) => ({ ...o, title: `${o.key} ${o.label}` })),
                ...(pair.weighted ? [{ ...pair.weighted, title: t.decisionView.weightedView }] : [])]
                .map((row) => (
                  <li key={row.title} className="flex flex-wrap items-center gap-1.5 text-[11px]">
                    <span className="text-text-secondary min-w-[8rem]">{row.title}</span>
                    <span
                      className={`px-1.5 py-0.5 rounded border text-[10px] ${VERDICT_CLASS[row.verdict]}`}
                      data-testid="verdict"
                      data-verdict={row.verdict}
                    >
                      {row.verdict === 'no_difference'
                        ? t.decisionView.verdicts.no_difference
                        : `${row.higher} ${t.decisionView.verdicts[row.verdict]}`}
                    </span>
                    {row.verdict !== 'no_difference' && (
                      <span className="text-[10px] text-text-muted">
                        {row.higher} {t.decisionView.higherIn.replace('{p}', pct(row.share))}
                      </span>
                    )}
                  </li>
                ))}
            </ul>
          </div>
        ))}
      </div>

      <div className="space-y-1.5" data-testid="sensitivity">
        <h3 className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
          {t.decisionView.sensitivityLabel}
        </h3>
        {comparison.drivers.length === 0 ? (
          <p className="text-[11px] text-text-muted" data-testid="no-drivers">
            {comparison.options.some((o) => o.weighted) ? t.decisionView.noDrivers : t.decisionView.noDriversNoWeights}
          </p>
        ) : (
          <>
            {a && b && (
              <p className="text-[11px] text-text-secondary">
                {t.decisionView.sensitivityOf.replace('{a}', name(a)).replace('{b}', name(b))}
              </p>
            )}
            <ol className="space-y-1.5 list-decimal list-inside">
              {comparison.drivers.map((driver) => (
                <li key={driver.key} className="text-xs text-text-primary" data-testid="driver">
                  {driver.label}
                  {driver.flip !== 'no_flip' && (
                    <span
                      className="ml-1.5 inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded border text-[10px] text-amber-300 bg-amber-500/10 border-amber-500/30"
                      data-testid="driver-flip"
                    >
                      <RotateCcw className="w-2.5 h-2.5" aria-hidden="true" />
                      {driver.flip === 'flips' ? t.decisionView.canFlip : t.decisionView.canErase}
                    </span>
                  )}
                  <span className="block pl-4 text-[10px] text-text-muted">
                    {(driver.kind === 'claim' ? t.decisionView.driverRangeWhatIf : t.decisionView.driverRange)
                      .replace('{current}', pct(driver.current))
                      .replace('{low}', pct(driver.low))
                      .replace('{high}', pct(driver.high))}
                  </span>
                  <span className="block pl-4 text-[10px] text-text-secondary">{driver.explanation}</span>
                </li>
              ))}
            </ol>
          </>
        )}
      </div>

      <details className="text-[10px] text-text-muted">
        <summary className="cursor-pointer">{t.decisionView.methodTitle}</summary>
        <p className="mt-1 leading-relaxed">{t.decisionView.method}</p>
      </details>
    </section>
  )
}
