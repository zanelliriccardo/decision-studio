import { useState } from 'react'
import { ChevronDown, ChevronRight, Coins } from 'lucide-react'
import { useT } from '../../i18n/index.tsx'
import type { AnalysisUsage } from '../../lib/api/reasoning.ts'

/**
 * What the analysis cost.
 *
 * Collapsed by default and shown in muted type: this is operational
 * information, and putting it beside the recommendation would suggest the two
 * are comparably important. But it is on the page rather than in a log, because
 * the person who ran the analysis is the one who cares what it cost and is
 * unlikely to go looking.
 *
 * Two honesty requirements, both visible rather than buried:
 *
 * * The **price table date** is shown next to every figure. The prices are
 *   hard-coded and go stale the moment a provider changes them, so a cost here
 *   makes one run comparable to another and will not reconcile with an invoice.
 * * **Unpriced calls are counted.** A model with no price entry contributes
 *   tokens but no cost, and without saying so the run would simply look cheap.
 *
 * Stages are listed most expensive first: the question is always "what cost the
 * money", never "what ran first".
 */
export default function UsagePanel({ usage }: { usage: AnalysisUsage | null }) {
  const { t } = useT()
  const [open, setOpen] = useState(false)

  if (!usage || usage.runs.length === 0) return null

  const latest = usage.runs[0]
  const stages = Object.entries(latest.by_stage ?? {})
  const unpriced = usage.runs.reduce((sum, r) => sum + (r.unpriced_calls ?? 0), 0)

  const money = (value: number) =>
    value >= 0.01 ? `$${value.toFixed(2)}` : `$${value.toFixed(4)}`

  return (
    <section
      className="rounded-lg border border-surface-700 bg-surface-800/50"
      data-testid="usage-panel"
    >
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-surface-700/40 transition-colors rounded-lg"
      >
        {open ? (
          <ChevronDown className="w-3 h-3 text-text-muted" aria-hidden="true" />
        ) : (
          <ChevronRight className="w-3 h-3 text-text-muted" aria-hidden="true" />
        )}
        <Coins className="w-3.5 h-3.5 text-text-muted" aria-hidden="true" />
        <span className="text-[11px] text-text-muted flex-1">
          {t.usage.title}
        </span>
        <span className="text-[11px] text-text-secondary tabular-nums">
          {money(usage.totalCostUsd)} · {usage.totalTokens.toLocaleString()}{' '}
          {t.usage.tokens}
        </span>
      </button>

      {open && (
        <div className="px-3 pb-3 space-y-2">
          {usage.runs.length > 1 && (
            <p className="text-[10px] text-text-muted">
              {t.usage.multipleRuns.replace('{n}', String(usage.runs.length))}
            </p>
          )}

          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-text-muted">
                <th className="text-left font-medium pb-1">{t.usage.stage}</th>
                <th className="text-right font-medium pb-1">{t.usage.calls}</th>
                <th className="text-right font-medium pb-1">{t.usage.tokens}</th>
                <th className="text-right font-medium pb-1">{t.usage.cost}</th>
              </tr>
            </thead>
            <tbody>
              {stages.map(([name, stage]) => (
                <tr key={name} className="border-t border-surface-700">
                  <td className="py-1 text-text-secondary">
                    {name.replace(/_/g, ' ')}
                  </td>
                  <td className="py-1 text-right text-text-muted tabular-nums">
                    {stage.calls}
                  </td>
                  <td className="py-1 text-right text-text-muted tabular-nums">
                    {stage.total_tokens.toLocaleString()}
                  </td>
                  <td className="py-1 text-right text-text-secondary tabular-nums">
                    {money(stage.cost_usd)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <p className="text-[10px] text-text-muted leading-relaxed">
            {t.usage.caveat.replace(
              '{date}',
              latest.price_table_date ?? t.usage.unknownDate,
            )}
            {unpriced > 0 && ' ' + t.usage.unpriced.replace('{n}', String(unpriced))}
          </p>
        </div>
      )}
    </section>
  )
}
