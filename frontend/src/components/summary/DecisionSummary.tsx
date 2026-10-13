import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  ArrowDown, ArrowRight, Download, GitBranch, Loader2,
  Lightbulb, MinusCircle, PlusCircle, Radar, ShieldAlert, Target,
} from 'lucide-react'
import { toast } from 'sonner'
import { useT } from '../../i18n/index.tsx'
import * as reasoningApi from '../../lib/api/reasoning.ts'
import { apiGet } from '../../lib/api/client.ts'
import type { Theory } from '../../types/reasoning.ts'
import ObjectiveEditor from './ObjectiveEditor.tsx'
import DecisionAnchorCard from '../anchor/DecisionAnchorCard.tsx'
import TheoryValueSection from '../theory/TheoryValueSection.tsx'
import OptionCoverageStrip from '../theory/OptionCoverageStrip.tsx'
import { draftDecisionAnchor, toAnchor } from '../../lib/decisionAnchor.ts'
import type { DecisionAnchor } from '../../types/graph.ts'
import UsagePanel from './UsagePanel.tsx'
import ComparableCases from './ComparableCases.tsx'
import OptionForecastCard from './OptionForecastCard.tsx'
import DecisionPrioritiesCard from './DecisionPrioritiesCard.tsx'
import RobustnessCard from './RobustnessCard.tsx'
import MindChangersCard from './MindChangersCard.tsx'
import InformationPriorityCard from './InformationPriorityCard.tsx'
import AssumptionsCard from './AssumptionsCard.tsx'
import ScenariosCard from './ScenariosCard.tsx'
import SubDecisionsCard from './SubDecisionsCard.tsx'
import TimelineCard from './TimelineCard.tsx'

/**
 * Where an analysis lands: the conclusions, written out.
 *
 * The graph used to be the destination and it was the wrong one. A graph is the
 * material a conclusion is made from; someone who has just waited several
 * minutes wants to read what the analysis concluded and decide whether to trust
 * it. Checking the reasoning comes after that, which is why the graph is a link
 * at the bottom rather than the page itself.
 *
 * Each theory is written out in full rather than compressed into a card: the
 * causal chain step by step, what argues against it, how it compares with cases
 * the reader has seen before, and what observation would prove it wrong. Hiding
 * those behind an expander produces a page that looks like an answer without
 * being one — and the qualifications are the part most worth reading.
 */
