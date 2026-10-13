/** One descriptive evidence label, as the server computes it (reasoning/evidence_quality.py). */
export interface QualityLabel {
  key: string
  text: string
  tone: 'good' | 'neutral' | 'caution'
}

const TONE: Record<QualityLabel['tone'], string> = {
  good: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30',
  neutral: 'text-text-secondary bg-surface-700 border-surface-600',
  caution: 'text-amber-300 bg-amber-500/10 border-amber-500/30',
}

/**
 * Evidence quality as small facts — recent, independent, direct, decisive, or
 * their opposites — rather than one opaque score, so the reader sees why.
 */
export default function QualityChips({ labels }: { labels: QualityLabel[] | undefined }) {
  if (!labels || labels.length === 0) return null
  return (
    <span className="inline-flex flex-wrap gap-1" data-testid="quality-chips">
      {labels.map((l) => (
        <span
          key={l.key}
          className={`px-1.5 py-0.5 rounded border text-[9px] leading-none ${TONE[l.tone] ?? TONE.neutral}`}
          data-tone={l.tone}
        >
          {l.text}
        </span>
      ))}
    </span>
  )
}
