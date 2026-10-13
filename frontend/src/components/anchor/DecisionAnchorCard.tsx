import { useState } from 'react'
import { Check, Loader2, Pencil, Plus, Target, Trash2, X } from 'lucide-react'
import { toast } from 'sonner'
import { useT } from '../../i18n/index.tsx'
import {
  cleanForSave,
  saveDecisionAnchor,
  type AnchorSaveReport,
} from '../../lib/decisionAnchor.ts'
import type { DecisionAnchor } from '../../types/graph.ts'

const MAX_OPTIONS = 4
const MAX_OUTCOMES = 3
const MAX_CONSTRAINTS = 5

const inputClass =
  'w-full px-2.5 py-1.5 text-xs bg-surface-700 border border-surface-600 rounded-lg text-text-primary placeholder-text-muted focus:outline-none focus:border-ocean-500 transition-colors'

/**
 * The decision anchor: the decision, its options, what success looks like.
 *
 * A pre-filled card, never a form to complete. The model drafts it from the
 * one-line objective and the material; the user may correct it and need not.
 * Three question systems were removed from this repository for standing
 * between the user and the analysis, so nothing here blocks anything.
 *
 * Two modes:
 * - **intake** (`onChange`): edits are lifted to the parent and submitted with
 *   the start of the analysis. Nothing is saved from here.
 * - **summary** (`projectId`): the card saves through the API. On a finished
 *   graph that re-scores every claim and links any new outcome into the graph,
 *   without re-running the pipeline.
 */
export default function DecisionAnchorCard({
  anchor,
  loading = false,
  onChange,
  projectId,
  onSaved,
}: {
  anchor: DecisionAnchor | null
  loading?: boolean
  onChange?: (anchor: DecisionAnchor) => void
  projectId?: string
  onSaved?: (anchor: DecisionAnchor) => void
}) {
  const { t } = useT()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<DecisionAnchor | null>(anchor)
  const [saving, setSaving] = useState(false)

  if (loading && !anchor) {
    return (
      <section className="rounded-xl border border-amber-500/20 bg-surface-800 p-4 flex items-center gap-2 text-xs text-text-muted">
        <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
        {t.anchor.drafting}
      </section>
    )
  }
  if (!anchor) return null

  const current = editing && draft ? draft : anchor
  const update = (next: DecisionAnchor) => {
    setDraft(next)
    // Intake mode lifts every keystroke; summary mode waits for Save.
    if (onChange && !projectId) onChange(next)
  }

  async function save() {
    if (!projectId || !draft) return
    setSaving(true)
    try {
      const result = await saveDecisionAnchor(projectId, draft)
      if (result.anchor) onSaved?.(result.anchor)
      toast.success(describeReport(result.report, t.anchor))
      setEditing(false)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t.anchor.saveFailed)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section
      className="rounded-xl border border-amber-500/25 bg-surface-800 p-4 space-y-3"
      data-testid="decision-anchor-card"
    >
      <header className="flex items-start gap-2">
        <Target className="w-4 h-4 text-amber-400 mt-0.5 shrink-0" aria-hidden="true" />
        <div className="flex-1 min-w-0">
          <p className="text-[10px] uppercase tracking-wide text-text-muted">
            {t.anchor.title}
            {anchor.status === 'draft' && (
              <span className="ml-1.5 normal-case tracking-normal text-amber-400/80">
                · {t.anchor.draftBadge}
              </span>
            )}
          </p>
          {!editing && (
            <p className="text-sm font-medium text-text-primary leading-snug">{anchor.decision}</p>
          )}
        </div>
        {!editing && (
          <button
            type="button"
            onClick={() => {
              setDraft(anchor)
              setEditing(true)
            }}
            aria-label={t.anchor.edit}
            title={t.anchor.edit}
            className="p-1 rounded-md text-text-muted hover:text-text-primary hover:bg-surface-700 transition-colors"
          >
            <Pencil className="w-3.5 h-3.5" aria-hidden="true" />
          </button>
        )}
      </header>

      {editing ? (
        <AnchorEditor value={current} onChange={update} />
      ) : (
        <AnchorView anchor={anchor} />
      )}

      {editing && projectId && (
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            disabled={saving || !cleanForSave(current).decision}
            onClick={() => void save()}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-lg bg-ocean-500/15 text-ocean-300 border border-ocean-500/30 hover:bg-ocean-500/25 transition-colors disabled:opacity-40"
          >
            {saving ? (
              <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" />
            ) : (
              <Check className="w-3 h-3" aria-hidden="true" />
            )}
            {t.anchor.save}
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={() => setEditing(false)}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-lg bg-surface-700 text-text-secondary border border-surface-600 hover:bg-surface-600 transition-colors"
          >
            <X className="w-3 h-3" aria-hidden="true" />
            {t.review.cancel}
          </button>
          <p className="basis-full text-[10px] text-text-muted">{t.anchor.saveHint}</p>
        </div>
      )}
      {editing && !projectId && (
        <button
          type="button"
          onClick={() => setEditing(false)}
          className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-lg bg-surface-700 text-text-secondary border border-surface-600 hover:bg-surface-600 transition-colors"
        >
          <Check className="w-3 h-3" aria-hidden="true" />
          {t.anchor.done}
        </button>
      )}
    </section>
  )
}

