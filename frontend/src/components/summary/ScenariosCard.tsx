import { useEffect, useState } from 'react'
import { CloudSun, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { useT } from '../../i18n/index.tsx'
import {
  fetchScenarios,
  resetScenario,
  saveScenario,
  type ScenarioCase,
  type Scenarios,
} from '../../lib/api/workspace.ts'

const pct = (p: number | null | undefined) => (p == null ? '—' : `${Math.round(p * 100)}%`)

/**
 * Base case, upside and downside: the option comparison rerun with a few
 * inputs of the same map changed. Each case lists exactly what it changed, and
 * the decider can replace the automatic assumptions with their own.
 */
export default function ScenariosCard({
  projectId,
  refreshKey,
  scenarios: preloaded,
}: {
  projectId: string
  refreshKey?: unknown
  scenarios?: Scenarios
}) {
  const { t } = useT()
  const [scenarios, setScenarios] = useState<Scenarios | null>(preloaded ?? null)
  const [editing, setEditing] = useState<'upside' | 'downside' | null>(null)
  const [draft, setDraft] = useState<Record<string, number>>({})
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (preloaded) return
    let cancelled = false
    fetchScenarios(projectId)
      .then((loaded) => !cancelled && setScenarios(loaded))
      .catch(() => !cancelled && setScenarios(null))
    return () => {
      cancelled = true
    }
  }, [projectId, refreshKey, preloaded])

  if (!scenarios || scenarios.unavailable || scenarios.cases.length === 0) return null
  const base = scenarios.cases[0]
  const labels = Object.fromEntries(base.options.map((o) => [o.key, o.label]))

  async function run(action: () => Promise<Scenarios>) {
    setBusy(true)
    try {
      setScenarios(await action())
      setEditing(null)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t.workspace.saveFailed)
    } finally {
      setBusy(false)
    }
  }

  function startEdit(kase: ScenarioCase) {
    setEditing(kase.key as 'upside' | 'downside')
    setDraft(Object.fromEntries(kase.assumptions.map((a) => [`${a.kind}:${a.id}`, Math.round(a.value * 100)])))
  }

  const headline = (kase: ScenarioCase) => {
    const h = kase.headline
    if (!h || !h.higher || h.verdict === 'no_difference') return t.workspace.noHeadline
    return t.workspace.headline
      .replace('{option}', `${h.higher} ${labels[h.higher] ?? ''}`.trim())
      .replace('{verdict}', t.decisionView.verdicts[h.verdict as keyof typeof t.decisionView.verdicts] ?? h.verdict)
  }

  return (
    <section className="rounded-xl border border-surface-700 bg-surface-800 p-4 space-y-2.5" data-testid="scenarios">
      <h2 className="text-xs font-semibold text-text-primary flex items-center gap-1.5">
        <CloudSun className="w-3.5 h-3.5 text-text-muted" aria-hidden="true" />
        {t.workspace.scenariosTitle}
      </h2>
      <p className="text-[11px] text-text-muted leading-relaxed">{t.workspace.scenariosHint}</p>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] uppercase tracking-wide text-text-muted text-left">
              <th className="py-1 pr-2 font-semibold">{t.optionForecast.option}</th>
              {scenarios.cases.map((c) => (
                <th key={c.key} className="py-1 pr-2 font-semibold" colSpan={1}>{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {base.options.map((option) => (
              <tr key={option.key} className="border-t border-surface-700 align-top" data-testid="scenario-row">
                <td className="py-1.5 pr-2 text-text-primary">
                  <span className="font-mono text-text-muted mr-1">{option.key}</span>{option.label}
                </td>
                {scenarios.cases.map((c) => {
                  const row = c.options.find((o) => o.key === option.key)
                  return (
                    <td key={c.key} className="py-1.5 pr-2" data-testid={`cell-${c.key}`}>
                      {scenarios.outcomes.map((o) => (
                        <span key={o.key} className="block text-[11px]">
                          <span className="text-text-muted">{o.key}</span> {pct(row?.outcomes[o.key]?.point)}
                        </span>
                      ))}
                      {row?.weighted != null && (
                        <span className="block text-[10px] text-text-muted">
                          {t.decisionView.weightedView}: {Math.round(row.weighted * 100)}
                        </span>
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {scenarios.cases.slice(1).map((kase) => (
        <div key={kase.key} className="border-t border-surface-700 pt-2 space-y-1" data-testid={`case-${kase.key}`}>
          <p className="text-xs text-text-primary">
            {kase.label}
            <span className="text-text-muted"> — {headline(kase)}</span>
          </p>
          <p className="text-[10px] text-text-muted" data-testid="case-source">
            {kase.source === 'user' ? t.workspace.userDefined : t.workspace.automatic}
          </p>
          {editing === kase.key ? (
            <div className="space-y-1">
              {kase.assumptions.map((a) => {
                const k = `${a.kind}:${a.id}`
                return (
                  <label key={k} className="flex items-center gap-2 text-[11px] text-text-secondary">
                    <span className="flex-1">{a.label}</span>
                    <span className="text-[10px] text-text-muted">{t.workspace.baseValue.replace('{v}', pct(a.base))}</span>
                    <input
                      type="number"
                      min={0}
                      max={100}
                      value={draft[k] ?? 0}
                      onChange={(e) => setDraft({ ...draft, [k]: Number(e.target.value) })}
                      aria-label={a.label}
                      className="w-16 px-1.5 py-0.5 text-[11px] bg-surface-700 border border-surface-600 rounded text-text-primary"
                    />
                    <span className="text-[10px] text-text-muted">%</span>
                  </label>
                )
              })}
              <div className="flex gap-1.5">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void run(() => saveScenario(projectId, kase.key as 'upside' | 'downside',
                    kase.assumptions.map((a) => ({
                      kind: a.kind, id: a.id,
                      value: Math.max(0, Math.min(100, draft[`${a.kind}:${a.id}`] ?? 0)) / 100,
                    }))))}
                  className="inline-flex items-center gap-1 px-2 py-1 text-[10px] rounded-md bg-ocean-500/15 text-ocean-300 border border-ocean-500/30"
                >
                  {busy && <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" />}
                  {t.workspace.save}
                </button>
                <button type="button" onClick={() => setEditing(null)}
                  className="px-2 py-1 text-[10px] rounded-md bg-surface-700 text-text-muted border border-surface-600">
                  {t.workspace.cancel}
                </button>
              </div>
            </div>
          ) : (
            <>
              <ul className="space-y-0.5">
                {kase.assumptions.map((a) => (
                  <li key={`${a.kind}:${a.id}`} className="text-[11px] text-text-secondary" data-testid="scenario-assumption">
                    {a.label}: <span className="text-text-muted">{pct(a.base)}</span> → <span className="text-text-primary">{pct(a.value)}</span>
                  </li>
                ))}
              </ul>
              <div className="flex gap-2">
                {kase.assumptions.length > 0 && (
                  <button type="button" onClick={() => startEdit(kase)}
                    className="text-[10px] text-ocean-300 hover:text-ocean-200">{t.workspace.edit}</button>
                )}
                {kase.source === 'user' && (
                  <button type="button" disabled={busy}
                    onClick={() => void run(() => resetScenario(projectId, kase.key as 'upside' | 'downside'))}
                    className="text-[10px] text-text-muted hover:text-text-secondary">{t.workspace.reset}</button>
                )}
              </div>
            </>
          )}
        </div>
      ))}
    </section>
  )
}
