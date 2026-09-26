import { useMemo, useState } from 'react'
import EventField from '../theory/EventField.tsx'
import {
  AlertTriangle, ChevronDown, ChevronRight, CircleHelp, Crosshair, FileWarning,
  GitBranch, Lightbulb, Loader2, RefreshCw, Scale, ShieldCheck,
  History, Radar, ShieldAlert, Sparkles, Target, X,
} from 'lucide-react'
import { useT } from '../../i18n/index.tsx'
import type { CausalGraph } from '../../types/graph.ts'
import type {
  BusinessImpact, ChangeSummary, Theory, TheoryStatus,
} from '../../types/reasoning.ts'
import Progress from '../ui/Progress.tsx'
import TheoryValueSection from '../theory/TheoryValueSection.tsx'
import OptionCoverageStrip from '../theory/OptionCoverageStrip.tsx'

/**
 * The Theories tab.
 *
 * Selecting a theory hands its supporting subgraph to the caller, which routes
 * it through the graph's existing focus mechanism — highlighting is a view
 * state, never a mutation of the graph.
 */

const STATUS_META: Record<
  TheoryStatus,
  { icon: React.ComponentType<{ className?: string }>; classes: string }
> = {
  supported: { icon: ShieldCheck, classes: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30' },
  hypothesis: { icon: Lightbulb, classes: 'bg-ocean-500/15 text-ocean-400 border-ocean-500/30' },
  contested: { icon: Scale, classes: 'bg-amber-500/15 text-amber-400 border-amber-500/30' },
  insufficient_evidence: { icon: FileWarning, classes: 'bg-purple-500/15 text-purple-300 border-purple-500/30' },
  superseded: { icon: CircleHelp, classes: 'bg-surface-600/40 text-text-muted border-surface-500/30' },
}

const IMPACT_META: Record<BusinessImpact, string> = {
  critical: 'bg-red-500/15 text-red-400 border-red-500/30',
  high: 'bg-orange-500/15 text-orange-400 border-orange-500/30',
  medium: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30',
  low: 'bg-surface-600/40 text-text-muted border-surface-500/30',
}

/** Objection severity shown as a band too -- same reason as confidence. */
function severityBand(value: number): 'very_low' | 'low' | 'moderate' | 'high' | 'very_high' {
  if (value < 0.2) return 'very_low'
  if (value < 0.4) return 'low'
  if (value < 0.6) return 'moderate'
  if (value < 0.8) return 'high'
  return 'very_high'
}

const IMPACT_BARS: Record<BusinessImpact, number> = {
  critical: 4,
  high: 3,
  medium: 2,
  low: 1,
}

export function TheoryStatusBadge({ status }: { status: TheoryStatus }) {
  const { t } = useT()
  const meta = STATUS_META[status] ?? STATUS_META.hypothesis
  const Icon = meta.icon
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium border ${meta.classes}`}
    >
      <Icon className="w-3 h-3 shrink-0" aria-hidden="true" />
      {t.theories.status[status]}
    </span>
  )
}

/** Impact is shown as a bar count as well as a colour, for colour-blind users. */
export function ImpactBadge({ impact }: { impact: BusinessImpact }) {
  const { t } = useT()
  const filled = IMPACT_BARS[impact] ?? 1
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[10px] font-medium border ${IMPACT_META[impact]}`}
      title={`${t.theories.impactLabel}: ${t.theories.impact[impact]}`}
    >
      <span className="flex items-end gap-[1px]" aria-hidden="true">
        {[1, 2, 3, 4].map((level) => (
          <span
            key={level}
            className={`w-[2px] rounded-sm ${level <= filled ? 'bg-current' : 'bg-current opacity-25'}`}
            style={{ height: `${3 + level * 2}px` }}
          />
        ))}
      </span>
      {t.theories.impact[impact]}
    </span>
  )
}

