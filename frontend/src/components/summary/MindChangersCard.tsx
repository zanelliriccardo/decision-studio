import { useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, Compass } from 'lucide-react'
import { useT } from '../../i18n/index.tsx'
import { fetchMindChangers, type MindOption, type MindSignal } from '../../lib/api/reasoning.ts'

const pct = (p: number | null) => (p == null ? null : `${Math.round(p * 100)}%`)
const SHOWN = 3

const DECISIVENESS_CLASS = {
  decisive: 'text-text-primary border-surface-500',
  moderate: 'text-text-secondary border-surface-600',
  weak: 'text-text-muted border-surface-600',
} as const

/**
 * What would change my mind: the tripwires, link tests and field tests already
 * set up, gathered per option and read in the option's favour or against it.
 *
 * Only references: each signal is an existing test with its status now. The
 * detail stays where it lives (the theory panel), so this stays short.
 */
export default function MindChangersCard({
  projectId,
  refreshKey,
  options: preloaded,
}: {
  projectId: string
  refreshKey?: unknown
  /** For tests and callers that already have the data. */
  options?: MindOption[]
}) {
  const { t } = useT()
  const [options, setOptions] = useState<MindOption[] | null>(preloaded ?? null)

  useEffect(() => {
    if (preloaded) return
    let cancelled = false
    fetchMindChangers(projectId)
      .then((loaded) => {
        if (!cancelled) setOptions(loaded)
      })
      .catch(() => {
        if (!cancelled) setOptions([])
      })
    return () => {
      cancelled = true
    }
  }, [projectId, refreshKey, preloaded])

  if (!options || options.length === 0) return null
  if (!options.some((o) => o.theories.length > 0)) return null

  return (
    <section
      className="rounded-xl border border-surface-700 bg-surface-800 p-4 space-y-3"
      data-testid="mind-changers"
    >
      <h2 className="text-xs font-semibold text-text-primary flex items-center gap-1.5">
        <Compass className="w-3.5 h-3.5 text-text-muted" aria-hidden="true" />
        {t.decisionView.mindTitle}
      </h2>
      <p className="text-[11px] text-text-muted leading-relaxed">{t.decisionView.mindHint}</p>

      {options.map((option) => (
        <div key={option.key} className="space-y-1.5 border-t border-surface-700 pt-2" data-testid="mind-option">
          <p className="text-xs font-medium text-text-primary">
            <span className="font-mono text-text-muted mr-1">{option.key}</span>
            {option.label}
          </p>
          {option.theories.length === 0 ? (
            <p className="text-[11px] text-text-muted">{t.decisionView.noTheories}</p>
          ) : (
            <>
              <ul className="space-y-0.5">
                {option.theories.map((theory) => (
                  <li key={theory.id} className="text-[11px] text-text-secondary">
                    {theory.title}
                    <span className="text-text-muted">
                      {' · '}
                      {t.decisionView.conviction}: {pct(theory.conviction) ?? t.decisionView.convictionNotStated}
                    </span>
                  </li>
                ))}
              </ul>
              <SignalList title={t.decisionView.weaken} signals={option.weaken} kind="weaken" />
              <SignalList title={t.decisionView.strengthen} signals={option.strengthen} kind="strengthen" />
            </>
          )}
        </div>
      ))}
    </section>
  )
}

function SignalList({
  title,
  signals,
  kind,
}: {
  title: string
  signals: MindSignal[]
  kind: 'weaken' | 'strengthen'
}) {
  const { t } = useT()
  const Icon = kind === 'weaken' ? AlertTriangle : CheckCircle2
  return (
    <div data-testid={`mind-${kind}`}>
      <h4 className={`text-[10px] font-semibold uppercase tracking-wide ${kind === 'weaken' ? 'text-amber-400' : 'text-emerald-400'}`}>
        {title}
      </h4>
      {signals.length === 0 ? (
        <p className="text-[11px] text-text-muted">{t.decisionView.noSignals}</p>
      ) : (
        <ul className="space-y-1 mt-0.5">
          {signals.slice(0, SHOWN).map((signal) => (
            <li
              key={`${signal.kind}-${signal.id}-${signal.condition}`}
              className={`text-[11px] flex gap-1.5 ${signal.resolved ? 'opacity-60' : ''}`}
              data-testid="mind-signal"
            >
              <Icon className={`w-3 h-3 mt-0.5 shrink-0 ${kind === 'weaken' ? 'text-amber-400' : 'text-emerald-400'}`} aria-hidden="true" />
              <span>
                <span className="text-text-primary">{signal.text}</span>
                <span className="text-text-muted"> — {signal.condition}</span>
                <span className="block text-[10px] space-x-1.5">
                  <span className="text-text-muted">{t.decisionView.kinds[signal.kind]}</span>
                  <span className={`px-1 rounded border ${DECISIVENESS_CLASS[signal.decisiveness]}`}>
                    {t.decisionView.decisiveness[signal.decisiveness]}
                  </span>
                  <span className="text-text-secondary" data-testid="signal-status">
                    {(t.decisionView.statuses as Record<string, string>)[signal.status] ?? signal.status}
                  </span>
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