export default function DecisionSummary() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { t } = useT()
  const [theories, setTheories] = useState<Theory[] | null>(null)
  const [claims, setClaims] = useState<{ id: string; text: string }[]>([])
  const [objective, setObjective] = useState<string | null>(null)
  const [advice, setAdvice] = useState<reasoningApi.Recommendation | null>(null)
  const [generating, setGenerating] = useState(false)
  const [savingObjective, setSavingObjective] = useState(false)
  const [usage, setUsage] = useState<reasoningApi.AnalysisUsage | null>(null)
  const [anchor, setAnchor] = useState<DecisionAnchor | null>(null)
  const [draftingAnchor, setDraftingAnchor] = useState(false)
  const [comparison, setComparison] = useState<reasoningApi.OptionComparison | null>(null)

  // The options compared on the causal map: one computation feeds the trade-off
  // table, robustness, drivers and information priority. Recomputed when the
  // anchor is saved; priorities return their own recomputed comparison.
  const optionCount = anchor?.options.length ?? 0
  useEffect(() => {
    if (!projectId || optionCount < 2) {
      setComparison(null)
      return
    }
    let cancelled = false
    reasoningApi
      .fetchOptionComparison(projectId)
      .then((loaded) => {
        if (!cancelled) setComparison(loaded)
      })
      .catch(() => {
        if (!cancelled) setComparison(null)
      })
    return () => {
      cancelled = true
    }
  }, [projectId, anchor, optionCount])

  useEffect(() => {
    if (!projectId) return
    let cancelled = false
    void (async () => {
      try {
        const [loadedTheories, loadedGraph, loadedAdvice, loadedUsage] = await Promise.all([
          reasoningApi.fetchTheories(projectId),
          // The API returns `claims`, not `nodes` — the graph screen
          // transforms it. Typing the raw response as CausalGraph made
          // `graph.nodes` undefined and every read of it a crash.
          apiGet<{
            claims: { id: string; text: string }[]
            decision_objective?: string | null
            decision_anchor?: unknown
          }>(`/api/v1/graph/${projectId}`),
          reasoningApi.fetchRecommendation(projectId),
          reasoningApi.fetchUsage(projectId),
        ])
        if (cancelled) return
        setTheories(loadedTheories.theories)
        setClaims(loadedGraph.claims ?? [])
        setObjective(loadedGraph.decision_objective ?? null)
        setAnchor(toAnchor(loadedGraph.decision_anchor))
        setAdvice(loadedAdvice)
        setUsage(loadedUsage)
      } catch (err) {
        if (!cancelled) {
          toast.error(err instanceof Error ? err.message : t.errors.loadFailed)
          setTheories([])
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [projectId, t])

  // The server's order (theories.rank_key): reaching a success criterion
  // first, then the decider's conviction, else the objection-discounted score.
  // Re-sorting here used to disagree with the graph panel and the report.
  const ranked = theories ?? []

  const claimText = (id: string) => claims.find((c) => c.id === id)?.text ?? ''

  if (theories === null) {
    return (
      <div className="flex items-center justify-center gap-2 py-20 text-text-muted">
        <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
        <span className="text-xs">{t.common.loading}</span>
      </div>
    )
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
      {/* The two ways out of an analysis, before anything else: the causal
          graph to check the reasoning, and the report for everyone else. */}
      <div className="flex flex-wrap justify-end gap-2" data-testid="summary-actions">
        <button
          type="button"
          onClick={() => navigate(`/graph/${projectId}`)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-surface-700 text-text-secondary border border-surface-600 hover:bg-surface-600 transition-colors"
        >
          <GitBranch className="w-3.5 h-3.5" aria-hidden="true" />
          {t.graphList.openGraph}
        </button>
        <a
          href={`/api/v1/graph/${projectId}/brief?format=pdf`}
          download
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg text-white bg-ocean-500 hover:bg-ocean-400 border border-ocean-500 transition-colors"
        >
          <Download className="w-3.5 h-3.5" aria-hidden="true" />
          {t.graphList.downloadReport}
        </a>
      </div>

      <header>
        <ObjectiveEditor
          objective={objective}
          saving={savingObjective}
          onSave={(next) => {
            void (async () => {
              if (!projectId) return
              setSavingObjective(true)
              try {
                await reasoningApi.setDecisionObjective(projectId, next)
                setObjective(next)
                // The server keeps the anchor's decision in step; mirror it.
                setAnchor((prev) => (prev ? { ...prev, decision: next } : prev))
                // The advice was written against the old question, so it now
                // answers something nobody asked. Clearing it makes that
                // visible rather than leaving stale advice on the page.
                setAdvice(null)
                toast.success(t.summary.objectiveSaved)
              } catch (err) {
                toast.error(
                  err instanceof Error ? err.message : t.summary.objectiveFailed,
                )
              } finally {
                setSavingObjective(false)
              }
            })()
          }}
        />
        <div className="mt-3">
          {anchor || draftingAnchor ? (
            <DecisionAnchorCard
              anchor={anchor}
              loading={draftingAnchor}
              projectId={projectId}
              onSaved={(saved) => {
                setAnchor(saved)
                setObjective(saved.decision)
                // Written against the old decision: clear it, as for the objective.
                setAdvice(null)
              }}
            />
          ) : (
            objective && (
              // An analysis from before anchors existed. Drafting one here and
              // saving it links outcome nodes into the existing graph and scores
              // every claim — no re-run.
              <button
                type="button"
                onClick={() => {
                  if (!projectId) return
                  setDraftingAnchor(true)
                  void draftDecisionAnchor(projectId)
                    .then((drafted) => {
                      setAnchor(drafted)
                      if (!drafted) toast.error(t.anchor.saveFailed)
                    })
                    .catch(() => toast.error(t.anchor.saveFailed))
                    .finally(() => setDraftingAnchor(false))
                }}
                className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded-lg bg-amber-500/10 text-amber-300 border border-amber-500/25 hover:bg-amber-500/20 transition-colors"
                data-testid="anchor-retrofit"
              >
                <Target className="w-3 h-3" aria-hidden="true" />
                {t.anchor.retrofit}
              </button>
            )
          )}
        </div>
      </header>

      {/* The options compared by the causal map itself, beside the anchor
          that defines them. Recomputed when the anchor is saved. */}
      {projectId && comparison && (
        <>
          <DecisionPrioritiesCard
            projectId={projectId}
            priorities={comparison.priorities}
            onChanged={setComparison}
          />
          <OptionForecastCard comparison={comparison} />
          {/* The same comparison under explicit assumptions, and inside each
              option. Refreshed with the comparison (priorities change both). */}
          <ScenariosCard projectId={projectId} refreshKey={comparison} />
          {anchor && (
            <SubDecisionsCard
              projectId={projectId}
              options={anchor.options}
              claims={claims}
              refreshKey={comparison.priorities}
            />
          )}
        </>
      )}

      {/* The answer, before the explanations it rests on. Someone who has
          waited for an analysis wants to know what it concluded; the reasoning
          is what they read next to decide whether to believe it. */}
      {ranked.length > 0 && (
        <section
          className="rounded-xl border border-ocean-500/30 bg-ocean-500/5 p-5 space-y-3"
          data-testid="recommendation"
        >
          <div className="flex items-start gap-2">
            <Lightbulb className="w-4 h-4 text-ocean-400 mt-0.5 shrink-0" aria-hidden="true" />
            <div className="flex-1">
              <h2 className="text-sm font-semibold text-text-primary">
                {t.summary.whatToDo}
              </h2>
              {advice && (
                <span className="text-[10px] text-text-muted">
                  {t.summary.adviceConfidence}: {t.bands[advice.confidence === 'low'
                    ? 'low'
                    : advice.confidence === 'high'
                      ? 'high'
                      : 'moderate']}
                  {advice.isStale && ` · ${t.summary.adviceStale}`}
                </span>
              )}
            </div>
          </div>

          {advice ? (
            <>
              <p className="text-sm text-text-primary leading-relaxed">
                {advice.recommendation}
              </p>

              {advice.reasoning && (
                <p className="text-xs text-text-secondary leading-relaxed">
                  {advice.reasoning}
                </p>
              )}

              {advice.dependsOn.length > 0 && (
                <div>
                  <h3 className="text-[10px] font-semibold uppercase tracking-wide text-text-muted mb-1">
                    {t.summary.dependsOn}
                  </h3>
                  <ul className="space-y-0.5">
                    {advice.dependsOn.map((item, i) => (
                      <li key={i} className="text-xs text-text-secondary">{item}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Beside the advice, not below it: the case for doing something
                  else is the part most worth reading before acting. */}
              {advice.againstIt && (
                <div className="px-3 py-2 rounded-lg bg-surface-800 border border-surface-600">
                  <h3 className="text-[10px] font-semibold uppercase tracking-wide text-text-muted mb-1">
                    {t.summary.theCaseAgainst}
                  </h3>
                  <p className="text-xs text-text-secondary leading-relaxed">
                    {advice.againstIt}
                  </p>
                </div>
              )}

              {advice.nextStep && (
                <p className="text-xs text-text-primary">
                  <span className="text-text-muted">{t.summary.thisWeek}: </span>
                  {advice.nextStep}
                </p>
              )}
            </>
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-text-muted">{t.summary.noAdviceYet}</p>
              <button
                type="button"
                disabled={generating}
                onClick={() => {
                  void (async () => {
                    if (!projectId) return
                    setGenerating(true)
                    try {
                      setAdvice(await reasoningApi.generateRecommendation(projectId))
                    } catch (err) {
                      toast.error(
                        err instanceof Error ? err.message : t.summary.adviceFailed,
                      )
                    } finally {
                      setGenerating(false)
                    }
                  })()
                }}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-ocean-500/15 text-ocean-300 border border-ocean-500/30 hover:bg-ocean-500/25 transition-colors disabled:opacity-50"
              >
                {generating && <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />}
                {t.summary.generateAdvice}
              </button>
            </div>
          )}
        </section>
      )}

      {/* After the answer, before the full theories: how solid the comparison
          is, what could change it, and where more information would help. */}
      {projectId && comparison && <RobustnessCard comparison={comparison} />}
      {projectId && comparison && <AssumptionsCard projectId={projectId} refreshKey={comparison} />}
      {projectId && ranked.length > 0 && (
        <MindChangersCard projectId={projectId} refreshKey={theories} />
      )}
      {/* Information priority ranks inputs by their effect on the weighted
          gap: without a weighted view there is nothing to rank against. */}
      {projectId && comparison && !comparison.unavailable && comparison.options.some((o) => o.weighted) && (
        <InformationPriorityCard items={comparison.informationPriority} />
      )}

      {ranked.length === 0 ? (
        <div className="py-12 text-center" data-testid="summary-empty">
          <p className="text-sm text-text-secondary">{t.summary.noTheories}</p>
          <p className="text-xs text-text-muted mt-1">{t.summary.noTheoriesHint}</p>
        </div>
      ) : (
        <>
          <p className="text-xs text-text-muted leading-relaxed">
            {t.summary.intro.replace('{n}', String(ranked.length))}
          </p>

          <OptionCoverageStrip anchor={anchor} theories={ranked} />

          {ranked.map((theory, index) => {
            const objections = theory.objections.filter((o) => !o.dismissed)
            const tripwires = theory.tripwires.filter((tw) => tw.status === 'pending')

            return (
              <article
                key={theory.id}
                className="rounded-xl border border-surface-700 bg-surface-800 p-5 space-y-4"
                data-testid="summary-theory"
              >
                <div>
                  <div className="flex items-baseline gap-2">
                    <span className="text-sm font-mono text-text-muted">
                      {index + 1}.
                    </span>
                    <h2 className="text-base font-semibold text-text-primary leading-snug">
                      {theory.title}
                    </h2>
                  </div>
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mt-1.5 pl-6">
                    <span className="text-[10px] text-text-muted">
                      {t.theories.confidence}: {t.bands[theory.confidenceBand]}
                    </span>
                    <span className="text-[10px] text-text-muted">
                      · {t.theories.impact[theory.businessImpact]}
                    </span>
                    {/* Chain integrity, beside the confidence rather than
                        inside it. Weighting it in the score would be another
                        uncalibrated constant; a reader told "1 of 3 links
                        verified" can weigh it themselves — and the ranking this
                        page shows is what the brief recommends from. */}
                    {theory.citedLinks > 0 && (
                      <span
                        className={`text-[10px] ${
                          theory.connectedLinks === theory.citedLinks
                            ? 'text-text-muted'
                            : 'text-amber-400'
                        }`}
                      >
                        · {t.summary.linksVerified
                            .replace('{n}', String(theory.connectedLinks))
                            .replace('{total}', String(theory.citedLinks))}
                      </span>
                    )}
                    {theory.contested && (
                      <span className="inline-flex items-center gap-1 text-[10px] text-amber-400">
                        <ShieldAlert className="w-3 h-3" aria-hidden="true" />
                        {t.adversary.contested}
                      </span>
                    )}
                    {theory.isStale && (
                      <span className="text-[10px] text-amber-400">
                        · {t.summary.stale}
                      </span>
                    )}
                  </div>
                </div>

                <p className="text-sm text-text-secondary leading-relaxed">
                  {theory.summary}
                </p>

                <TheoryValueSection
                  theory={theory}
                  anchor={anchor}
                  onChanged={() => {
                    if (!projectId) return
                    void reasoningApi.fetchTheories(projectId)
                      .then((loaded) => setTheories(loaded.theories))
                      .catch(() => undefined)
                  }}
                />

                {/* The chain, step by step. This is the argument itself; a
                    summary of it is only a claim about the argument. */}
                {theory.causalChain.length > 0 && (
                  <section>
                    <h3 className="text-[10px] font-semibold uppercase tracking-wide text-text-muted mb-1.5">
                      {t.summary.howItWorks}
                    </h3>
                    <ol className="space-y-0.5">
                      {theory.causalChain.map((step, i) => (
                        <li key={i} className="text-xs">
                          {step.gapBefore && (
                            <span className="text-[10px] text-amber-400 block pl-3 py-0.5">
                              {t.summary.chainGap}
                            </span>
                          )}
                          {step.claimId ? (
                            <span className="text-text-primary">
                              {claimText(step.claimId) || step.label}
                            </span>
                          ) : (
                            <span className="text-text-muted flex items-start gap-1 pl-3">
                              <ArrowDown
                                className="w-3 h-3 mt-0.5 shrink-0"
                                aria-hidden="true"
                              />
                              <em>{step.label}</em>
                            </span>
                          )}
                        </li>
                      ))}
                    </ol>
                  </section>
                )}

                {theory.recommendation && (
                  <section className="px-3 py-2 rounded-lg bg-ocean-500/10 border border-ocean-500/25">
                    <h3 className="text-[10px] font-semibold uppercase tracking-wide text-ocean-300 mb-1">
                      {t.summary.recommendation}
                    </h3>
                    <p className="text-xs text-text-primary leading-relaxed">
                      {theory.recommendation}
                    </p>
                  </section>
                )}

                {/* Objections beside the conclusion rather than in an appendix.
                    An argument nobody has attacked has not been tested, and
                    burying the attacks is how a qualification gets lost. */}
                {objections.length > 0 && (
                  <section>
                    <h3 className="text-[10px] font-semibold uppercase tracking-wide text-text-muted mb-1.5 flex items-center gap-1">
                      <MinusCircle className="w-3 h-3" aria-hidden="true" />
                      {t.summary.againstIt}
                    </h3>
                    <ul className="space-y-1">
                      {objections.map((objection) => (
                        <li key={objection.id} className="text-xs text-text-secondary">
                          <span className="text-[10px] text-text-muted">
                            [{t.adversary.kinds[objection.kind]}]
                          </span>{' '}
                          {objection.objection}
                        </li>
                      ))}
                    </ul>
                  </section>
                )}

                {theory.weakAssumptions.length > 0 && (
                  <section>
                    <h3 className="text-[10px] font-semibold uppercase tracking-wide text-text-muted mb-1.5">
                      {t.theories.weakAssumptions}
                    </h3>
                    <ul className="space-y-0.5">
                      {theory.weakAssumptions.map((assumption, i) => (
                        <li key={i} className="text-xs text-text-secondary">
                          {assumption}
                        </li>
                      ))}
                    </ul>
                  </section>
                )}

                {theory.outsideViewNote && (
                  <section>
                    <h3 className="text-[10px] font-semibold uppercase tracking-wide text-text-muted mb-1 flex items-center gap-1">
                      <PlusCircle className="w-3 h-3" aria-hidden="true" />
                      {t.summary.comparedWithBefore}
                    </h3>
                    <p className="text-xs text-text-secondary leading-relaxed">
                      {theory.outsideViewNote}
                    </p>
                  </section>
                )}

                {/* The one thing that turns a claim about an unknowable future
                    into a bet that can be lost. */}
                {tripwires.length > 0 && (
                  <section className="px-3 py-2 rounded-lg bg-surface-700/50 border border-surface-600">
                    <h3 className="text-[10px] font-semibold uppercase tracking-wide text-text-muted mb-1 flex items-center gap-1">
                      <Radar className="w-3 h-3" aria-hidden="true" />
                      {t.summary.whatWouldDisproveIt}
                    </h3>
                    <ul className="space-y-1">
                      {tripwires.map((tripwire) => (
                        <li key={tripwire.id} className="text-xs text-text-secondary">
                          {tripwire.observable}
                          {tripwire.checkBy && (
                            <span className="text-text-muted">
                              {' — '}
                              {t.tripwires.checkBy} {tripwire.checkBy.slice(0, 10)}
                            </span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
              </article>
            )
          })}

          {/* Said plainly rather than in small print: a reader who takes these
              numbers as measurements has misread the page. */}
          <section className="pt-2 border-t border-surface-700">
            <h3 className="text-[10px] font-semibold uppercase tracking-wide text-text-muted mb-1.5">
              {t.summary.howToRead}
            </h3>
            <p className="text-[11px] text-text-muted leading-relaxed">
              {t.summary.howToReadBody}
            </p>
          </section>
        </>
      )}

      {/* After the theories, because it is checked against them: each theory's
          "compared with cases you have seen" note comes from here. */}
      {projectId && ranked.length > 0 && (
        <ComparableCases
          projectId={projectId}
          onChecked={() => {
            void reasoningApi
              .fetchTheories(projectId)
              .then((loaded) => setTheories(loaded.theories))
              .catch(() => undefined)
          }}
        />
      )}

      {/* How the decision got here: what was believed and what changed it. */}
      {projectId && <TimelineCard projectId={projectId} refreshKey={comparison ?? theories} />}

      {/* Below the conclusions: operational information, not a finding. */}
      <UsagePanel usage={usage} />

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => navigate(`/graph/${projectId}`)}
          className="flex-1 min-w-[180px] inline-flex items-center justify-center gap-1.5 px-3 py-2.5 text-xs font-medium rounded-lg bg-surface-700 text-text-secondary border border-surface-600 hover:bg-surface-600 transition-colors"
        >
          <GitBranch className="w-3.5 h-3.5" aria-hidden="true" />
          {t.summary.inspectTheGraph}
          <ArrowRight className="w-3.5 h-3.5" aria-hidden="true" />
        </button>
        <a
          href={`/api/v1/graph/${projectId}/brief?format=pdf`}
          download
          className="flex-1 min-w-[180px] inline-flex items-center justify-center gap-1.5 px-3 py-2.5 text-xs font-medium rounded-lg bg-surface-700 text-text-secondary border border-surface-600 hover:bg-surface-600 transition-colors"
        >
          <Download className="w-3.5 h-3.5" aria-hidden="true" />
          {t.summary.exportBrief}
        </a>
      </div>
    </div>
  )
}
