import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, ChevronDown, ChevronRight, FlaskConical, Loader2, Scale, Split } from 'lucide-react'
import { toast } from 'sonner'
import { useT } from '../../i18n/index.tsx'
import {
  designFieldTest,
  fetchConviction,
  fetchFieldTests,
  fetchHypotheses,
  independentCount,
  likelihoodKey,
  proposeHypotheses,
  recordFieldResult,
  recordHypothesisResult,
  statePrior,
  type Conviction,
  type FieldTest,
  type LinkHypothesis,
} from '../../lib/theoryValue.ts'
import type { DecisionAnchor } from '../../types/graph.ts'
import type { Theory } from '../../types/reasoning.ts'
import ConvictionElicitor from './ConvictionElicitor.tsx'
import EventField from './EventField.tsx'

const pct = (p: number | null | undefined) => (p == null ? '' : `${Math.round(p * 100)}%`)

const smallButton =
  'inline-flex items-center gap-1 px-2 py-1 text-[10px] rounded-md bg-surface-700 text-text-secondary border border-surface-600 hover:bg-surface-600 transition-colors disabled:opacity-50'

/**
 * A theory as a theory of value: the option it argues about, the decider's
 * conviction in it, and the tests that can move that conviction.
 *
 * Self-contained — it fetches and records through the API itself — so the two
 * screens that show theories do not each need the plumbing.
 */
