import { useT } from '../../i18n/index.tsx'
import type { Decisiveness } from '../../types/reasoning.ts'

const LEVELS: Decisiveness[] = ['weak', 'moderate', 'decisive']

/**
 * How much a test would count, stated before its result is known.
 *
 * "If this happens I drop the plan" and "this would be a warning sign" should
 * not move conviction by the same amount. Asked in advance, and locked once
 * the result is in, so the weight cannot be chosen to fit the result.
 */
export default function DecisivenessPicker({
  value,
  onChange,
  locked,
}: {
  value: Decisiveness
  onChange?: (next: Decisiveness) => void
  /** The result is in: shown, not editable. */
  locked?: boolean
}) {
  const { t } = useT()
  if (locked || !onChange) {
    return (
      <span className="text-[9px] text-text-muted" data-testid="decisiveness">
        {t.theoryValue.wouldCount}: {t.theoryValue.decisiveness[value]}
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1" data-testid="decisiveness" title={t.theoryValue.decisivenessHint}>
      <span className="text-[9px] text-text-muted">{t.theoryValue.wouldCount}:</span>
      {LEVELS.map((level) => (
        <button
          key={level}
          type="button"
          aria-pressed={value === level}
          onClick={() => onChange(level)}
          className={`text-[9px] px-1.5 py-0.5 rounded border transition-colors ${
            value === level
              ? 'bg-ocean-500/20 text-ocean-300 border-ocean-500/40'
              : 'bg-surface-700 text-text-muted border-surface-600 hover:bg-surface-600'
          }`}
        >
          {t.theoryValue.decisiveness[level]}
        </button>
      ))}
    </span>
  )
}
