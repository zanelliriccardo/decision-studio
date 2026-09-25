/**
 * A labelled switch.
 *
 * `role="switch"` rather than a styled checkbox: assistive technology announces
 * "on"/"off" rather than "checked", which is what this actually means.
 */
export default function Toggle({
  checked,
  onChange,
  label,
  hint,
  disabled = false,
}: {
  checked: boolean
  onChange: (next: boolean) => void
  label: string
  hint?: string
  disabled?: boolean
}) {
  return (
    <label
      className={`inline-flex items-start gap-2.5 ${
        disabled ? 'opacity-50' : 'cursor-pointer'
      }`}
    >
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => !disabled && onChange(!checked)}
        className={`relative mt-0.5 w-9 h-5 shrink-0 rounded-full transition-colors ${
          checked ? 'bg-ocean-500' : 'bg-surface-600'
        } ${disabled ? '' : 'hover:opacity-90'}`}
      >
        <span
          className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
            checked ? 'translate-x-[18px]' : 'translate-x-0.5'
          }`}
        />
      </button>
      <span className="min-w-0">
        <span className="text-xs text-text-secondary block">{label}</span>
        {hint && (
          <span className="text-[10px] text-text-muted block mt-0.5 leading-relaxed">
            {hint}
          </span>
        )}
      </span>
    </label>
  )
}
