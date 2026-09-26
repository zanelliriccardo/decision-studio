import { useState } from 'react'
import { ChevronDown, ChevronRight, Scale } from 'lucide-react'
import { useT } from '../../i18n/index.tsx'
import type { OptionComparison } from '../../lib/api/reasoning.ts'

const pct = (p: number | null | undefined) => (p == null ? '—' : `${Math.round(p * 100)}%`)
const points = (p: number) => `${Math.round(p * 100)}`

/**
 * What each option implies: the model-implied outcome for every success
 * criterion, then the weighted view under the decider's priorities.
 *
 * The two are kept visibly apart. The outcome columns are probabilities from
 * the causal map; the weighted column is those probabilities read through the
 * decider's priorities, in points — not a probability and not a verdict.
 */
export default function OptionForecastCard({ comparison }: { comparison: OptionComparison }) {
  const { t } = useT()
  const [openLevers, setOpenLevers] = useState<string | null>(null)

  if (comparison.options.length < 2) return null

  const labels = Object.fromEntries(comparison.options.map((o) => [o.key, o.label]))
  const hasWeights = comparison.options.some((o) => o.weighted)
  const pair = comparison.headlinePair
    ? comparison.robustness.find(
        (r) => [r.a, r.b].sort().join() === [...comparison.headlinePair!].sort().join(),
      )
    : undefined
  const verdict = pair?.weighted ?? null

  let headline: string
  if (comparison.unavailable) headline = comparison.unavailable
  else if (!hasWeights) headline = t.decisionView.noWeights
  else if (!verdict || verdict.verdict === 'no_difference' || !verdict.higher) headline = t.decisionView.weightedLevel
  else
    headline = t.decisionView.weightedHeadline
      .replace('{option}', `${verdict.higher} (${labels[verdict.higher]})`)
      .replace(
        '{verdict}',
        `${t.decisionView.verdicts[verdict.verdict]} — ${t.decisionView.higherIn.replace('{p}', pct(verdict.share))}`,
      )

  return (
    <section
      className="rounded-xl border border-surface-700 bg-surface-800 p-4 space-y-2.5"
      data-testid="option-forecast"
    >
      <h2 className="text-xs font-semibold text-text-primary flex items-center gap-1.5">
        <Scale className="w-3.5 h-3.5 text-text-muted" aria-hidden="true" />
        {t.decisionView.tradeOffTitle}
      </h2>
      <p className="text-xs leading-relaxed text-text-primary" data-testid="option-forecast-headline">
        {headline}
        {!comparison.unavailable && hasWeights && (
          <span className="text-text-muted"> {t.decisionView.humanDecision}</span>
        )}
      </p>

      {!comparison.unavailable && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] uppercase tracking-wide text-text-muted text-left">
                <th className="py-1 pr-2 font-semibold">{t.optionForecast.option}</th>
                {comparison.outcomes.map((o) => {
                  const priority = comparison.priorities.find((p) => p.key === o.key)
                  return (
                    <th key={o.key} className="py-1 pr-2 font-semibold">
                      <span className="font-mono mr-1">{o.key}</span>
                      {o.label}
                      {priority && (
                        <span className="block normal-case tracking-normal font-normal text-text-muted">
                          {t.decisionView.importance[priority.importance]}
                        </span>
                      )}
                    </th>
                  )
                })}
                {hasWeights && (
                  <th className="py-1 font-semibold text-right" title={t.decisionView.weightedHint}>
                    {t.decisionView.weightedView}
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {comparison.options.map((option) => {
                const note = t.optionForecast.statuses[option.status]
                const levers = [
                  ...option.leversOn.map((l) => ({ ...l, on: true })),
                  ...option.leversOff.map((l) => ({ ...l, on: false })),
                ]
                return (
                  <tr key={option.key} className="border-t border-surface-700 align-top" data-testid="forecast-row">
                    <td className="py-1.5 pr-2">
                      <span className="text-text-primary">
                        <span className="font-mono text-text-muted mr-1">{option.key}</span>
                        {option.label}
                      </span>
                      {note && <span className="block text-[10px] text-amber-400">{note}</span>}
                      {levers.length > 0 && (
                        <button
                          type="button"
                          onClick={() => setOpenLevers(openLevers === option.key ? null : option.key)}
                          aria-expanded={openLevers === option.key}
                          className="mt-0.5 inline-flex items-center gap-0.5 text-[10px] text-text-muted hover:text-text-secondary"
                        >
                          {openLevers === option.key
                            ? <ChevronDown className="w-3 h-3" aria-hidden="true" />
                            : <ChevronRight className="w-3 h-3" aria-hidden="true" />}
                          {t.optionForecast.levers} ({levers.length})
                        </button>
                      )}
                      {openLevers === option.key && (
                        <ul className="mt-0.5 space-y-0.5">
                          {levers.map((l) => (
                            <li key={l.claimId} className="text-[10px] text-text-secondary">
                              <span className={l.on ? 'text-emerald-400' : 'text-text-muted'}>
                                {l.on ? t.optionForecast.on : t.optionForecast.off}
                              </span>
                              {' · '}
                              {l.text}
                            </li>
                          ))}
                        </ul>
                      )}
                    </td>
                    {comparison.outcomes.map((o) => {
                      const stats = option.outcomes[o.key]
                      return (
                        <td key={o.key} className="py-1.5 pr-2">
                          {stats ? (
                            <div className="space-y-0.5">
                              <span className="text-text-primary">{pct(stats.point)}</span>
                              <span className="text-[10px] text-text-muted">
                                {' '}({pct(stats.p10)}–{pct(stats.p90)})
                              </span>
                              <div className="relative h-1.5 w-24 rounded bg-surface-700" aria-hidden="true">
                                <div
                                  className="absolute h-1.5 rounded bg-ocean-500/40"
                                  style={{ left: `${stats.p10 * 100}%`, width: `${Math.max((stats.p90 - stats.p10) * 100, 1)}%` }}
                                />
                                <div className="absolute h-1.5 w-0.5 bg-ocean-300" style={{ left: `${stats.point * 100}%` }} />
                              </div>
                            </div>
                          ) : (
                            '—'
                          )}
                        </td>
                      )
                    })}
                    {hasWeights && (
                      <td className="py-1.5 text-right" data-testid="weighted-cell">
                        {option.weighted ? (
                          <>
                            <span className="text-text-primary font-medium">{points(option.weighted.score)}</span>
                            <span className="text-[10px] text-text-muted"> / 100</span>
                            <span className="block text-[10px] text-text-muted">
                              {comparison.outcomes
                                .filter((o) => option.weighted!.contributions[o.key] != null)
                                .map((o) =>
                                  t.decisionView.contribution
                                    .replace('{label}', o.key)
                                    .replace('{points}', points(option.weighted!.contributions[o.key])),
                                )
                                .join(' + ')}
                            </span>
                          </>
                        ) : '—'}
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-[10px] text-text-muted leading-relaxed">
        {t.decisionView.tradeOffHint} {hasWeights && t.decisionView.weightedHint} {t.optionForecast.caveat}
      </p>
    </section>
  )
}
