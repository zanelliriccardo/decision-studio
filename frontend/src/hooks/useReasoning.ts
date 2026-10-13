import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { useT } from '../i18n/index.tsx'
import * as api from '../lib/api/reasoning.ts'
import type {
  Debate,
  ChangeSummary,
  ReviewPayload,
  Theory,
} from '../types/reasoning.ts'

/**
 * Owns all decision-reasoning state for a project: theories, clarification
 * questions and graph review.
 *
 * Two deliberate behaviours:
 *  - Theories are never regenerated automatically. Edits and answers only mark
 *    the existing ones stale; the user chooses when to spend a generation.
 *  - Review calls carry `expected_graph_revision`, so an edit made against a
 *    stale view is rejected by the backend rather than silently applied.
 */
export function useReasoning(projectId: string | null) {
  const { t } = useT()

  const [theories, setTheories] = useState<Theory[]>([])
  const [debates, setDebates] = useState<Debate[]>([])
  const [graphRevision, setGraphRevision] = useState(1)
  const [changeSummary, setChangeSummary] = useState<ChangeSummary | null>(null)

  const [theoriesLoading, setTheoriesLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [reviewBusyId, setReviewBusyId] = useState<string | null>(null)
  const [debatesLoading, setDebatesLoading] = useState(false)
  const [running, setRunning] = useState(false)
  const [promoting, setPromoting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [debatesError, setDebatesError] = useState<string | null>(null)

  const [theoriesError, setTheoriesError] = useState<string | null>(null)

  const staleCount = theories.filter((theory) => theory.isStale).length

  const describeError = useCallback(
    (err: unknown, fallback: string): string => {
      if (err && typeof err === 'object' && 'body' in err) {
        try {
          const parsed = JSON.parse(String((err as { body: string }).body))
          if (typeof parsed.detail === 'string') return parsed.detail
        } catch {
          // Non-JSON error body — fall through to the generic message.
        }
      }
      return err instanceof Error ? err.message : fallback
    },
    [],
  )

  // --- Loading ---

  const loadTheories = useCallback(async () => {
    if (!projectId) return
    setTheoriesLoading(true)
    setTheoriesError(null)
    try {
      const result = await api.fetchTheories(projectId)
      setTheories(result.theories)
      setGraphRevision(result.graphRevision)
    } catch (err) {
      setTheoriesError(describeError(err, t.errors.loadFailed))
    } finally {
      setTheoriesLoading(false)
    }
  }, [projectId, describeError, t])




  const loadDebates = useCallback(async () => {
    if (!projectId) return
    setDebatesLoading(true)
    setDebatesError(null)
    try {
      setDebates(await api.fetchDebates(projectId))
    } catch (err) {
      setDebatesError(describeError(err, t.errors.loadFailed))
    } finally {
      setDebatesLoading(false)
    }
  }, [projectId, describeError, t])

  useEffect(() => {
    void loadTheories()
    void loadDebates()
  }, [loadTheories, loadDebates])

  // --- Theories ---

  const runGeneration = useCallback(
    async (mode: 'generate' | 'regenerate') => {
      if (!projectId) return null
      setGenerating(true)
      setTheoriesError(null)
      try {
        const result =
          mode === 'generate'
            ? await api.generateTheories(projectId)
            : await api.regenerateTheories(projectId)
        setTheories(result.theories)
        setGraphRevision(result.graphRevision)
        setChangeSummary(result.changeSummary)
        toast.success(
          mode === 'generate' ? t.theories.generated : t.theories.regenerated,
        )
        // Open question links move to the new theory versions.
        return result
      } catch (err) {
        const message = describeError(err, t.theories.generateFailed)
        setTheoriesError(message)
        toast.error(message)
        return null
      } finally {
        setGenerating(false)
      }
    },
    [projectId, describeError, t],
  )

  const generateTheories = useCallback(() => runGeneration('generate'), [runGeneration])
  const regenerateTheories = useCallback(
    () => runGeneration('regenerate'),
    [runGeneration],
  )

  // --- Clarifications ---



  // --- Manual authoring ---

  const addEdge = useCallback(
    async (
      sourceClaimId: string,
      targetClaimId: string,
      mechanism: string,
      effect: number,
      linkConfidence: number,
    ) => {
      if (!projectId) return false
      setSaving(true)
      try {
        await api.addEdge(
          projectId, sourceClaimId, targetClaimId, mechanism, effect, linkConfidence,
        )
        // Beliefs are not recomputed here: the caller reloads the graph, and
        // every graph read propagates the whole graph afresh.
        await Promise.all([loadTheories(), loadDebates()])
        toast.success(t.authoring.linkCreated)
        return true
      } catch (err) {
        toast.error(describeError(err, t.authoring.linkFailed))
        return false
      } finally {
        setSaving(false)
      }
    },
    [projectId, describeError, loadTheories, loadDebates, t],
  )

  const addClaim = useCallback(
    async (text: string, claimType: string) => {
      if (!projectId) return false
      setSaving(true)
      try {
        const { plan } = await api.addClaim(projectId, text, claimType)

        // Inference is a separate concern from the claim existing, and it can
        // fail on its own — a model outage, an exhausted quota. Reporting
        // "could not add the claim" then would be false: the claim is in the
        // graph, and saying otherwise invites the user to add it twice.
        let linksInferred = true
        if (plan.newClaimIds.length > 0) {
          try {
            // Only pairs involving the new claim: re-running the whole
            // inference would regenerate links already rejected by hand.
            await api.inferLinks(projectId, plan.newClaimIds)
          } catch (err) {
            linksInferred = false
            toast.warning(describeError(err, t.authoring.linksNotInferred))
          }
        }

        // No recompute call: the caller reloads the graph, which propagates it.
        await Promise.all([loadTheories(), loadDebates()])
        if (linksInferred) toast.success(t.authoring.claimCreated)
        return true
      } catch (err) {
        toast.error(describeError(err, t.authoring.claimFailed))
        return false
      } finally {
        setSaving(false)
      }
    },
    [projectId, describeError, loadTheories, loadDebates, t],
  )

  // --- Debates ---

  const runDebates = useCallback(async () => {
    if (!projectId) return
    setRunning(true)
    setDebatesError(null)
    try {
      const report = await api.runDebates(projectId)
      await loadDebates()
      if (report.competing === 0 && report.orthogonal === 0) {
        // Every pair was a restatement: worth saying, since the panel will
        // otherwise look like nothing happened.
        toast.info(t.debate.allRestatements)
      } else {
        toast.success(
          t.debate.ran
            .replace('{competing}', String(report.competing))
            .replace('{calls}', String(report.modelCalls)),
        )
      }
    } catch (err) {
      const message = describeError(err, t.debate.runFailed)
      setDebatesError(message)
      toast.error(message)
    } finally {
      setRunning(false)
    }
  }, [projectId, describeError, loadDebates, t])

  const promoteDiscriminator = useCallback(
    async (debateId: string) => {
      if (!projectId) return
      setPromoting(true)
      try {
        await api.promoteDiscriminator(projectId, debateId)
        // The tripwire lands on both theories, so both views need rereading.
        await Promise.all([loadDebates(), loadTheories()])
        toast.success(t.debate.promoted)
      } catch (err) {
        toast.error(describeError(err, t.debate.promoteFailed))
      } finally {
        setPromoting(false)
      }
    },
    [projectId, describeError, loadDebates, loadTheories, t],
  )

  // --- Review ---

  const review = useCallback(
    async (
      targetType: 'claim' | 'edge',
      targetId: string,
      payload: ReviewPayload,
    ) => {
      if (!projectId) return null
      setReviewBusyId(targetId)
      try {
        const call = targetType === 'claim' ? api.reviewClaim : api.reviewEdge
        const result = await call(projectId, targetId, {
          ...payload,
          expected_graph_revision: payload.expected_graph_revision ?? graphRevision,
        })
        setGraphRevision(result.graphRevision)
        // A graph edit invalidates comparisons too: their overlap numbers were
        // computed against the previous revision.
        void loadDebates()
        if (result.staleTheoryCount > 0) {
          setTheories((prev) =>
            prev.map((theory) => ({
              ...theory,
              isStale: true,
              staleReason: theory.staleReason ?? t.theories.staleEdit,
            })),
          )
        }
        toast.success(t.review.saved)
        return result
      } catch (err) {
        const message = describeError(err, t.review.saveFailed)
        toast.error(message)
        // A 409 means someone else moved the graph; resync so the next edit works.
        if (err && typeof err === 'object' && (err as { status?: number }).status === 409) {
          void loadTheories()
        }
        return null
      } finally {
        setReviewBusyId(null)
      }
    },
    [projectId, graphRevision, describeError, loadTheories, t],
  )

  return {
    theories,
    debates,
    debatesLoading,
    debatesError,
    running,
    promoting,
    loadDebates,
    runDebates,
    promoteDiscriminator,
    addEdge,
    addClaim,
    saving,
    graphRevision,
    changeSummary,
    staleCount,
    theoriesLoading,
    generating,
    reviewBusyId,
    theoriesError,
    loadTheories,
    generateTheories,
    regenerateTheories,
    review,
    clearChangeSummary: () => setChangeSummary(null),
  }
}

export type ReasoningApi = ReturnType<typeof useReasoning>
