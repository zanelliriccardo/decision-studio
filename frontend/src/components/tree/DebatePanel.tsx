import { useState } from 'react'
import {
  AlertTriangle, Copy, Crosshair, GitCompare, Layers, Loader2, Radar, Scale, X,
} from 'lucide-react'
import { useT } from '../../i18n/index.tsx'
import type { Debate, DebateRelation, Theory } from '../../types/reasoning.ts'

/**
 * The Comparisons tab.
 *
 * A comparison sits *between* two theories rather than belonging to either, so
 * it gets its own tab instead of a section inside a theory card.
 *
 * The three relations are shown very differently on purpose:
 *
 *  - `competing` leads, because it is the only one that produces work.
 *  - `orthogonal` carries a prominent "both may hold" warning, because that is
 *    the case a ranked list actively hides: presenting two theories as first
 *    and second implies choosing between them.
 *  - `same_story` collapses to a grey line. It is a non-result, and giving it
 *    equal weight would be noise.
 */

const RELATION_META: Record<
  DebateRelation,
  { icon: React.ComponentType<{ className?: string }>; classes: string; rank: number }
> = {
  competing: {
    icon: Scale,
    classes: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
    rank: 0,
  },
  orthogonal: {
    icon: Layers,
    classes: 'bg-ocean-500/15 text-ocean-400 border-ocean-500/30',
    rank: 1,
  },
  same_story: {
    icon: Copy,
    classes: 'bg-surface-600/40 text-text-muted border-surface-500/30',
    rank: 2,
  },
}

function theoryTitle(theories: Theory[], id: string): string {
  return theories.find((t) => t.id === id)?.title ?? id.slice(0, 8)
}

function SameStoryRow({
  debate,
  theories,
}: {
  debate: Debate
  theories: Theory[]
}) {
  const { t } = useT()
  return (
    <div
      className="flex items-start gap-1.5 px-2 py-1.5 rounded-md bg-surface-800/50 border border-surface-700"
      data-testid="debate-same-story"
    >
      <Copy className="w-3 h-3 text-text-muted mt-0.5 shrink-0" aria-hidden="true" />
      <p className="text-[10px] text-text-muted">
        <span className="text-text-secondary">
          {theoryTitle(theories, debate.theoryAId)}
        </span>
        {' ≈ '}
        <span className="text-text-secondary">
          {theoryTitle(theories, debate.theoryBId)}
        </span>
        {' — '}
        {t.debate.sameStoryShort.replace(
          '{pct}',
          `${Math.round(debate.overlapJaccard * 100)}`,
        )}
      </p>
    </div>
  )
}

