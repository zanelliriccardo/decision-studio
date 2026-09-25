import { useState } from 'react'
import { Loader2, Plus, X } from 'lucide-react'
import { useT } from '../../i18n/index.tsx'
import type { ClaimType } from '../../types/graph.ts'

/**
 * Adds a claim the documents did not contain.
 *
 * In a strategic decision the factors that matter are frequently not written
 * down: the thing everyone in the room knows and nobody put in a document. Human
 * review could already reject and disable, so the graph could be pruned but not
 * corrected — this closes that.
 *
 * The type defaults to ASSUMPTION rather than FACT. Something the user asserts
 * from their own knowledge is, to the model, an assumption until evidence says
 * otherwise, and starting it as a fact would let an unevidenced belief carry the
 * same weight as a sourced one.
 */

const TYPES: { id: ClaimType; labelKey: 'fact' | 'assumption' | 'prediction' | 'opinion' }[] = [
  { id: 'ASSUMPTION', labelKey: 'assumption' },
  { id: 'FACT', labelKey: 'fact' },
  { id: 'PREDICTION', labelKey: 'prediction' },
  { id: 'OPINION', labelKey: 'opinion' },
]

export default function AddClaimDialog({
  saving,
  onConfirm,
  onCancel,
}: {
  saving: boolean
  onConfirm: (text: string, claimType: ClaimType) => void
  onCancel: () => void
}) {
  const { t } = useT()
  const [text, setText] = useState('')
  const [claimType, setClaimType] = useState<ClaimType>('ASSUMPTION')

  const canSave = text.trim().length > 2 && !saving

  return (
    <div
      className="absolute inset-0 z-50 flex items-center justify-center bg-black/50"
      role="dialog"
      aria-modal="true"
      aria-label={t.authoring.newClaim}
      data-testid="add-claim-dialog"
    >
      <div className="w-full max-w-md rounded-xl bg-surface-800 border border-surface-600 shadow-xl">
        <div className="flex items-center justify-between px-4 py-3 border-b border-surface-700">
          <h3 className="text-sm font-semibold text-text-primary">
            {t.authoring.newClaim}
          </h3>
          <button
            onClick={onCancel}
            className="p-1 rounded-md hover:bg-surface-700 text-text-muted hover:text-text-primary transition-colors"
            aria-label={t.common.close}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-4 space-y-3">
          <p className="text-[10px] text-text-muted leading-relaxed">
            {t.authoring.newClaimHint}
          </p>

          <div>
            <label
              htmlFor="claim-text"
              className="text-[11px] font-medium text-text-primary block mb-1"
            >
              {t.authoring.claimText}
            </label>
            <textarea
              id="claim-text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={3}
              placeholder={t.authoring.claimPlaceholder}
              className="w-full px-2 py-1.5 text-xs bg-surface-700 border border-surface-600 rounded-lg text-text-primary placeholder-text-muted focus:outline-none focus:border-ocean-500 transition-colors resize-none"
            />
          </div>

          <div>
            <span className="text-[11px] font-medium text-text-primary block mb-1">
              {t.authoring.claimType}
            </span>
            <div className="flex flex-wrap gap-1.5" role="group">
              {TYPES.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  aria-pressed={claimType === option.id}
                  onClick={() => setClaimType(option.id)}
                  className={`px-2 py-1 text-[11px] rounded-md border transition-colors ${
                    claimType === option.id
                      ? 'bg-ocean-500/20 text-ocean-300 border-ocean-500/40'
                      : 'bg-surface-700 text-text-secondary border-surface-600 hover:bg-surface-600'
                  }`}
                >
                  {t.claimTypes[option.labelKey]}
                </button>
              ))}
            </div>
            <p className="text-[10px] text-text-muted mt-1">
              {t.authoring.assumptionHint}
            </p>
          </div>
        </div>

        <div className="flex gap-2 px-4 py-3 border-t border-surface-700">
          <button
            type="button"
            disabled={!canSave}
            onClick={() => onConfirm(text.trim(), claimType)}
            className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg bg-ocean-500/15 text-ocean-300 border border-ocean-500/30 hover:bg-ocean-500/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {saving ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <Plus className="w-3.5 h-3.5" aria-hidden="true" />
            )}
            {t.authoring.createClaim}
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="px-3 py-2 text-xs rounded-lg bg-surface-700 text-text-secondary border border-surface-600 hover:bg-surface-600 transition-colors"
          >
            {t.review.cancel}
          </button>
        </div>
      </div>
    </div>
  )
}
