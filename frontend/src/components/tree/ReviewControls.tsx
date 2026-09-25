import { useEffect, useState } from 'react'
import {
  AlertTriangle, Check, CircleSlash, EyeOff, FileWarning, Loader2,
  RotateCcw, Star, Undo2, X,
} from 'lucide-react'
import { useT } from '../../i18n/index.tsx'
import type { ReviewPayload, ReviewStatus } from '../../types/reasoning.ts'
import Slider from '../ui/Slider.tsx'

/**
 * Review controls shared by the node and edge detail panels.
 *
 * Every status carries an icon as well as a colour, so the state is legible
 * without colour perception.
 */

export const REVIEW_STATUS_META: Record<
  ReviewStatus,
  { icon: React.ComponentType<{ className?: string }>; classes: string }
> = {
  accepted: {
    icon: Check,
    classes: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  },
  rejected: {
    icon: X,
    classes: 'bg-red-500/15 text-red-400 border-red-500/30',
  },
  uncertain: {
    icon: AlertTriangle,
    classes: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  },
  business_critical: {
    icon: Star,
    classes: 'bg-ocean-500/15 text-ocean-400 border-ocean-500/30',
  },
  not_relevant: {
    icon: CircleSlash,
    classes: 'bg-surface-600/40 text-text-muted border-surface-500/30',
  },
  needs_evidence: {
    icon: FileWarning,
    classes: 'bg-purple-500/15 text-purple-300 border-purple-500/30',
  },
}

const STATUS_ORDER: ReviewStatus[] = [
  'accepted',
  'uncertain',
  'business_critical',
  'needs_evidence',
  'not_relevant',
  'rejected',
]