function DebateCard({
  debate,
  theories,
  selected,
  onSelect,
  onPromote,
  promoting,
}: {
  debate: Debate
  theories: Theory[]
  selected: boolean
  onSelect: (debate: Debate | null) => void
  onPromote?: (debateId: string) => void
  promoting?: boolean
}) {
  const { t } = useT()
  const [confirming, setConfirming] = useState(false)
  const meta = RELATION_META[debate.relation]
  const Icon = meta.icon

  return (
    <article
      className={`rounded-lg border p-3 space-y-2 transition-colors ${
        selected
          ? 'border-ocean-500/60 bg-ocean-500/5'
          : 'border-surface-600 bg-surface-800 hover:border-surface-500'
      }`}
      data-testid="debate-card"
      data-relation={debate.relation}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <span
          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium border ${meta.classes}`}
        >
          <Icon className="w-3 h-3 shrink-0" aria-hidden="true" />
          {t.debate.relations[debate.relation]}
        </span>
        <span className="text-[10px] text-text-muted">
          {t.debate.overlap}: {Math.round(debate.overlapJaccard * 100)}%
        </span>
      </div>

      <p className="text-xs text-text-primary leading-snug">
        <span className="font-medium">{theoryTitle(theories, debate.theoryAId)}</span>
        <span className="text-text-muted"> {t.debate.versus} </span>
        <span className="font-medium">{theoryTitle(theories, debate.theoryBId)}</span>
      </p>

      {/* Orthogonal: the case a ranked list hides. */}
      {debate.bothPossible && (
        <div
          className="flex items-start gap-1.5 px-2 py-1.5 rounded-md bg-ocean-500/10 border border-ocean-500/30"
          data-testid="both-possible"
        >
          <Layers className="w-3 h-3 text-ocean-400 mt-0.5 shrink-0" aria-hidden="true" />
          <span className="text-[10px] text-ocean-200">{t.debate.bothPossible}</span>
        </div>
      )}

      {debate.crux && (
        <div>
          <h5 className="text-[10px] font-semibold text-text-muted mb-0.5">
            {t.debate.crux}
          </h5>
          <p className="text-[11px] text-text-secondary leading-relaxed">
            {debate.crux}
          </p>
        </div>
      )}

      {/* The discriminator, or the fact that none exists. */}
      {debate.discriminatorFeasible && debate.discriminator ? (
        <div
          className="px-2 py-1.5 rounded-md bg-surface-700/60 border border-surface-600 space-y-1.5"
          data-testid="discriminator"
        >
          <h5 className="flex items-center gap-1.5 text-[10px] font-semibold text-text-secondary">
            <Radar className="w-3 h-3" aria-hidden="true" />
            {t.debate.discriminator}
            {debate.discriminatorHorizonDays ? (
              <span className="font-normal text-text-muted">
                · {debate.discriminatorHorizonDays} {t.debate.days}
              </span>
            ) : null}
          </h5>
          <p className="text-[11px] text-text-secondary">{debate.discriminator}</p>

          {debate.promotedTripwireAt ? (
            <p className="text-[10px] text-emerald-400">{t.debate.alreadyPromoted}</p>
          ) : (
            onPromote && (
              <>
                {confirming ? (
                  <div className="space-y-1.5">
                    <p className="text-[10px] text-amber-300">
                      {t.debate.confirmPromote}
                    </p>
                    <div className="flex gap-1.5">
                      <button
                        type="button"
                        disabled={promoting}
                        onClick={() => {
                          onPromote(debate.id)
                          setConfirming(false)
                        }}
                        className="px-2 py-1 text-[10px] rounded-md bg-ocean-500/20 text-ocean-300 border border-ocean-500/40 hover:bg-ocean-500/30 transition-colors disabled:opacity-50"
                      >
                        {t.debate.confirmPromoteYes}
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirming(false)}
                        className="px-2 py-1 text-[10px] rounded-md bg-surface-700 text-text-secondary border border-surface-600 hover:bg-surface-600 transition-colors"
                      >
                        {t.review.cancel}
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setConfirming(true)}
                    className="inline-flex items-center gap-1 px-2 py-1 text-[10px] rounded-md bg-surface-700 text-text-secondary border border-surface-600 hover:bg-surface-600 transition-colors"
                  >
                    <Radar className="w-3 h-3" aria-hidden="true" />
                    {t.debate.promote}
                  </button>
                )}
              </>
            )
          )}
        </div>
      ) : (
        debate.relation === 'competing' && (
          <div
            className="flex items-start gap-1.5 px-2 py-1.5 rounded-md bg-amber-500/10 border border-amber-500/30"
            data-testid="no-discriminator"
          >
            <AlertTriangle
              className="w-3 h-3 text-amber-400 mt-0.5 shrink-0"
              aria-hidden="true"
            />
            <span className="text-[10px] text-amber-200">
              {t.debate.noDiscriminator}
            </span>
          </div>
        )
      )}

      <button
        type="button"
        onClick={() => onSelect(selected ? null : debate)}
        aria-pressed={selected}
        className={`inline-flex items-center gap-1.5 px-2 py-1 text-[10px] rounded-md border transition-colors ${
          selected
            ? 'bg-ocean-500/20 text-ocean-300 border-ocean-500/40'
            : 'bg-surface-700 text-text-secondary border-surface-600 hover:bg-surface-600'
        }`}
      >
        <Crosshair className="w-3 h-3" aria-hidden="true" />
        {selected ? t.debate.clearHighlight : t.debate.highlight}
      </button>
    </article>
  )
}

interface DebatePanelProps {
  debates: Debate[]
  theories: Theory[]
  loading: boolean
  running: boolean
  promoting: boolean
  error: string | null
  selectedDebateId: string | null
  onSelectDebate: (debate: Debate | null) => void
  onRun: () => void
  onPromote: (debateId: string) => void
  onClose: () => void
}

export default function DebatePanel({
  debates,
  theories,
  loading,
  running,
  promoting,
  error,
  selectedDebateId,
  onSelectDebate,
  onRun,
  onPromote,
  onClose,
}: DebatePanelProps) {
  const { t } = useT()

  const ordered = [...debates].sort(
    (a, b) => RELATION_META[a.relation].rank - RELATION_META[b.relation].rank,
  )
  const substantive = ordered.filter((d) => d.relation !== 'same_story')
  const restatements = ordered.filter((d) => d.relation === 'same_story')
  const canRun = theories.length >= 2

  return (
    <div className="w-full bg-surface-800 border-l border-surface-700 h-full overflow-y-auto flex flex-col">
      <div className="flex items-center justify-between p-4 border-b border-surface-700 shrink-0">
        <div className="flex items-center gap-2">
          <GitCompare className="w-4 h-4 text-ocean-400" aria-hidden="true" />
          <h3 className="text-sm font-semibold text-text-primary">{t.debate.title}</h3>
          {substantive.length > 0 && (
            <span className="text-[10px] text-text-muted bg-surface-700 px-1.5 py-0.5 rounded-full">
              {substantive.length}
            </span>
          )}
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded-md hover:bg-surface-700 text-text-muted hover:text-text-primary transition-colors"
          aria-label={t.common.close}
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="p-4 space-y-3 flex-1">
        <p className="text-[11px] text-text-muted leading-relaxed">{t.debate.intro}</p>

        <button
          type="button"
          onClick={onRun}
          disabled={running || !canRun}
          title={canRun ? undefined : t.debate.needTwo}
          className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg bg-ocean-500/15 text-ocean-300 border border-ocean-500/30 hover:bg-ocean-500/25 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {running ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
          ) : (
            <GitCompare className="w-3.5 h-3.5" aria-hidden="true" />
          )}
          {running ? t.debate.running : t.debate.run}
        </button>

        {!canRun && (
          <p className="text-[10px] text-text-muted" data-testid="need-two-theories">
            {t.debate.needTwo}
          </p>
        )}

        {loading && (
          <div
            className="flex items-center justify-center gap-2 py-8 text-text-muted"
            data-testid="debates-loading"
          >
            <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
            <span className="text-xs">{t.common.loading}</span>
          </div>
        )}

        {!loading && error && (
          <div
            className="px-3 py-3 rounded-lg bg-red-500/10 border border-red-500/30"
            role="alert"
            data-testid="debates-error"
          >
            <p className="text-xs text-red-300">{error}</p>
          </div>
        )}

        {!loading && !error && debates.length === 0 && (
          <div className="py-8 text-center" data-testid="debates-empty">
            <GitCompare
              className="w-6 h-6 text-text-muted mx-auto mb-2"
              aria-hidden="true"
            />
            <p className="text-xs text-text-muted">{t.debate.empty}</p>
            <p className="text-[10px] text-text-muted/70 mt-1">{t.debate.emptyHint}</p>
          </div>
        )}

        <div className="space-y-2.5">
          {substantive.map((debate) => (
            <DebateCard
              key={debate.id}
              debate={debate}
              theories={theories}
              selected={selectedDebateId === debate.id}
              onSelect={onSelectDebate}
              onPromote={onPromote}
              promoting={promoting}
            />
          ))}
        </div>

        {/* Restatements are a non-result: acknowledged, not dwelt on. */}
        {restatements.length > 0 && (
          <section className="space-y-1.5 pt-1">
            <h4 className="text-[10px] font-semibold text-text-muted">
              {t.debate.restatements} ({restatements.length})
            </h4>
            {restatements.map((debate) => (
              <SameStoryRow key={debate.id} debate={debate} theories={theories} />
            ))}
          </section>
        )}
      </div>
    </div>
  )
}
