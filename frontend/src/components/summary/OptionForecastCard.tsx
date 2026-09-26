import { useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, Scale } from 'lucide-react'
import { useT } from '../../i18n/index.tsx'
import {
  fetchOptionComparison,
  type OptionComparison,
} from '../../lib/api/reasoning.ts'

const pct = (p: number | null | undefined) => (p == null ? '—' : `${Math.round(p * 100)}%`)

/**
 * What the causal map predicts for each option: the options compared by the
 * model, not only by the arguments made about them.
 *
 * Hidden when the decision has fewer than two options. When the map cannot
 * compare them it says why, because "the map is silent on the choice" is
 * itself something a decider needs to know.
 */
export default function OptionForecastCard({
  projectId,
  refreshKey,
}: {
  projectId: string
  /** Changes when the graph or anchor may have changed, to recompute. */
  refreshKey?: unknown
}) {
  const { t } = useT()
  const [comparison, setComparison] = useState<OptionComparison | null>(null)
  const [openLevers, setOpenLevers] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchOptionComparison(projectId)
      .then((loaded) => {
        if (!cancelled) setComparison(loaded)
      })
      .catch(() => {
        if (!cancelled) setComparison(null)
      })
    return () => {
      cancelled = true
    }
  }, [projectId, refreshKey])

  if (!comparison || comparison.options.length < 2) return null

  const leader = [...comparison.options].sort((a, b) => (b.pBest ?? 0) - (a.pBest ?? 0))[0]
  const headline = comparison.unavailable
    ? comparison.unavailable
    : (comparison.decisive ? t.optionForecast.decisive : t.optionForecast.notDecisive)
        .replace('{key}', `${leader.key} (${leader.label})`)
        .replace('{p}', pct(leader.pBest))

  return (
    <section
      className="rounded-xl border border-surface-700 bg-surface-800 p-4 space-y-2.5"
      data-testid="option-forecast"
    >
      <h2 className="text-xs font-semibold text-text-primary flex items-center gap-1.5">
        <Scale className="w-3.5 h-3.5 text-text-muted" aria-hidden="true" />
        {t.optionForecast.title}
      </h2>
      <p
        className={`text-xs leading-relaxed ${comparison.decisive ? 'text-text-primary' : 'text-amber-300'}`}
        data-testid="option-forecast-headline"
      >
        {headline}
      </p>

      {!comparison.unavailable && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] uppercase tracking-wide text-text-muted text-left">
                <th className="py-1 pr-2 font-semibold">{t.optionForecast.option}</th>
                {comparison.outcomes.map((o) => (
                  <th key={o.key} className="py-1 pr-2 font-semibold">
                    <span className="font-mono mr-1">{o.key}</span>
                    {o.label}
                  </th>
                ))}
                <th className="py-1 font-semibold text-right">{t.optionForecast.bestIn}</th>
              </tr>
            </thead>
            <tbody>
              {comparison.options.map((option) => {
                const isLeader = comparison.decisive && option.key === comparison.leader
                const note = t.optionForecast.statuses[option.status]
                const levers = [
                  ...option.leversOn.map((l) => ({ ...l, on: true })),
                  ...option.leversOff.map((l) => ({ ...l, on: false })),
                ]
                return (
                  <tr key={option.key} className="border-t border-surface-700 align-top">
                    <td className="py-1.5 pr-2">
                      <span className={isLeader ? 'text-emerald-300 font-medium' : 'text-text-primary'}>
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
                              {/* The range as a bar: where the figure moves when links are shaken. */}
                              <div className="relative h-1.5 w-24 rounded bg-surface-700" aria-hidden="true">
                                <div
                                  className="absolute h-1.5 rounded bg-ocean-500/40"
                                  style={{ left: `${stats.p10 * 100}%`, width: `${Math.max((stats.p90 - stats.p10) * 100, 1)}%` }}
                                />
                                <div
                                  className="absolute h-1.5 w-0.5 bg-ocean-300"
                                  style={{ left: `${stats.point * 100}%` }}
                                />
                              </div>
                            </div>
                          ) : (
                            '—'
                          )}
                        </td>
                      )
                    })}
                    <td className="py-1.5 text-right">
                      <span className={isLeader ? 'text-emerald-300 font-semibold' : 'text-text-secondary'}>
                        {pct(option.pBest)}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-[10px] text-text-muted leading-relaxed">
        {t.optionForecast.hint} {t.optionForecast.caveat}
      </p>
    </section>
  )
}