function describeReport(
  report: AnchorSaveReport,
  strings: { saved: string; savedRescored: string },
): string {
  if (!report.claims_total) return strings.saved
  return strings.savedRescored
    .replace('{rescored}', String(report.claims_rescored ?? 0))
    .replace('{total}', String(report.claims_total))
    .replace('{links}', String(report.links_inferred ?? 0))
}

function AnchorView({ anchor }: { anchor: DecisionAnchor }) {
  const { t } = useT()
  return (
    <div className="space-y-2 text-xs">
      {anchor.options.length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-wide text-text-muted mb-1">{t.anchor.options}</p>
          <div className="flex flex-wrap gap-1.5">
            {anchor.options.map((o) => (
              <span key={o.key} className="px-2 py-1 rounded-md bg-surface-700 border border-surface-600 text-text-secondary">
                <span className="font-mono text-[10px] text-text-muted mr-1">{o.key}</span>
                {o.label}
              </span>
            ))}
          </div>
        </div>
      )}
      {anchor.outcomes.length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-wide text-text-muted mb-1">{t.anchor.outcomes}</p>
          <ul className="space-y-0.5">
            {anchor.outcomes.map((y) => (
              <li key={y.key} className="text-text-secondary">
                <span className="font-mono text-[10px] text-amber-400/80 mr-1">{y.key}</span>
                {y.label}
                {y.measure && <span className="text-text-muted"> — {y.measure}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {(anchor.deadline || anchor.constraints.length > 0) && (
        <p className="text-text-muted">
          {anchor.deadline && <span>{t.anchor.deadline}: {anchor.deadline}</span>}
          {anchor.deadline && anchor.constraints.length > 0 && ' · '}
          {anchor.constraints.length > 0 && (
            <span>{t.anchor.constraints}: {anchor.constraints.join('; ')}</span>
          )}
        </p>
      )}
      {anchor.outcomes.length === 0 && (
        <p className="text-[11px] text-amber-400">{t.anchor.noOutcomes}</p>
      )}
    </div>
  )
}

function AnchorEditor({
  value,
  onChange,
}: {
  value: DecisionAnchor
  onChange: (anchor: DecisionAnchor) => void
}) {
  const { t } = useT()
  const set = (patch: Partial<DecisionAnchor>) => onChange({ ...value, ...patch })

  return (
    <div className="space-y-3" data-testid="decision-anchor-editor">
      <label className="block space-y-1">
        <span className="text-[10px] uppercase tracking-wide text-text-muted">{t.anchor.decision}</span>
        <textarea
          value={value.decision}
          rows={2}
          onChange={(e) => set({ decision: e.target.value })}
          className={`${inputClass} resize-y`}
        />
      </label>

      <fieldset className="space-y-1.5">
        <legend className="text-[10px] uppercase tracking-wide text-text-muted">{t.anchor.options}</legend>
        {value.options.map((option, index) => (
          <div key={option.key || `new-${index}`} className="flex items-center gap-1.5">
            <span className="w-7 shrink-0 font-mono text-[10px] text-text-muted">{option.key || '+'}</span>
            <input
              type="text"
              value={option.label}
              aria-label={`${t.anchor.options} ${index + 1}`}
              onChange={(e) =>
                set({
                  options: value.options.map((o, i) => (i === index ? { ...o, label: e.target.value } : o)),
                })
              }
              className={inputClass}
            />
            <RemoveButton
              label={t.anchor.remove}
              onClick={() => set({ options: value.options.filter((_, i) => i !== index) })}
            />
          </div>
        ))}
        {value.options.length < MAX_OPTIONS && (
          <AddButton
            label={t.anchor.addOption}
            onClick={() => set({ options: [...value.options, { key: '', label: '' }] })}
          />
        )}
      </fieldset>

      <fieldset className="space-y-1.5">
        <legend className="text-[10px] uppercase tracking-wide text-text-muted">{t.anchor.outcomes}</legend>
        <p className="text-[10px] text-text-muted">{t.anchor.outcomesHint}</p>
        {value.outcomes.map((outcome, index) => (
          <div key={outcome.key || `new-${index}`} className="flex items-center gap-1.5">
            <span className="w-7 shrink-0 font-mono text-[10px] text-amber-400/80">{outcome.key || '+'}</span>
            <input
              type="text"
              value={outcome.label}
              placeholder={t.anchor.outcomeLabel}
              aria-label={`${t.anchor.outcomes} ${index + 1}`}
              onChange={(e) =>
                set({
                  outcomes: value.outcomes.map((o, i) => (i === index ? { ...o, label: e.target.value } : o)),
                })
              }
              className={inputClass}
            />
            <input
              type="text"
              value={outcome.measure}
              placeholder={t.anchor.outcomeMeasure}
              aria-label={`${t.anchor.outcomeMeasure} ${index + 1}`}
              onChange={(e) =>
                set({
                  outcomes: value.outcomes.map((o, i) => (i === index ? { ...o, measure: e.target.value } : o)),
                })
              }
              className={`${inputClass} max-w-[40%]`}
            />
            <RemoveButton
              label={t.anchor.remove}
              onClick={() => set({ outcomes: value.outcomes.filter((_, i) => i !== index) })}
            />
          </div>
        ))}
        {value.outcomes.length < MAX_OUTCOMES && (
          <AddButton
            label={t.anchor.addOutcome}
            onClick={() => set({ outcomes: [...value.outcomes, { key: '', label: '', measure: '' }] })}
          />
        )}
      </fieldset>

      <label className="block space-y-1">
        <span className="text-[10px] uppercase tracking-wide text-text-muted">{t.anchor.deadline}</span>
        <input
          type="text"
          value={value.deadline}
          onChange={(e) => set({ deadline: e.target.value })}
          className={inputClass}
        />
      </label>

      <fieldset className="space-y-1.5">
        <legend className="text-[10px] uppercase tracking-wide text-text-muted">{t.anchor.constraints}</legend>
        {value.constraints.map((constraint, index) => (
          <div key={index} className="flex items-center gap-1.5">
            <input
              type="text"
              value={constraint}
              aria-label={`${t.anchor.constraints} ${index + 1}`}
              onChange={(e) =>
                set({
                  constraints: value.constraints.map((c, i) => (i === index ? e.target.value : c)),
                })
              }
              className={inputClass}
            />
            <RemoveButton
              label={t.anchor.remove}
              onClick={() => set({ constraints: value.constraints.filter((_, i) => i !== index) })}
            />
          </div>
        ))}
        {value.constraints.length < MAX_CONSTRAINTS && (
          <AddButton
            label={t.anchor.addConstraint}
            onClick={() => set({ constraints: [...value.constraints, ''] })}
          />
        )}
      </fieldset>
    </div>
  )
}

function AddButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1 px-2 py-1 text-[11px] rounded-md text-text-muted hover:text-text-primary hover:bg-surface-700 transition-colors"
    >
      <Plus className="w-3 h-3" aria-hidden="true" />
      {label}
    </button>
  )
}

function RemoveButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className="p-1 rounded-md text-text-muted hover:text-red-400 hover:bg-surface-700 transition-colors shrink-0"
    >
      <Trash2 className="w-3 h-3" aria-hidden="true" />
    </button>
  )
}
