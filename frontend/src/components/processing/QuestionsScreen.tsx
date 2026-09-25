import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { useT } from '../../i18n/index.tsx'
import * as reasoningApi from '../../lib/api/reasoning.ts'
import QuestionsStep from './QuestionsStep.tsx'
import type { DecisionFrame } from '../../types/reasoning.ts'

/**
 * The questions, on their own page.
 *
 * They are normally asked during the analysis, on the processing screen. This
 * route exists for the one case that would otherwise be a dead end: the user
 * skipped them, reached the graph, and found theory generation blocked. Without
 * somewhere to go, the gate would be unrecoverable.
 *
 * Only framing questions appear here. Intake questions hold the pipeline, so by
 * the time a graph exists they have all been answered or skipped.
 */
export default function QuestionsScreen() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { t } = useT()
  const [frame, setFrame] = useState<DecisionFrame | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!projectId) return
    let cancelled = false
    void (async () => {
      try {
        const loaded = await reasoningApi.fetchFrame(projectId)
        if (!cancelled) setFrame(loaded)
      } catch (err) {
        if (!cancelled) toast.error(err instanceof Error ? err.message : t.errors.loadFailed)
      }
    })()
    return () => { cancelled = true }
  }, [projectId, t])

  async function save(answers: Record<string, unknown>) {
    if (!projectId) return
    setSaving(true)
    try {
      const updated = await reasoningApi.saveFrameAnswers(projectId, answers)
      setFrame(updated)
      toast.success(t.framing.saved)
      // Once the gate is open there is nothing left to do here.
      if (updated.canGenerateTheories) navigate(`/graph/${projectId}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t.framing.saveFailed)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <button
        onClick={() => navigate(`/graph/${projectId}`)}
        className="inline-flex items-center gap-1.5 text-xs text-text-muted hover:text-text-primary mb-4 transition-colors"
      >
        <ArrowLeft className="w-3.5 h-3.5" />
        {t.framing.backToGraph}
      </button>

      {frame === null ? (
        <div className="flex items-center justify-center gap-2 py-16 text-text-muted">
          <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
          <span className="text-xs">{t.common.loading}</span>
        </div>
      ) : (
        <QuestionsStep
          intakeQuestions={[]}
          frame={frame}
          submitting={saving}
          onAnswerIntake={async () => false}
          onSkipIntake={async () => false}
          onSaveFrame={save}
        />
      )}
    </div>
  )
}