/** Status pill used in detail panels and theory cards. */
export function ReviewStatusBadge({
  status,
  isActive = true,
  className = '',
}: {
  status: ReviewStatus
  isActive?: boolean
  className?: string
}) {
  const { t } = useT()
  const meta = REVIEW_STATUS_META[status] ?? REVIEW_STATUS_META.accepted
  const Icon = meta.icon
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium border ${meta.classes} ${className}`}
      title={t.review.statusLabels[status]}
    >
      <Icon className="w-3 h-3 shrink-0" aria-hidden="true" />
      {t.review.statusLabels[status]}
      {!isActive && (
        <>
          <span className="sr-only">, </span>
          <EyeOff className="w-3 h-3 shrink-0" aria-hidden="true" />
        </>
      )}
    </span>
  )
}

interface ReviewControlsProps {
  targetType: 'claim' | 'edge'
  status: ReviewStatus
  isActive: boolean
  userNote: string | null
  /** Edge only: the AI-inferred strength, shown alongside any override. */
  aiStrength?: number
  strengthOverride?: number | null
  busy?: boolean
  /** Set when current theories would be made stale by an edit. */
  hasTheories?: boolean
  onReview: (payload: ReviewPayload) => void | Promise<void>
}

export default function ReviewControls({
  targetType,
  status,
  isActive,
  userNote,
  aiStrength,
  strengthOverride,
  busy = false,
  hasTheories = false,
  onReview,
}: ReviewControlsProps) {
  const { t } = useT()
  const [note, setNote] = useState(userNote ?? '')
  const [noteDirty, setNoteDirty] = useState(false)
  const [pendingOverride, setPendingOverride] = useState<number | null>(
    strengthOverride ?? null,
  )
  const [confirmReject, setConfirmReject] = useState(false)

  useEffect(() => {
    setNote(userNote ?? '')
    setNoteDirty(false)
  }, [userNote])

  useEffect(() => {
    setPendingOverride(strengthOverride ?? null)
  }, [strengthOverride])

  const handleStatus = (next: ReviewStatus) => {
    // Rejecting removes the element from every future theory, so make the
    // user say it twice.
    if (next === 'rejected' && !confirmReject) {
      setConfirmReject(true)
      return
    }
    setConfirmReject(false)
    void onReview({ review_status: next })
  }

  return (
    <div className="space-y-3 pt-3 border-t border-surface-700">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-semibold text-text-primary">
          {t.review.sectionTitle}
        </h4>
        {busy && <Loader2 className="w-3.5 h-3.5 text-ocean-400 animate-spin" />}
      </div>

      {hasTheories && (
        <p className="text-[11px] text-amber-400/90 flex items-start gap-1.5">
          <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" aria-hidden="true" />
          {t.review.staleWarning}
        </p>
      )}

      {/* Status */}
      <div>
        <label className="text-[11px] font-medium text-text-muted block mb-1.5">
          {t.review.statusLabel}
        </label>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label={t.review.statusLabel}>
          {STATUS_ORDER.map((option) => {
            const meta = REVIEW_STATUS_META[option]
            const Icon = meta.icon
            const selected = status === option
            return (
              <button
                key={option}
                type="button"
                disabled={busy}
                aria-pressed={selected}
                onClick={() => handleStatus(option)}
                className={`inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium border transition-colors disabled:opacity-50 ${
                  selected
                    ? meta.classes
                    : 'bg-surface-700 text-text-muted border-surface-600 hover:text-text-secondary hover:bg-surface-600'
                }`}
              >
                <Icon className="w-3 h-3 shrink-0" aria-hidden="true" />
                {t.review.statusLabels[option]}
              </button>
            )
          })}
        </div>
        {confirmReject && (
          <div className="mt-2 p-2 rounded-lg bg-red-500/10 border border-red-500/30 space-y-2">
            <p className="text-[11px] text-red-300">{t.review.confirmReject}</p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => handleStatus('rejected')}
                className="px-2 py-1 text-[10px] rounded-md bg-red-500/20 text-red-300 border border-red-500/40 hover:bg-red-500/30 transition-colors"
              >
                {t.review.confirmRejectYes}
              </button>
              <button
                type="button"
                onClick={() => setConfirmReject(false)}
                className="px-2 py-1 text-[10px] rounded-md bg-surface-700 text-text-secondary border border-surface-600 hover:bg-surface-600 transition-colors"
              >
                {t.review.cancel}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Active / inactive */}
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[11px] font-medium text-text-muted">
            {isActive ? t.review.activeLabel : t.review.inactiveLabel}
          </p>
          <p className="text-[10px] text-text-muted/70">
            {isActive ? t.review.activeHint : t.review.inactiveHint}
          </p>
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={() => void onReview({ is_active: !isActive })}
          className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 text-[11px] rounded-lg border transition-colors shrink-0 disabled:opacity-50 ${
            isActive
              ? 'bg-surface-700 text-text-secondary border-surface-600 hover:bg-surface-600'
              : 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/25'
          }`}
        >
          {isActive ? (
            <>
              <EyeOff className="w-3 h-3" aria-hidden="true" />
              {t.review.disable}
            </>
          ) : (
            <>
              <RotateCcw className="w-3 h-3" aria-hidden="true" />
              {t.review.restore}
            </>
          )}
        </button>
      </div>

      {/* Strength override (edges only) */}
      {targetType === 'edge' && aiStrength !== undefined && (
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="text-[11px] font-medium text-text-muted">
              {t.review.strengthOverride}
            </label>
            {strengthOverride !== null && strengthOverride !== undefined && (
              <button
                type="button"
                disabled={busy}
                onClick={() => void onReview({ clear_strength_override: true })}
                className="inline-flex items-center gap-1 text-[10px] text-text-muted hover:text-text-primary transition-colors disabled:opacity-50"
              >
                <Undo2 className="w-3 h-3" aria-hidden="true" />
                {t.review.clearOverride}
              </button>
            )}
          </div>
          <Slider
            aria-label={t.review.strengthOverride}
            value={pendingOverride ?? aiStrength}
            min={0}
            max={1}
            step={0.05}
            onChange={setPendingOverride}
            showValue
          />
          <div className="flex items-center justify-between mt-1">
            <span className="text-[10px] text-text-muted">
              {t.review.aiStrength}: {aiStrength.toFixed(2)}
              {strengthOverride !== null && strengthOverride !== undefined && (
                <span className="ml-1.5 px-1 py-0.5 rounded bg-ocean-500/15 text-ocean-400 border border-ocean-500/30">
                  {t.review.overridden}
                </span>
              )}
            </span>
            {pendingOverride !== null && pendingOverride !== strengthOverride && (
              <button
                type="button"
                disabled={busy}
                onClick={() => void onReview({ strength_override: pendingOverride })}
                className="px-2 py-1 text-[10px] rounded-md bg-ocean-500/15 text-ocean-400 border border-ocean-500/30 hover:bg-ocean-500/25 transition-colors disabled:opacity-50"
              >
                {t.review.saveOverride}
              </button>
            )}
          </div>
        </div>
      )}

      {/* User note */}
      <div>
        <label
          htmlFor={`review-note-${targetType}`}
          className="text-[11px] font-medium text-text-muted block mb-1"
        >
          {t.review.noteLabel}
        </label>
        <textarea
          id={`review-note-${targetType}`}
          value={note}
          onChange={(e) => {
            setNote(e.target.value)
            setNoteDirty(true)
          }}
          rows={2}
          placeholder={t.review.notePlaceholder}
          className="w-full px-2 py-1.5 text-xs bg-surface-700 border border-surface-600 rounded-lg text-text-primary placeholder-text-muted focus:outline-none focus:border-ocean-500 transition-colors resize-none"
        />
        {noteDirty && (
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              void onReview({ user_note: note })
              setNoteDirty(false)
            }}
            className="mt-1.5 px-2 py-1 text-[10px] rounded-md bg-ocean-500/15 text-ocean-400 border border-ocean-500/30 hover:bg-ocean-500/25 transition-colors disabled:opacity-50"
          >
            {t.review.saveNote}
          </button>
        )}
      </div>
    </div>
  )
}