interface TheoryCardProps {
  theory: Theory
  graph: CausalGraph | null
  selected: boolean
  onSelect: (theory: Theory | null) => void
  onDismissObjection?: (objectionId: string) => void
  onObserveTripwire?: (tripwireId: string, observed: boolean, event?: string) => void
  onTheoriesChanged?: () => void
}

function TheoryCard({
  theory, graph, selected, onSelect,
  onDismissObjection, onObserveTripwire, onTheoriesChanged,
}: TheoryCardProps) {
  const { t } = useT()
  const [expanded, setExpanded] = useState(false)
  const [tripwireEvent, setTripwireEvent] = useState('')

  const evidence = useMemo(() => {
    if (!graph) return { supporting: [], contradicting: [] }
    const all = graph.edges.flatMap((edge) => edge.evidences)
    return {
      supporting: all.filter((ev) => theory.supportingEvidenceIds.includes(ev.id)),
      contradicting: all.filter((ev) =>
        theory.contradictingEvidenceIds.includes(ev.id),
      ),
    }
  }, [graph, theory])


  return (
    <article
      className={`rounded-lg border transition-colors ${
        selected
          ? 'border-ocean-500/60 bg-ocean-500/5'
          : 'border-surface-600 bg-surface-800 hover:border-surface-500'
      } ${theory.isStale ? 'opacity-90' : ''}`}
      data-testid="theory-card"
      data-stale={theory.isStale}
    >
      <div className="p-3 space-y-2">
        {theory.isStale && (
          <div
            className="flex items-start gap-1.5 px-2 py-1.5 rounded-md bg-amber-500/10 border border-amber-500/30"
            role="status"
            data-testid="stale-indicator"
          >
            <AlertTriangle className="w-3 h-3 text-amber-400 mt-0.5 shrink-0" aria-hidden="true" />
            <span className="text-[10px] text-amber-300">
              {t.theories.stale}
              {theory.staleReason ? ` — ${theory.staleReason}` : ''}
            </span>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-1.5">
          <TheoryStatusBadge status={theory.status} />
          <ImpactBadge impact={theory.businessImpact} />
          {theory.changeKind && theory.changeKind !== 'unchanged' && (
            <span className="px-1.5 py-0.5 rounded text-[9px] font-medium bg-surface-700 text-text-secondary border border-surface-600">
              {t.theories.changeKind[theory.changeKind]}
            </span>
          )}
        </div>

        <h4 className="text-sm font-semibold text-text-primary leading-snug">
          {theory.title}
        </h4>
        <p className="text-xs text-text-secondary leading-relaxed">{theory.summary}</p>

        {/* The option it argues about, the decider's conviction, and the tests
            that can move it. */}
        <TheoryValueSection
          theory={theory}
          anchor={graph?.decisionAnchor}
          onChanged={onTheoriesChanged}
        />

        {/* Confidence as a band. Nothing here has ever been calibrated, so a
            percentage asserts a resolution the pipeline does not possess. */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] font-medium text-text-muted">
              {t.theories.confidence}
            </span>
            <span
              className="text-[10px] text-text-secondary"
              title={t.theories.bandHint}
              data-testid="confidence-band"
            >
              {t.bands[theory.confidenceBand]}
            </span>
          </div>
          <Progress value={theory.confidence} />
          {theory.contested && (
            <p
              className="text-[10px] text-amber-400 mt-1 flex items-start gap-1"
              data-testid="contested-flag"
            >
              <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" aria-hidden="true" />
              {t.adversary.contestedHint}
            </p>
          )}
        </div>

        {/* Outside view: how this compares with cases the user has actually seen.
            Shown next to confidence rather than buried, because the inside-view
            error is precisely that this comparison never gets made. */}
        {theory.outsideViewNote && (
          <div
            className={`flex items-start gap-1.5 px-2 py-1.5 rounded-md border ${
              theory.outsideViewDelta !== null &&
              Math.abs(theory.outsideViewDelta) >= 0.2
                ? 'bg-amber-500/10 border-amber-500/30'
                : 'bg-surface-700/60 border-surface-600'
            }`}
            data-testid="outside-view"
          >
            <History className="w-3 h-3 text-text-muted mt-0.5 shrink-0" aria-hidden="true" />
            <span className="text-[10px] text-text-secondary">
              {theory.outsideViewNote}
            </span>
          </div>
        )}

        {/* Recommendation */}
        {theory.recommendation && (
          <div className="flex items-start gap-1.5 px-2 py-1.5 rounded-md bg-ocean-500/10 border border-ocean-500/20">
            <Target className="w-3 h-3 text-ocean-400 mt-0.5 shrink-0" aria-hidden="true" />
            <span className="text-[11px] text-ocean-200">{theory.recommendation}</span>
          </div>
        )}

        <div className="flex items-center gap-2 pt-1">
          <button
            type="button"
            onClick={() => onSelect(selected ? null : theory)}
            aria-pressed={selected}
            className={`inline-flex items-center gap-1.5 px-2 py-1 text-[10px] rounded-md border transition-colors ${
              selected
                ? 'bg-ocean-500/20 text-ocean-300 border-ocean-500/40'
                : 'bg-surface-700 text-text-secondary border-surface-600 hover:bg-surface-600'
            }`}
          >
            <Crosshair className="w-3 h-3" aria-hidden="true" />
            {selected ? t.theories.clearHighlight : t.theories.highlightPath}
          </button>
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            aria-expanded={expanded}
            className="inline-flex items-center gap-1 px-2 py-1 text-[10px] rounded-md bg-surface-700 text-text-secondary border border-surface-600 hover:bg-surface-600 transition-colors"
          >
            {expanded ? (
              <ChevronDown className="w-3 h-3" aria-hidden="true" />
            ) : (
              <ChevronRight className="w-3 h-3" aria-hidden="true" />
            )}
            {t.theories.details}
          </button>
        </div>

        {expanded && (
          <div className="pt-2 space-y-3 border-t border-surface-700">
            {/* Causal chain */}
            {theory.causalChain.length > 0 && (
              <section>
                <h5 className="flex items-center gap-1.5 text-[10px] font-semibold text-text-muted mb-1.5">
                  <GitBranch className="w-3 h-3" aria-hidden="true" />
                  {t.theories.causalChain}
                </h5>
                <ol className="space-y-1">
                  {theory.causalChain.map((step, index) => (
                    <li
                      key={`${step.claimId ?? step.edgeId ?? index}-${index}`}
                      className="text-[11px] text-text-secondary flex gap-1.5"
                    >
                      <span className="text-text-muted shrink-0">
                        {step.edgeId ? '↳' : '•'}
                      </span>
                      <span className={step.edgeId ? 'italic text-text-muted' : ''}>
                        {step.label ?? (step.edgeId ? t.theories.causalLink : '')}
                      </span>
                    </li>
                  ))}
                </ol>
              </section>
            )}

            {/* Evidence */}
            {(evidence.supporting.length > 0 || evidence.contradicting.length > 0) && (
              <section>
                <h5 className="text-[10px] font-semibold text-text-muted mb-1.5">
                  {t.theories.evidence}
                </h5>
                <ul className="space-y-1.5">
                  {evidence.supporting.map((ev) => (
                    <li key={ev.id} className="text-[11px] flex gap-1.5">
                      <span className="text-emerald-400 shrink-0" aria-hidden="true">＋</span>
                      <span className="text-text-secondary">
                        <span className="sr-only">{t.theories.supporting}: </span>
                        {ev.snippet}
                        <span className="text-text-muted"> — {ev.sourceTitle}</span>
                      </span>
                    </li>
                  ))}
                  {evidence.contradicting.map((ev) => (
                    <li key={ev.id} className="text-[11px] flex gap-1.5">
                      <span className="text-red-400 shrink-0" aria-hidden="true">－</span>
                      <span className="text-text-secondary">
                        <span className="sr-only">{t.theories.contradicting}: </span>
                        {ev.snippet}
                        <span className="text-text-muted"> — {ev.sourceTitle}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* Weak assumptions */}
            {theory.weakAssumptions.length > 0 && (
              <section>
                <h5 className="flex items-center gap-1.5 text-[10px] font-semibold text-text-muted mb-1.5">
                  <AlertTriangle className="w-3 h-3" aria-hidden="true" />
                  {t.theories.weakAssumptions}
                </h5>
                <ul className="space-y-1">
                  {theory.weakAssumptions.map((assumption, index) => (
                    <li key={index} className="text-[11px] text-amber-300/90 flex gap-1.5">
                      <span aria-hidden="true">•</span>
                      <span>{assumption}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* Objections -- written by a call that never saw the case-for */}
            {theory.objections.length > 0 && (
              <section data-testid="objections">
                <h5 className="flex items-center gap-1.5 text-[10px] font-semibold text-text-muted mb-1.5">
                  <ShieldAlert className="w-3 h-3" aria-hidden="true" />
                  {t.adversary.title} ({theory.objections.filter((o) => !o.dismissed).length})
                </h5>
                <ul className="space-y-1.5">
                  {theory.objections.map((objection) => (
                    <li
                      key={objection.id}
                      className={`text-[11px] px-2 py-1.5 rounded-md border ${
                        objection.dismissed
                          ? 'bg-surface-700/40 border-surface-600 opacity-60'
                          : 'bg-red-500/10 border-red-500/25'
                      }`}
                    >
                      <div className="flex items-center gap-1.5 mb-0.5">
                        <span className="text-[9px] px-1 rounded bg-surface-700 text-text-muted border border-surface-600">
                          {t.adversary.kinds[objection.kind]}
                        </span>
                        <span className="text-[9px] text-text-muted">
                          {t.adversary.severity}: {t.bands[severityBand(objection.severity)]}
                        </span>
                        {objection.dismissed && (
                          <span className="text-[9px] text-text-muted">
                            · {t.adversary.dismissed}
                          </span>
                        )}
                      </div>
                      <p className={objection.dismissed ? 'text-text-muted line-through' : 'text-text-secondary'}>
                        {objection.objection}
                      </p>
                      {!objection.dismissed && onDismissObjection && (
                        <button
                          type="button"
                          onClick={() => onDismissObjection(objection.id)}
                          className="mt-1 text-[9px] text-text-muted hover:text-text-primary transition-colors"
                        >
                          {t.adversary.dismiss}
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* Tripwires -- the substitute for an experiment */}
            {theory.tripwires.length > 0 && (
              <section data-testid="tripwires">
                <h5 className="flex items-center gap-1.5 text-[10px] font-semibold text-text-muted mb-1.5">
                  <Radar className="w-3 h-3" aria-hidden="true" />
                  {t.tripwires.title}
                </h5>
                <p className="text-[10px] text-text-muted mb-1.5">{t.tripwires.hint}</p>
                {onObserveTripwire && theory.tripwires.some((tw) => tw.status === 'pending') && (
                  <div className="mb-1.5">
                    <EventField
                      projectId={theory.projectId}
                      value={tripwireEvent}
                      onChange={setTripwireEvent}
                    />
                  </div>
                )}
                <ul className="space-y-1.5">
                  {theory.tripwires.map((tripwire) => (
                    <li
                      key={tripwire.id}
                      className="text-[11px] px-2 py-1.5 rounded-md bg-surface-700/60 border border-surface-600"
                    >
                      <p className="text-text-secondary">{tripwire.observable}</p>
                      <div className="flex items-center gap-2 mt-1 flex-wrap">
                        <span className="text-[9px] text-text-muted">
                          {tripwire.direction === 'falsifies'
                            ? t.tripwires.falsifies
                            : t.tripwires.confirms}
                        </span>
                        {tripwire.checkBy && (
                          <span className="text-[9px] text-text-muted">
                            · {t.tripwires.checkBy} {tripwire.checkBy.slice(0, 10)}
                          </span>
                        )}
                        {tripwire.status === 'pending' && onObserveTripwire ? (
                          <>
                            <button
                              type="button"
                              onClick={() => onObserveTripwire(tripwire.id, true, tripwireEvent)}
                              className="text-[9px] px-1.5 py-0.5 rounded bg-surface-700 text-text-secondary border border-surface-600 hover:bg-surface-600 transition-colors"
                            >
                              {t.tripwires.happened}
                            </button>
                            <button
                              type="button"
                              onClick={() => onObserveTripwire(tripwire.id, false, tripwireEvent)}
                              className="text-[9px] px-1.5 py-0.5 rounded bg-surface-700 text-text-secondary border border-surface-600 hover:bg-surface-600 transition-colors"
                            >
                              {t.tripwires.didNotHappen}
                            </button>
                          </>
                        ) : (
                          tripwire.status !== 'pending' && (
                            <span className="text-[9px] text-emerald-400">
                              ·{' '}
                              {tripwire.status === 'observed'
                                ? t.tripwires.observed
                                : t.tripwires.notObserved}
                            </span>
                          )
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* Change explanation */}
            {theory.changeExplanation && (
              <section className="px-2 py-1.5 rounded-md bg-surface-700/60 border border-surface-600">
                <h5 className="text-[10px] font-semibold text-text-muted mb-1">
                  {t.theories.whatChanged}
                </h5>
                <p className="text-[11px] text-text-secondary">
                  {theory.changeExplanation}
                </p>
              </section>
            )}

            <p className="text-[10px] text-text-muted">
              {t.theories.version} {theory.version} · {t.theories.graphRevision}{' '}
              {theory.graphRevision} · {theory.supportingClaimIds.length}{' '}
              {t.theories.claims} · {theory.supportingEdgeIds.length}{' '}
              {t.theories.links}
            </p>
          </div>
        )}
      </div>
    </article>
  )
}

interface TheoryPanelProps {
  graph: CausalGraph | null
  theories: Theory[]
  changeSummary: ChangeSummary | null
  loading: boolean
  generating: boolean
  error: string | null
  staleCount: number
  graphRevision: number
  selectedTheoryId: string | null
  onSelectTheory: (theory: Theory | null) => void
  onGenerate: () => void
  onRegenerate: () => void
  onDismissChangeSummary: () => void
  onClose: () => void
  onChallenge?: () => void
  onGenerateTripwires?: () => void
  onRunOutsideView?: () => void
  onDismissObjection?: (objectionId: string) => void
  onObserveTripwire?: (tripwireId: string, observed: boolean, event?: string) => void
  /** Reload the theory list after a recorded result changes it (e.g. marks it stale). */
  onTheoriesChanged?: () => void
  /** Required framing answers still missing. Reported, never enforced: the
      theories generate anyway and are weaker for the gaps. */
  challenging?: boolean
}

export default function TheoryPanel({
  graph,
  theories,
  changeSummary,
  loading,
  generating,
  error,
  staleCount,
  graphRevision,
  selectedTheoryId,
  onSelectTheory,
  onGenerate,
  onRegenerate,
  onDismissChangeSummary,
  onClose,
  onChallenge,
  onGenerateTripwires,
  onRunOutsideView,
  onDismissObjection,
  onObserveTripwire,
  onTheoriesChanged,
  challenging = false,
}: TheoryPanelProps) {
  const { t } = useT()
  const [statusFilter, setStatusFilter] = useState<TheoryStatus | 'all'>('all')
  const [impactFilter, setImpactFilter] = useState<BusinessImpact | 'all'>('all')

  const visible = theories.filter(
    (theory) =>
      (statusFilter === 'all' || theory.status === statusFilter) &&
      (impactFilter === 'all' || theory.businessImpact === impactFilter),
  )

  const hasTheories = theories.length > 0

  return (
    <div className="w-full bg-surface-800 border-l border-surface-700 h-full overflow-y-auto flex flex-col">
      <div className="flex items-center justify-between p-4 border-b border-surface-700 shrink-0">
        <div className="flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-ocean-400" aria-hidden="true" />
          <h3 className="text-sm font-semibold text-text-primary">
            {t.theories.title}
          </h3>
          {hasTheories && (
            <span className="text-[10px] text-text-muted bg-surface-700 px-1.5 py-0.5 rounded-full">
              {theories.length}
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
        {/* Actions */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={hasTheories ? onRegenerate : onGenerate}
            disabled={generating}
            className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg bg-ocean-500/15 text-ocean-300 border border-ocean-500/30 hover:bg-ocean-500/25 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {generating ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
            ) : hasTheories ? (
              <RefreshCw className="w-3.5 h-3.5" aria-hidden="true" />
            ) : (
              <Sparkles className="w-3.5 h-3.5" aria-hidden="true" />
            )}
            {generating
              ? t.theories.generating
              : hasTheories
                ? t.theories.regenerate
                : t.theories.generate}
          </button>
        </div>

        {hasTheories && (onChallenge || onGenerateTripwires || onRunOutsideView) && (
          <div className="flex gap-2 flex-wrap">
            {onChallenge && (
              <button
                type="button"
                onClick={onChallenge}
                disabled={challenging}
                className="flex-1 inline-flex items-center justify-center gap-1.5 px-2 py-1.5 text-[11px] rounded-lg bg-surface-700 text-text-secondary border border-surface-600 hover:bg-surface-600 transition-colors disabled:opacity-50"
              >
                <ShieldAlert className="w-3 h-3" aria-hidden="true" />
                {challenging ? t.adversary.running : t.adversary.run}
              </button>
            )}
            {onRunOutsideView && (
              <button
                type="button"
                onClick={onRunOutsideView}
                className="flex-1 inline-flex items-center justify-center gap-1.5 px-2 py-1.5 text-[11px] rounded-lg bg-surface-700 text-text-secondary border border-surface-600 hover:bg-surface-600 transition-colors"
              >
                <History className="w-3 h-3" aria-hidden="true" />
                {t.outsideView.run}
              </button>
            )}
            {onGenerateTripwires && (
              <button
                type="button"
                onClick={onGenerateTripwires}
                className="flex-1 inline-flex items-center justify-center gap-1.5 px-2 py-1.5 text-[11px] rounded-lg bg-surface-700 text-text-secondary border border-surface-600 hover:bg-surface-600 transition-colors"
              >
                <Radar className="w-3 h-3" aria-hidden="true" />
                {t.tripwires.generate}
              </button>
            )}
          </div>
        )}

        <p className="text-[10px] text-text-muted">
          {t.theories.graphRevision} {graphRevision}
        </p>

        {staleCount > 0 && (
          <div
            className="flex items-start gap-1.5 px-2.5 py-2 rounded-lg bg-amber-500/10 border border-amber-500/30"
            role="status"
          >
            <AlertTriangle className="w-3.5 h-3.5 text-amber-400 mt-0.5 shrink-0" aria-hidden="true" />
            <span className="text-[11px] text-amber-300">
              {t.theories.staleBanner.replace('{count}', String(staleCount))}
            </span>
          </div>
        )}

        {/* Change summary */}
        {changeSummary && (
          <div
            className="px-2.5 py-2 rounded-lg bg-surface-700/60 border border-surface-600 space-y-1"
            data-testid="change-summary"
          >
            <div className="flex items-center justify-between">
              <h4 className="text-[11px] font-semibold text-text-primary">
                {t.theories.changesTitle}
              </h4>
              <button
                type="button"
                onClick={onDismissChangeSummary}
                className="text-text-muted hover:text-text-primary transition-colors"
                aria-label={t.common.close}
              >
                <X className="w-3 h-3" />
              </button>
            </div>
            <ul className="text-[10px] text-text-secondary space-y-0.5">
              <li>
                {t.theories.changeKind.new}: {changeSummary.newTheoryIds.length}
              </li>
              <li>
                {t.theories.changeKind.changed}: {changeSummary.changedTheoryIds.length}
              </li>
              <li>
                {t.theories.changeKind.unchanged}:{' '}
                {changeSummary.unchangedTheoryIds.length}
              </li>
              <li>
                {t.theories.changeKind.superseded}:{' '}
                {changeSummary.supersededTheoryIds.length}
              </li>
            </ul>
          </div>
        )}

        {/* Filters */}
        {hasTheories && (
          <div className="flex flex-wrap gap-2">
            <label className="sr-only" htmlFor="theory-status-filter">
              {t.theories.filterStatus}
            </label>
            <select
              id="theory-status-filter"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as TheoryStatus | 'all')}
              className="flex-1 px-2 py-1 text-[11px] bg-surface-700 border border-surface-600 rounded-md text-text-secondary focus:outline-none focus:border-ocean-500"
            >
              <option value="all">{t.theories.allStatuses}</option>
              {(Object.keys(STATUS_META) as TheoryStatus[]).map((status) => (
                <option key={status} value={status}>
                  {t.theories.status[status]}
                </option>
              ))}
            </select>
            <label className="sr-only" htmlFor="theory-impact-filter">
              {t.theories.filterImpact}
            </label>
            <select
              id="theory-impact-filter"
              value={impactFilter}
              onChange={(e) =>
                setImpactFilter(e.target.value as BusinessImpact | 'all')
              }
              className="flex-1 px-2 py-1 text-[11px] bg-surface-700 border border-surface-600 rounded-md text-text-secondary focus:outline-none focus:border-ocean-500"
            >
              <option value="all">{t.theories.allImpacts}</option>
              {(['critical', 'high', 'medium', 'low'] as BusinessImpact[]).map(
                (impact) => (
                  <option key={impact} value={impact}>
                    {t.theories.impact[impact]}
                  </option>
                ),
              )}
            </select>
          </div>
        )}

        {/* States */}
        {loading && (
          <div
            className="flex items-center justify-center gap-2 py-8 text-text-muted"
            data-testid="theories-loading"
          >
            <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
            <span className="text-xs">{t.common.loading}</span>
          </div>
        )}

        {!loading && error && (
          <div
            className="px-3 py-3 rounded-lg bg-red-500/10 border border-red-500/30"
            role="alert"
            data-testid="theories-error"
          >
            <p className="text-xs text-red-300">{error}</p>
          </div>
        )}

        {!loading && !error && theories.length === 0 && (
          <div className="py-8 text-center" data-testid="theories-empty">
            <Sparkles className="w-6 h-6 text-text-muted mx-auto mb-2" aria-hidden="true" />
            <p className="text-xs text-text-muted">{t.theories.empty}</p>
            <p className="text-[10px] text-text-muted/70 mt-1">{t.theories.emptyHint}</p>
          </div>
        )}

        {!loading && !error && theories.length > 0 && visible.length === 0 && (
          <p className="py-6 text-center text-xs text-text-muted">
            {t.theories.noneMatchFilter}
          </p>
        )}

        {hasTheories && (
          <OptionCoverageStrip anchor={graph?.decisionAnchor} theories={theories} />
        )}

        <div className="space-y-2.5">
          {visible.map((theory) => (
            <TheoryCard
              key={theory.id}
              theory={theory}
              graph={graph}
              selected={selectedTheoryId === theory.id}
              onSelect={onSelectTheory}
              onDismissObjection={onDismissObjection}
              onObserveTripwire={onObserveTripwire}
              onTheoriesChanged={onTheoriesChanged}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