export default function TheoryValueSection({
  theory,
  anchor,
  onChanged,
}: {
  theory: Theory
  anchor: DecisionAnchor | null | undefined
  /** Called after anything that changes the theory list (e.g. a refuted link marks it stale). */
  onChanged?: () => void
}) {
  const { t } = useT()
  const projectId = theory.projectId
  const [conviction, setConviction] = useState<Conviction | null>(null)
  const [eliciting, setEliciting] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [testsOpen, setTestsOpen] = useState(false)
  const [hypotheses, setHypotheses] = useState<LinkHypothesis[] | null>(null)
  const [fieldTests, setFieldTests] = useState<FieldTest[] | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  // One per theory's tests: the results recorded next usually come from the same event.
  const [event, setEvent] = useState('')

  const current = conviction?.current ?? theory.conviction ?? null
  const prior = conviction?.prior ?? theory.convictionPrior ?? null
  const option = anchor?.options.find((o) => o.key === theory.optionKey)

  const refreshConviction = useCallback(async () => {
    try {
      setConviction(await fetchConviction(projectId, theory.theoryKey))
    } catch {
      // The list's value still shows; history just stays closed.
    }
  }, [projectId, theory.theoryKey])

  useEffect(() => {
    if (!testsOpen) return
    let cancelled = false
    void Promise.all([
      fetchHypotheses(projectId, theory.theoryKey),
      fetchFieldTests(projectId, theory.id),
    ]).then(([h, f]) => {
      if (!cancelled) {
        setHypotheses(h)
        setFieldTests(f)
      }
    }).catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [testsOpen, projectId, theory.theoryKey, theory.id])

  async function run(key: string, action: () => Promise<void>) {
    setBusy(key)
    try {
      await action()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t.theoryValue.failed)
    } finally {
      setBusy(null)
    }
  }

  const effect = theory.predictedEffect ?? 'unclear'
  const effectClass =
    effect === 'achieves' ? 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30'
      : effect === 'threatens' ? 'text-red-300 bg-red-500/10 border-red-500/30'
        : 'text-text-secondary bg-surface-700 border-surface-600'

  return (
    <div className="space-y-2" data-testid="theory-value">
      {/* What the theory is a theory of */}
      {anchor && (
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-1.5 text-[10px]">
            {option ? (
              <>
                <span className="text-text-muted">{t.theoryValue.theoryOf}</span>
                <span className="px-1.5 py-0.5 rounded bg-surface-700 border border-surface-600 text-text-secondary">
                  <span className="font-mono text-text-muted mr-1">{option.key}</span>
                  {option.label}
                </span>
                <span className={`px-1.5 py-0.5 rounded border ${effectClass}`} data-testid="predicted-effect">
                  {t.theoryValue.effects[effect]}
                  {theory.outcomeKeys && theory.outcomeKeys.length > 0 && ` · ${theory.outcomeKeys.join(', ')}`}
                </span>
              </>
            ) : (
              <span className="px-1.5 py-0.5 rounded bg-surface-700 border border-surface-600 text-text-muted">
                {t.theoryValue.situational}
              </span>
            )}
          </div>
          {!theory.reachesOutcome && (
            <p className="text-[10px] text-amber-400 flex items-start gap-1" data-testid="no-outcome">
              <AlertTriangle className="w-3 h-3 mt-px shrink-0" aria-hidden="true" />
              {t.theoryValue.noOutcome}
            </p>
          )}
        </div>
      )}

      {/* The decider's conviction */}
      <div className="rounded-md border border-surface-600 bg-surface-700/40 px-2 py-1.5 space-y-1.5" data-testid="conviction">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[10px] font-medium text-text-muted flex items-center gap-1" title={t.theoryValue.convictionHint}>
            <Scale className="w-3 h-3" aria-hidden="true" />
            {t.theoryValue.conviction}
          </span>
          <span className="text-[11px] text-text-primary">
            {current != null ? (
              <>
                <span data-testid="conviction-value">{pct(current)}</span>
                {prior != null && Math.abs(current - prior) >= 0.005 && (
                  <span className="text-text-muted text-[10px]">
                    {' '}({t.theoryValue.statedAt.replace('{p}', pct(prior))})
                  </span>
                )}
              </>
            ) : (
              <span className="text-text-muted text-[10px]">{t.theoryValue.notStated}</span>
            )}
          </span>
        </div>

        {eliciting ? (
          <ConvictionElicitor
            onCancel={() => setEliciting(false)}
            onDone={(value, note) =>
              void run('prior', async () => {
                setConviction(await statePrior(projectId, theory.theoryKey, value, 'lottery', note))
                setEliciting(false)
              })
            }
          />
        ) : (
          <div className="flex flex-wrap gap-1.5">
            <button type="button" className={smallButton} onClick={() => setEliciting(true)} disabled={busy !== null}>
              {current != null ? t.theoryValue.restate : t.theoryValue.state}
            </button>
            <button
              type="button"
              className={smallButton}
              aria-expanded={showHistory}
              onClick={() => {
                if (!showHistory) void refreshConviction()
                setShowHistory(!showHistory)
              }}
            >
              {showHistory ? t.theoryValue.hideHistory : t.theoryValue.history}
            </button>
          </div>
        )}

        {showHistory && conviction && (
          <ul className="space-y-1" data-testid="conviction-history">
            {conviction.steps.length === 0 && (
              <li className="text-[10px] text-text-muted">{t.theoryValue.noEvidence}</li>
            )}
            {(() => {
              const { total, independent } = independentCount(conviction.steps)
              return total > independent ? (
                <li className="text-[10px] text-text-muted" data-testid="independent-count">
                  {t.theoryValue.independentOf
                    .replace('{total}', String(total))
                    .replace('{independent}', String(independent))}
                </li>
              ) : null
            })()}
            {conviction.steps.map((step) => (
              <li key={step.id} className="text-[10px] leading-snug">
                <span className="text-text-secondary">
                  {t.theoryValue.sources[step.source as keyof typeof t.theoryValue.sources] ?? step.source}
                </span>
                <span className="text-text-muted"> · {t.theoryValue.likelihood[likelihoodKey(step.likelihoodRatio)]}</span>
                {step.event && <span className="text-text-muted"> · “{step.event}”</span>}
                {step.applied ? (
                  <span className="text-text-primary"> → {pct(step.after)}</span>
                ) : step.duplicateOf ? (
                  <span className="text-text-muted italic"> — {t.theoryValue.sameEvent}</span>
                ) : (
                  <span className="text-text-muted italic">
                    {' '}— {conviction.prior == null ? t.theoryValue.waiting : t.theoryValue.notApplied}
                  </span>
                )}
                {step.note && <span className="block text-text-muted">{step.note}</span>}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Tests: links worth testing, and a real field test */}
      <button
        type="button"
        onClick={() => setTestsOpen(!testsOpen)}
        aria-expanded={testsOpen}
        className="inline-flex items-center gap-1 text-[10px] text-text-muted hover:text-text-secondary"
      >
        {testsOpen ? <ChevronDown className="w-3 h-3" aria-hidden="true" /> : <ChevronRight className="w-3 h-3" aria-hidden="true" />}
        {t.theoryValue.linksTitle} · {t.theoryValue.fieldTitle}
      </button>

      {testsOpen && (
        <div className="space-y-3 pl-1">
          <EventField projectId={projectId} value={event} onChange={setEvent} />
          <section className="space-y-1.5" data-testid="link-hypotheses">
            <h5 className="flex items-center gap-1.5 text-[10px] font-semibold text-text-muted">
              <Split className="w-3 h-3" aria-hidden="true" />
              {t.theoryValue.linksTitle}
            </h5>
            <p className="text-[10px] text-text-muted">{t.theoryValue.linksHint}</p>
            {(hypotheses ?? []).map((h, index) => (
              <div key={h.id} className="rounded-md border border-surface-600 bg-surface-800 p-2 space-y-1 text-[11px]">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-text-primary">{h.statement}</p>
                  {/* Rank, not the raw product: absolute values depend on how
                      saturated propagation is, and only the order is meaningful. */}
                  {h.status === 'open' && (
                    <span
                      className="text-[9px] text-text-muted shrink-0 font-mono"
                      title={`${t.theoryValue.priority}: ${h.leverage.toFixed(3)} × ${h.uncertainty.toFixed(2)}`}
                      data-testid="hypothesis-rank"
                    >
                      #{index + 1}
                    </span>
                  )}
                </div>
                <p className="text-text-secondary"><span className="text-text-muted">{t.theoryValue.wrongIf}: </span>{h.refutedIf}</p>
                {h.cheapestTest && (
                  <p className="text-text-secondary"><span className="text-text-muted">{t.theoryValue.cheapest}: </span>{h.cheapestTest}</p>
                )}
                {h.status === 'open' ? (
                  <div className="flex gap-1.5 pt-0.5">
                    {(['held', 'refuted', 'inconclusive'] as const).map((result) => (
                      <button
                        key={result}
                        type="button"
                        className={smallButton}
                        disabled={busy !== null}
                        onClick={() =>
                          void run(h.id, async () => {
                            const updated = await recordHypothesisResult(projectId, h.id, result, undefined, undefined, event)
                            setHypotheses((prev) => (prev ?? []).map((x) => (x.id === h.id ? updated : x)))
                            await refreshConviction()
                            toast.success(t.theoryValue.resultRecorded)
                            onChanged?.()
                          })
                        }
                      >
                        {t.theoryValue[result]}
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="text-[10px] text-text-muted">{t.theoryValue.statuses[h.status]}</p>
                )}
              </div>
            ))}
            <button
              type="button"
              className={smallButton}
              disabled={busy !== null}
              onClick={() =>
                void run('links', async () => {
                  const proposed = await proposeHypotheses(projectId, theory.id)
                  setHypotheses(await fetchHypotheses(projectId, theory.theoryKey).catch(() => proposed))
                })
              }
            >
              {busy === 'links' && <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" />}
              {busy === 'links' ? t.theoryValue.finding : t.theoryValue.findLinks}
            </button>
          </section>

          <section className="space-y-1.5" data-testid="field-tests">
            <h5 className="flex items-center gap-1.5 text-[10px] font-semibold text-text-muted">
              <FlaskConical className="w-3 h-3" aria-hidden="true" />
              {t.theoryValue.fieldTitle}
            </h5>
            <p className="text-[10px] text-text-muted">{t.theoryValue.fieldHint}</p>
            {(fieldTests ?? []).map((f) => (
              <div key={f.id} className="rounded-md border border-surface-600 bg-surface-800 p-2 space-y-1 text-[11px]">
                <p className="text-text-primary">{f.hypothesis}</p>
                {f.design ? (
                  <p className="text-text-secondary">{f.design}</p>
                ) : (
                  <p className="text-amber-300 text-[10px]">{f.summary || t.theoryValue.notFeasible}</p>
                )}
                {f.measure && (
                  <p className="text-text-secondary"><span className="text-text-muted">{t.theoryValue.measure}: </span>{f.measure}</p>
                )}
                {(f.costEstimate || f.durationDays) && (
                  <p className="text-[10px] text-text-muted">
                    {f.costEstimate && `${t.theoryValue.cost}: ${f.costEstimate}`}
                    {f.costEstimate && f.durationDays ? ' · ' : ''}
                    {f.durationDays ? t.theoryValue.days.replace('{n}', String(f.durationDays)) : ''}
                  </p>
                )}
                {f.status === 'designed' && f.design ? (
                  <div className="flex gap-1.5 pt-0.5">
                    {(['supports', 'refutes', 'inconclusive'] as const).map((result) => (
                      <button
                        key={result}
                        type="button"
                        className={smallButton}
                        disabled={busy !== null}
                        onClick={() =>
                          void run(f.id, async () => {
                            await recordFieldResult(projectId, f.id, result, undefined, event)
                            setFieldTests(await fetchFieldTests(projectId, theory.id))
                            await refreshConviction()
                            toast.success(t.theoryValue.resultRecorded)
                          })
                        }
                      >
                        {t.theoryValue[result]}
                      </button>
                    ))}
                  </div>
                ) : f.status === 'executed' ? (
                  <p className="text-[10px] text-text-muted">{f.summary}</p>
                ) : null}
              </div>
            ))}
            <button
              type="button"
              className={smallButton}
              disabled={busy !== null}
              onClick={() =>
                void run('field', async () => {
                  const designed = await designFieldTest(projectId, theory.id)
                  setFieldTests((prev) => [designed, ...(prev ?? [])])
                })
              }
            >
              {busy === 'field' && <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" />}
              {busy === 'field' ? t.theoryValue.designing : t.theoryValue.designField}
            </button>
          </section>
        </div>
      )}
    </div>
  )
}
