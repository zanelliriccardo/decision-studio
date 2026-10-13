import { useEffect, useState } from 'react'
import { GitFork, Loader2, Plus, X } from 'lucide-react'
import { toast } from 'sonner'
import { useT } from '../../i18n/index.tsx'
import {
  fetchSubDecisions,
  saveSubDecisions,
  type SubDecision,
  type SubDecisionInput,
} from '../../lib/api/workspace.ts'

const pct = (p: number | null | undefined) => (p == null ? '—' : `${Math.round(p * 100)}%`)

type DraftChoice = { label: string; claimIds: string[]; filter: string }
type Draft = { parent: string; label: string; choices: DraftChoice[] }

const emptyChoice = (): DraftChoice => ({ label: '', claimIds: [], filter: '' })

/**
 * Sub-decisions: choices inside an option, each defined by existing claims and
 * evaluated as that option's intervention plus its claims on the same map.
 */
export default function SubDecisionsCard({
  projectId,
  options,
  claims,
  refreshKey,
  subDecisions: preloaded,
}: {
  projectId: string
  options: { key: string; label: string }[]
  claims: { id: string; text: string }[]
  refreshKey?: unknown
  subDecisions?: SubDecision[]
}) {
  const { t } = useT()
  const [items, setItems] = useState<SubDecision[] | null>(preloaded ?? null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (preloaded) return
    let cancelled = false
    fetchSubDecisions(projectId)
      .then((loaded) => !cancelled && setItems(loaded))
      .catch(() => !cancelled && setItems([]))
    return () => {
      cancelled = true
    }
  }, [projectId, refreshKey, preloaded])

  if (items === null || options.length === 0) return null

  const asInput = (sd: SubDecision): SubDecisionInput => ({
    parent: sd.parent,
    label: sd.label,
    choices: sd.choices.map((c) => ({ label: c.label, claim_ids: c.claims.map((x) => x.id) })),
  })

  async function persist(next: SubDecisionInput[]) {
    setBusy(true)
    try {
      setItems(await saveSubDecisions(projectId, next))
      setDraft(null)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t.workspace.subSaveFailed)
    } finally {
      setBusy(false)
    }
  }

  function submitDraft() {
    if (!draft) return
    const valid =
      draft.label.trim() &&
      draft.choices.length >= 2 && draft.choices.length <= 4 &&
      draft.choices.every((c) => c.label.trim() && c.claimIds.length > 0)
    if (!valid) {
      toast.error(t.workspace.subInvalid)
      return
    }
    void persist([
      ...items!.map(asInput),
      {
        parent: draft.parent,
        label: draft.label.trim(),
        choices: draft.choices.map((c) => ({ label: c.label.trim(), claim_ids: c.claimIds })),
      },
    ])
  }

  const setChoice = (index: number, patch: Partial<DraftChoice>) =>
    setDraft((d) => d && { ...d, choices: d.choices.map((c, i) => (i === index ? { ...c, ...patch } : c)) })

  return (
    <section className="rounded-xl border border-surface-700 bg-surface-800 p-4 space-y-2.5" data-testid="sub-decisions">
      <h2 className="text-xs font-semibold text-text-primary flex items-center gap-1.5">
        <GitFork className="w-3.5 h-3.5 text-text-muted" aria-hidden="true" />
        {t.workspace.subTitle}
      </h2>
      <p className="text-[11px] text-text-muted leading-relaxed">{t.workspace.subHint}</p>

      {items.length === 0 && !draft && <p className="text-[11px] text-text-muted">{t.workspace.subEmpty}</p>}

      {items.map((sd, index) => (
        <div key={sd.key} className="border-t border-surface-700 pt-2 space-y-1" data-testid="sub-decision">
          <div className="flex items-start justify-between gap-2">
            <p className="text-xs text-text-primary">
              <span className="font-mono text-text-muted mr-1">{sd.parent}</span>
              {sd.parentLabel} → {sd.label}
            </p>
            <button
              type="button"
              disabled={busy}
              onClick={() => void persist(items.filter((_, i) => i !== index).map(asInput))}
              className="text-[10px] text-text-muted hover:text-red-300"
              aria-label={`${t.workspace.remove} ${sd.label}`}
            >
              <X className="w-3 h-3" aria-hidden="true" />
            </button>
          </div>
          {sd.unavailable ? (
            <p className="text-[11px] text-amber-300" data-testid="sub-unavailable">{sd.unavailable}</p>
          ) : (
            <>
              <table className="w-full text-[11px]">
                <tbody>
                  {sd.choices.map((c) => (
                    <tr key={c.key} className="align-top" data-testid="sub-choice">
                      <td className="pr-2 text-text-secondary">{c.label}</td>
                      {sd.outcomes.map((o) => (
                        <td key={o.key} className="pr-2 text-text-muted">
                          {o.key} <span className="text-text-primary">{pct(c.outcomes[o.key]?.point)}</span>
                        </td>
                      ))}
                      <td className="text-right text-text-primary">
                        {c.weighted != null && `${Math.round(c.weighted * 100)} / 100`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {sd.sentence && <p className="text-[10px] text-text-secondary" data-testid="sub-sentence">{sd.sentence}</p>}
            </>
          )}
        </div>
      ))}

      {draft ? (
        <div className="border-t border-surface-700 pt-2 space-y-2" data-testid="sub-editor">
          <div className="flex flex-wrap gap-2">
            <label className="text-[10px] text-text-muted">
              {t.workspace.parent}{' '}
              <select
                value={draft.parent}
                onChange={(e) => setDraft({ ...draft, parent: e.target.value })}
                className="ml-1 px-1.5 py-0.5 text-[11px] bg-surface-700 border border-surface-600 rounded text-text-primary"
              >
                {options.map((o) => <option key={o.key} value={o.key}>{o.key} {o.label}</option>)}
              </select>
            </label>
            <input
              value={draft.label}
              onChange={(e) => setDraft({ ...draft, label: e.target.value })}
              placeholder={t.workspace.subLabel}
              aria-label={t.workspace.subLabel}
              className="flex-1 min-w-[10rem] px-2 py-1 text-[11px] bg-surface-700 border border-surface-600 rounded text-text-primary"
            />
          </div>
          {draft.choices.map((choice, index) => (
            <div key={index} className="rounded-md border border-surface-600 p-2 space-y-1" data-testid="choice-editor">
              <input
                value={choice.label}
                onChange={(e) => setChoice(index, { label: e.target.value })}
                placeholder={t.workspace.choicePlaceholder}
                aria-label={t.workspace.choiceLabel.replace('{n}', String(index + 1))}
                className="w-full px-2 py-1 text-[11px] bg-surface-700 border border-surface-600 rounded text-text-primary"
              />
              <p className="text-[10px] text-text-muted">{t.workspace.claimsFor}</p>
              <input
                value={choice.filter}
                onChange={(e) => setChoice(index, { filter: e.target.value })}
                placeholder={t.workspace.filterClaims}
                className="w-full px-2 py-0.5 text-[10px] bg-surface-700 border border-surface-600 rounded text-text-primary"
              />
              <div className="max-h-28 overflow-y-auto space-y-0.5">
                {claims
                  .filter((c) => !choice.filter || c.text.toLowerCase().includes(choice.filter.toLowerCase()))
                  .slice(0, 30)
                  .map((c) => (
                    <label key={c.id} className="flex gap-1.5 text-[10px] text-text-secondary">
                      <input
                        type="checkbox"
                        checked={choice.claimIds.includes(c.id)}
                        onChange={(e) =>
                          setChoice(index, {
                            claimIds: e.target.checked
                              ? [...choice.claimIds, c.id]
                              : choice.claimIds.filter((x) => x !== c.id),
                          })
                        }
                      />
                      {c.text}
                    </label>
                  ))}
              </div>
            </div>
          ))}
          <div className="flex flex-wrap gap-1.5">
            {draft.choices.length < 4 && (
              <button type="button" onClick={() => setDraft({ ...draft, choices: [...draft.choices, emptyChoice()] })}
                className="text-[10px] px-2 py-1 rounded-md bg-surface-700 text-text-secondary border border-surface-600">
                {t.workspace.addChoice}
              </button>
            )}
            <button type="button" disabled={busy} onClick={submitDraft}
              className="inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded-md bg-ocean-500/15 text-ocean-300 border border-ocean-500/30">
              {busy && <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" />}
              {t.workspace.saveSub}
            </button>
            <button type="button" onClick={() => setDraft(null)}
              className="text-[10px] px-2 py-1 rounded-md bg-surface-700 text-text-muted border border-surface-600">
              {t.workspace.cancel}
            </button>
          </div>
        </div>
      ) : (
        items.length < 6 && (
          <button
            type="button"
            onClick={() => setDraft({ parent: options[0].key, label: '', choices: [emptyChoice(), emptyChoice()] })}
            className="inline-flex items-center gap-1 text-[10px] text-ocean-300 hover:text-ocean-200"
          >
            <Plus className="w-3 h-3" aria-hidden="true" />
            {t.workspace.addSub}
          </button>
        )
      )}
    </section>
  )
}
