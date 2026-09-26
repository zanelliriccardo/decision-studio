import { useEffect, useState } from 'react'
import { History, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { useT } from '../../i18n/index.tsx'
import {
  fetchOutsideView,
  runOutsideView,
  type OutsideView,
} from '../../lib/api/reasoning.ts'

/**
 * The outside view: how comparable decisions went for the decider.
 *
 * The one input the documents cannot supply. The base rates read from it are
 * set against each theory, turned the same way round (a theory that the date
 * will be met is compared with how often dates slipped), and measured against
 * the decider's conviction once they have stated one.
 */
export default function ComparableCases({
  projectId,
  onChecked,
}: {
  projectId: string
  /** Called after a check, so theory notes can be reloaded. */
  onChecked?: () => void
}) {
  const { t } = useT()
  const [view, setView] = useState<OutsideView | null>(null)
  const [text, setText] = useState('')
  const [checking, setChecking] = useState(false)
  const [lastResult, setLastResult] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchOutsideView(projectId)
      .then((loaded) => {
        if (cancelled) return
        setView(loaded)
        setText(loaded.recollection ?? '')
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [projectId])

  async function check() {
    setChecking(true)
    try {
      const result = await runOutsideView(projectId, text)
      setView(result)
      setLastResult(
        result.cases.length === 0 && text.trim()
          ? t.outsideView.noCases
          : t.outsideView.result
              .replace('{checked}', String(result.checked))
              .replace('{diverging}', String(result.diverging)),
      )
      onChecked?.()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t.outsideView.failed)
    } finally {
      setChecking(false)
    }
  }

  const unchanged = (view?.recollection ?? '') === text.trim()

  return (
    <section
      className="rounded-xl border border-surface-700 bg-surface-800 p-4 space-y-2.5"
      data-testid="comparable-cases"
    >
      <h2 className="text-xs font-semibold text-text-primary flex items-center gap-1.5">
        <History className="w-3.5 h-3.5 text-text-muted" aria-hidden="true" />
        {t.outsideView.title}
      </h2>
      <p className="text-[11px] text-text-muted leading-relaxed">{t.outsideView.hint}</p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        maxLength={4000}
        placeholder={t.outsideView.placeholder}
        aria-label={t.outsideView.title}
        className="w-full px-2.5 py-1.5 text-xs bg-surface-700 border border-surface-600 rounded-lg text-text-primary placeholder-text-muted focus:outline-none focus:border-ocean-500 transition-colors"
      />
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => void check()}
          disabled={checking || (unchanged && !text.trim())}
          className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded-lg bg-ocean-500/15 text-ocean-300 border border-ocean-500/30 hover:bg-ocean-500/25 transition-colors disabled:opacity-50"
        >
          {checking && <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" />}
          {checking ? t.outsideView.checking : t.outsideView.check}
        </button>
        {lastResult && (
          <span className="text-[11px] text-text-secondary" data-testid="outside-view-result">
            {lastResult}
          </span>
        )}
      </div>
      {view && view.cases.length > 0 && (
        <div>
          <h3 className="text-[10px] font-semibold uppercase tracking-wide text-text-muted mb-1">
            {t.outsideView.baseRates}
          </h3>
          <ul className="space-y-0.5">
            {view.cases.map((c) => (
              <li key={c.id} className="text-xs text-text-secondary">
                {c.outcome}:{' '}
                <span className="text-text-primary">
                  {c.casesWithOutcome}/{c.casesTotal} ({Math.round(c.baseRate * 100)}%)
                </span>
                {c.basis && <span className="text-text-muted italic"> — “{c.basis}”</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
