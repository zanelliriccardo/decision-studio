import { useState } from 'react'
import { Loader2, Table2 } from 'lucide-react'
import { toast } from 'sonner'
import { useT } from '../../i18n/index.tsx'
import { testHypothesisWithData, type LinkHypothesis } from '../../lib/theoryValue.ts'

/**
 * Test one link against the decider's own numbers: two pasted columns, the
 * cause then the effect. The only route by which company data reaches a link.
 */
export default function DataTestForm({
  projectId,
  hypothesis,
  event,
  onRecorded,
}: {
  projectId: string
  hypothesis: LinkHypothesis
  event: string
  onRecorded: (updated: LinkHypothesis) => void
}) {
  const { t } = useT()
  const [open, setOpen] = useState(false)
  const [table, setTable] = useState('')
  const [timeOrdered, setTimeOrdered] = useState(true)
  const [busy, setBusy] = useState(false)

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1 text-[10px] text-ocean-300 hover:text-ocean-200"
      >
        <Table2 className="w-3 h-3" aria-hidden="true" />
        {t.theoryValue.dataTest}
      </button>
    )
  }

  async function submit() {
    setBusy(true)
    try {
      const outcome = await testHypothesisWithData(projectId, hypothesis.id, table, timeOrdered, event)
      toast.success(`${t.theoryValue[outcome.result]}: ${outcome.summary}`)
      onRecorded(outcome.hypothesis)
      setOpen(false)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t.theoryValue.failed)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-1 pt-1" data-testid="data-test">
      <p className="text-[10px] text-text-muted">{t.theoryValue.dataTestHint}</p>
      <textarea
        value={table}
        onChange={(e) => setTable(e.target.value)}
        rows={4}
        placeholder={t.theoryValue.dataTestPlaceholder}
        aria-label={t.theoryValue.dataTest}
        className="w-full px-2 py-1 text-[11px] font-mono bg-surface-700 border border-surface-600 rounded-md text-text-primary placeholder-text-muted focus:outline-none focus:border-ocean-500"
      />
      <label className="flex items-center gap-1.5 text-[10px] text-text-secondary">
        <input type="checkbox" checked={timeOrdered} onChange={(e) => setTimeOrdered(e.target.checked)} />
        {t.theoryValue.dataTimeOrdered}
      </label>
      <div className="flex gap-1.5">
        <button
          type="button"
          onClick={() => void submit()}
          disabled={busy || !table.trim()}
          className="inline-flex items-center gap-1 px-2 py-1 text-[10px] rounded-md bg-ocean-500/15 text-ocean-300 border border-ocean-500/30 hover:bg-ocean-500/25 disabled:opacity-50"
        >
          {busy && <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" />}
          {t.theoryValue.dataRun}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="px-2 py-1 text-[10px] rounded-md bg-surface-700 text-text-muted border border-surface-600 hover:bg-surface-600"
        >
          {t.common.close}
        </button>
      </div>
    </div>
  )
}
