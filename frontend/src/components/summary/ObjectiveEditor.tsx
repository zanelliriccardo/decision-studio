import { useState } from 'react'
import { AlertTriangle, Check, Loader2, Pencil, Target, X } from 'lucide-react'
import { useT } from '../../i18n/index.tsx'

/**
 * The stated decision, editable in place.
 *
 * People frequently only work out what they are actually deciding after seeing
 * what the documents contain — the question sharpens as the material comes into
 * view. Making the objective settable only before the run would mean starting
 * over to correct it, which in practice means not correcting it.
 *
 * When it is missing the empty state says what is lost rather than showing a
 * blank line, because the consequence is not obvious: without a decision the
 * theories describe the situation instead of bearing on a choice, and the
 * recommendation has no question to answer.
 */
export default function ObjectiveEditor({
  objective,
  saving,
  onSave,
}: {
  objective: string | null
  saving: boolean
  onSave: (objective: string) => void
}) {
  const { t } = useT()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(objective ?? '')

  const stated = (objective ?? '').trim()

  if (editing) {
    return (
      <div className="space-y-2" data-testid="objective-editor">
        <label
          htmlFor="objective-input"
          className="text-[10px] uppercase tracking-wide text-text-muted block"
        >
          {t.summary.theDecision}
        </label>
        <input
          id="objective-input"
          type="text"
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && draft.trim()) {
              onSave(draft.trim())
              setEditing(false)
            }
            if (e.key === 'Escape') {
              setDraft(objective ?? '')
              setEditing(false)
            }
          }}
          placeholder={t.input.objectivePlaceholder}
          className="w-full px-3 py-2 text-sm bg-surface-700 border border-surface-600 rounded-lg text-text-primary placeholder-text-muted focus:outline-none focus:border-ocean-500 transition-colors"
        />
        <div className="flex gap-1.5">
          <button
            type="button"
            disabled={!draft.trim() || saving}
            onClick={() => {
              onSave(draft.trim())
              setEditing(false)
            }}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-lg bg-ocean-500/15 text-ocean-300 border border-ocean-500/30 hover:bg-ocean-500/25 transition-colors disabled:opacity-40"
          >
            {saving ? (
              <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" />
            ) : (
              <Check className="w-3 h-3" aria-hidden="true" />
            )}
            {t.summary.saveObjective}
          </button>
          <button
            type="button"
            onClick={() => {
              setDraft(objective ?? '')
              setEditing(false)
            }}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-lg bg-surface-700 text-text-secondary border border-surface-600 hover:bg-surface-600 transition-colors"
          >
            <X className="w-3 h-3" aria-hidden="true" />
            {t.review.cancel}
          </button>
        </div>
        {/* Said here rather than after the fact: regenerating is the whole
            reason to bother editing this. */}
        <p className="text-[10px] text-text-muted">{t.summary.regenerateHint}</p>
      </div>
    )
  }

  return (
    <div className="flex items-start gap-2 group">
      <Target className="w-5 h-5 text-ocean-400 mt-1 shrink-0" aria-hidden="true" />
      <div className="flex-1 min-w-0">
        <p className="text-[10px] uppercase tracking-wide text-text-muted">
          {t.summary.theDecision}
        </p>
        <div className="flex items-start gap-2">
          <h1 className="text-lg font-semibold text-text-primary leading-snug flex-1">
            {stated || t.summary.decisionNotStated}
          </h1>
          <button
            type="button"
            onClick={() => {
              setDraft(stated)
              setEditing(true)
            }}
            aria-label={t.summary.editObjective}
            title={t.summary.editObjective}
            className="p-1 mt-0.5 rounded-md text-text-muted hover:text-text-primary hover:bg-surface-700 transition-colors"
          >
            <Pencil className="w-3.5 h-3.5" aria-hidden="true" />
          </button>
        </div>
        {!stated && (
          <p className="text-[11px] text-amber-400 flex items-start gap-1.5 mt-1">
            <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" aria-hidden="true" />
            {t.summary.noObjectiveWarning}
          </p>
        )}
      </div>
    </div>
  )
}
