import { useState } from 'react'
import { ArrowRight, Loader2, X } from 'lucide-react'
import { useT } from '../../i18n/index.tsx'
import Slider from '../ui/Slider.tsx'

/**
 * Confirms a causal link drawn on the graph.
 *
 * The mechanism is required, and that is the point of this dialog existing at
 * all: a link without a mechanism is a correlation someone has drawn an arrow
 * on. Asking "how does the cause act?" at the moment of drawing is the cheapest
 * place to catch a link that turns out not to be causal — the author usually
 * discovers it themselves while trying to write the sentence.
 *
 * Effect and confidence default to 0.5 rather than to something confident. A
 * link the user has just thought of has not been evidenced yet, and the
 * evidence floor keeps it propagating meanwhile.
 */
export default function LinkDialog({
  sourceText,
  targetText,
  saving,
  onConfirm,
  onCancel,
}: {
  sourceText: string
  targetText: string
  saving: boolean
  onConfirm: (mechanism: string, effect: number, confidence: number) => void
  onCancel: () => void
}) {
  const { t } = useT()
  const [mechanism, setMechanism] = useState('')
  const [effect, setEffect] = useState(0.5)
  const [confidence, setConfidence] = useState(0.5)

  const canSave = mechanism.trim().length > 0 && !saving

  return (
    <div
      className="absolute inset-0 z-50 flex items-center justify-center bg-black/50"
      role="dialog"
      aria-modal="true"
      aria-label={t.authoring.newLink}
      data-testid="link-dialog"
    >
      <div className="w-full max-w-md rounded-xl bg-surface-800 border border-surface-600 shadow-xl">
        <div className="flex items-center justify-between px-4 py-3 border-b border-surface-700">
          <h3 className="text-sm font-semibold text-text-primary">
            {t.authoring.newLink}
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
          <div className="flex items-start gap-2 text-xs">
            <span className="flex-1 text-text-secondary">{sourceText}</span>
            <ArrowRight
              className="w-4 h-4 text-ocean-400 mt-0.5 shrink-0"
              aria-hidden="true"
            />
            <span className="flex-1 text-text-secondary">{targetText}</span>
          </div>

          <div>
            <label
              htmlFor="link-mechanism"
              className="text-[11px] font-medium text-text-primary block mb-1"
            >
              {t.authoring.mechanism}
              <span className="ml-1 text-amber-400" title={t.authoring.mechanismRequired}>
                *
              </span>
            </label>
            <p className="text-[10px] text-text-muted mb-1.5">
              {t.authoring.mechanismHint}
            </p>
            <textarea
              id="link-mechanism"
              value={mechanism}
              onChange={(e) => setMechanism(e.target.value)}
              rows={3}
              placeholder={t.authoring.mechanismPlaceholder}
              className="w-full px-2 py-1.5 text-xs bg-surface-700 border border-surface-600 rounded-lg text-text-primary placeholder-text-muted focus:outline-none focus:border-ocean-500 transition-colors resize-none"
            />
          </div>

          <div className="space-y-2">
            <Slider
              aria-label={t.scores.effect}
              value={effect}
              min={0}
              max={1}
              step={0.05}
              onChange={setEffect}
              showValue
            />
            <p className="text-[10px] text-text-muted -mt-1">
              {t.scores.effect}: {t.scores.effectHint}
            </p>

            <Slider
              aria-label={t.scores.linkConfidence}
              value={confidence}
              min={0}
              max={1}
              step={0.05}
              onChange={setConfidence}
              showValue
            />
            <p className="text-[10px] text-text-muted -mt-1">
              {t.scores.linkConfidence}: {t.scores.linkConfidenceHint}
            </p>
          </div>

          <p className="text-[10px] text-text-muted">{t.authoring.notSearchedYet}</p>
        </div>

        <div className="flex gap-2 px-4 py-3 border-t border-surface-700">
          <button
            type="button"
            disabled={!canSave}
            onClick={() => onConfirm(mechanism.trim(), effect, confidence)}
            className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg bg-ocean-500/15 text-ocean-300 border border-ocean-500/30 hover:bg-ocean-500/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />}
            {t.authoring.createLink}
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
