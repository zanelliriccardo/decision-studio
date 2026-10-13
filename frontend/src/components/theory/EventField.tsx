import { useEffect, useId, useState } from 'react'
import { useT } from '../../i18n/index.tsx'
import { fetchObservationEvents } from '../../lib/theoryValue.ts'

/**
 * Optional: which real-world event an observation came from.
 *
 * A tripwire and a link test often observe the same thing ("the vendor missed
 * 1 August"). Named the same, they count once against a theory's conviction
 * instead of compounding. Events already used in the project are offered, so
 * naming the same one again is a pick, not a retype.
 */
export default function EventField({
  projectId,
  value,
  onChange,
}: {
  projectId: string
  value: string
  onChange: (next: string) => void
}) {
  const { t } = useT()
  const listId = useId()
  const [known, setKnown] = useState<string[]>([])

  useEffect(() => {
    let cancelled = false
    fetchObservationEvents(projectId)
      .then((events) => {
        if (!cancelled) setKnown(events)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [projectId])

  return (
    <label className="block space-y-0.5">
      <span className="text-[10px] text-text-muted">{t.theoryValue.eventLabel}</span>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        list={listId}
        maxLength={200}
        placeholder={t.theoryValue.eventPlaceholder}
        title={t.theoryValue.eventHint}
        data-testid="observation-event"
        className="w-full px-2 py-1 text-[11px] bg-surface-700 border border-surface-600 rounded-md text-text-primary placeholder-text-muted focus:outline-none focus:border-ocean-500"
      />
      <datalist id={listId}>
        {known.map((event) => (
          <option key={event} value={event} />
        ))}
      </datalist>
    </label>
  )
}
