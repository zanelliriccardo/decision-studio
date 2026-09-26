import { useEffect, useState } from 'react'
import { ListChecks } from 'lucide-react'
import { useT } from '../../i18n/index.tsx'
import { fetchAssumptions, type AssumptionRegister } from '../../lib/api/workspace.ts'
import QualityChips from '../evidence/QualityChips.tsx'

const pct = (p: number | null) => (p == null ? '—' : `${Math.round(p * 100)}%`)

const flag = 'px-1.5 py-0.5 rounded border text-[9px] leading-none'

/**
 * The assumptions the decision rests on: existing claims, uncertain and
 * influential first. Derived from the map; nothing here adds a claim.
 */
export default function AssumptionsCard({
  projectId,
  refreshKey,
  register: preloaded,
}: {
  projectId: string
  refreshKey?: unknown
  /** For tests and callers that already have the data. */
  register?: AssumptionRegister
}) {
  const { t } = useT()
  const [register, setRegister] = useState<AssumptionRegister | null>(preloaded ?? null)

  useEffect(() => {
    if (preloaded) return
    let cancelled = false
    fetchAssumptions(projectId)
      .then((loaded) => !cancelled && setRegister(loaded))
      .catch(() => !cancelled && setRegister(null))
    return () => {
      cancelled = true
    }
  }, [projectId, refreshKey, preloaded])

  if (!register) return null

  return (
    <section className="rounded-xl border border-surface-700 bg-surface-800 p-4 space-y-2.5" data-testid="assumptions">
      <h2 className="text-xs font-semibold text-text-primary flex items-center gap-1.5">
        <ListChecks className="w-3.5 h-3.5 text-text-muted" aria-hidden="true" />
        {t.workspace.assumptionsTitle}
      </h2>
      <p className="text-[11px] text-text-muted leading-relaxed">{t.workspace.assumptionsHint}</p>
      {register.influenceBasis === 'relevance' && (
        <p className="text-[10px] text-amber-300">{t.workspace.relevanceBasis}</p>
      )}
      {register.assumptions.length === 0 ? (
        <p className="text-[11px] text-text-muted" data-testid="assumptions-empty">{t.workspace.assumptionsEmpty}</p>
      ) : (
        <ol className="space-y-2">
          {register.assumptions.map((a) => (
            <li key={a.claimId} className="text-xs border-t border-surface-700 pt-2 first:border-0 first:pt-0" data-testid="assumption">
              <div className="flex items-start justify-between gap-2">
                <span className="text-text-primary">{a.text}</span>
                <span className="shrink-0 text-right">
                  <span className="text-text-primary font-medium">{pct(a.belief)}</span>
                  <span className="block text-[9px] text-text-muted">{t.workspace.belief}</span>
                </span>
              </div>
              <div className="mt-1 flex flex-wrap gap-1 items-center text-[10px] text-text-muted">
                {a.options.length > 0 && <span>{t.workspace.bearsOn}: {a.options.join(', ')}</span>}
                {a.outcomes.length > 0 && <span>· {t.workspace.reaches}: {a.outcomes.join(', ')}</span>}
                {a.driverRank != null && (
                  <span className={`${flag} text-ocean-300 bg-ocean-500/10 border-ocean-500/30`}>
                    {t.workspace.driver.replace('{n}', String(a.driverRank))}
                  </span>
                )}
                {a.canAlter && (
                  <span className={`${flag} text-amber-300 bg-amber-500/10 border-amber-500/30`} data-testid="can-alter">
                    {t.workspace.canAlter}
                  </span>
                )}
                {a.affects === 'all_options' && (
                  <span className={`${flag} text-text-secondary bg-surface-700 border-surface-600`}>{t.workspace.allOptions}</span>
                )}
                {a.stale && (
                  <span className={`${flag} text-amber-300 bg-amber-500/10 border-amber-500/30`} title={a.staleTheories.join('; ')}>
                    {t.workspace.stale}
                  </span>
                )}
                {a.needsEvidence && (
                  <span className={`${flag} text-amber-300 bg-amber-500/10 border-amber-500/30`}>{t.workspace.needsEvidence}</span>
                )}
              </div>
              <div className="mt-1"><QualityChips labels={a.evidence.labels} /></div>
            </li>
          ))}
        </ol>
      )}
      {register.total > register.assumptions.length && (
        <p className="text-[10px] text-text-muted">
          {t.workspace.more.replace('{n}', String(register.total - register.assumptions.length))}
        </p>
      )}
    </section>
  )
}
