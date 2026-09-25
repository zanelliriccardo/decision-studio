import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowRight, HelpCircle, Loader2, Quote } from 'lucide-react'
import { toast } from 'sonner'
import { Button, Toggle } from '../ui/index.ts'
import { apiGet, apiPost } from '../../lib/api/client.ts'
import { useAnalysis } from '../../context/AnalysisContext.tsx'
import { useT } from '../../i18n/index.tsx'
import { useIntakeEnabled } from '../../hooks/useIntakeEnabled.ts'
import type { AnalyzeResponse } from '../../types/api.ts'
import type {
  IntakeAnswer,
  IntakeQuestion,
  IntakeQuestionsResponse,
} from '../../types/intake.ts'

/**
 * The questions asked before the pipeline starts.
 *
 * Three things about this screen are load-bearing:
 *
 * **It can always be left.** "Start anyway" works from the first frame,
 * including while the model is still reading — which is possible only because
 * the project id arrives from a separate call that returns immediately. Three
 * earlier question systems were removed from this repository for standing
 * between the user and their analysis; this one must never do that.
 *
 * **No question is required.** Unanswered ones are omitted from the context
 * entirely rather than rendered as "unknown", so skipping is genuinely free.
 *
 * **Zero questions is a correct outcome**, not an error. When the material was
 * clear the screen forwards to the analysis without the user seeing it — which
 * is also what happens when generation fails, and when the deployment has the
 * feature switched off.
 */
export default function IntakeScreen() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { dispatch } = useAnalysis()
  const { t } = useT()
  const { enabled: askNextTime, setEnabled: setAskNextTime } = useIntakeEnabled()

  const [questions, setQuestions] = useState<IntakeQuestion[] | null>(null)
  const [answers, setAnswers] = useState<Record<string, IntakeAnswer>>({})
  const [starting, setStarting] = useState(false)

  useEffect(() => {
    if (!projectId) return
    let cancelled = false

    void (async () => {
      try {
        // Already-generated questions first, so a reload does not re-read the
        // material and replace answers the user is halfway through giving.
        const existing = await apiGet<IntakeQuestionsResponse>(
          `/api/v1/intake/${projectId}`,
        )
        if (cancelled) return

        if (existing.questions.length > 0) {
          setQuestions(existing.questions)
          setAnswers(
            Object.fromEntries(
              existing.questions
                .filter((q) => q.answer_text || q.answer_choice !== null)
                .map((q) => [
                  q.id,
                  {
                    question_id: q.id,
                    text: q.answer_text ?? '',
                    choice: q.answer_choice,
                  },
                ]),
            ),
          )
          return
        }

        const generated = await apiPost<IntakeQuestionsResponse>(
          `/api/v1/intake/${projectId}/questions`,
          {},
        )
        if (cancelled) return
        setQuestions(generated.questions)

        // Nothing to ask: go, without the user seeing this screen. The same
        // path covers a generation failure and the deployment-wide off switch.
        if (generated.questions.length === 0) void start([])
      } catch {
        if (!cancelled) void start([])
      }
    })()

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  async function start(payload?: IntakeAnswer[]) {
    if (!projectId || starting) return
    setStarting(true)
    try {
      const body = payload ?? Object.values(answers)
      await apiPost<AnalyzeResponse>(`/api/v1/intake/${projectId}/start`, {
        answers: body,
      })
      dispatch({ type: 'START_ANALYSIS', projectId })
      navigate(`/analysis/${projectId}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t.errors.analysisFailed)
      setStarting(false)
    }
  }

  const setChoice = (id: string, choice: number) =>
    setAnswers((prev) => ({
      ...prev,
      [id]: { question_id: id, choice, text: '' },
    }))

  const setText = (id: string, text: string) =>
    setAnswers((prev) => ({
      ...prev,
      [id]: { question_id: id, text, choice: null },
    }))

  const answeredCount = Object.values(answers).filter(
    (a) => (a.text ?? '').trim() || a.choice !== null,
  ).length

  // Reading: the screen is up, with a working way out, before any question
  // exists. That is the whole reason the id comes from a separate call.
  if (questions === null) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-12">
        <div className="flex items-center gap-2 text-text-muted mb-6">
          <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
          <span className="text-sm">{t.intake.reading}</span>
        </div>
        <Button variant="ghost" onClick={() => void start([])} disabled={starting}>
          {t.intake.startAnyway}
        </Button>
      </div>
    )
  }

  if (questions.length === 0) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-12 flex items-center gap-2 text-text-muted">
        <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
        <span className="text-sm">{t.intake.reading}</span>
      </div>
    )
  }

  return (
    <div className="max-w-2xl mx-auto px-4 py-8 space-y-5" data-testid="intake-screen">
      <header>
        <h1 className="text-lg font-semibold text-text-primary">
          {t.intake.title}
        </h1>
        <p className="text-xs text-text-muted mt-1 leading-relaxed">
          {t.intake.subtitle}
        </p>
      </header>

      {questions.map((question) => {
        const answer = answers[question.id]
        return (
          <section
            key={question.id}
            className="rounded-xl border border-surface-700 bg-surface-800 p-4 space-y-2.5"
            data-testid="intake-question"
          >
            {/* The sentence this is about. Only ever shown when it was found
                verbatim in the material — a quotation the user cannot find
                makes them doubt the document instead of answering. */}
            {question.quoted_source && (
              <p className="text-[11px] text-text-muted italic flex gap-1.5 leading-relaxed">
                <Quote className="w-3 h-3 mt-0.5 shrink-0" aria-hidden="true" />
                {question.quoted_source}
              </p>
            )}

            <div className="flex items-start gap-1.5">
              <p className="text-sm text-text-primary flex-1">{question.question}</p>
              {question.rationale && (
                <span title={question.rationale} className="mt-0.5 shrink-0">
                  <HelpCircle
                    className="w-3.5 h-3.5 text-text-muted"
                    aria-label={question.rationale}
                  />
                </span>
              )}
            </div>

            {question.options.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {question.options.map((option, index) => (
                  <button
                    key={option}
                    type="button"
                    aria-pressed={answer?.choice === index}
                    onClick={() => setChoice(question.id, index)}
                    className={`px-2.5 py-1.5 text-xs rounded-lg border transition-colors ${
                      answer?.choice === index
                        ? 'bg-ocean-500/20 text-ocean-300 border-ocean-500/40'
                        : 'bg-surface-700 text-text-secondary border-surface-600 hover:bg-surface-600'
                    }`}
                  >
                    {option}
                  </button>
                ))}
              </div>
            )}

            {/* Always present, options or not: the readings on offer may all be
                wrong, and there is no way to say so with buttons alone. */}
            <input
              type="text"
              value={answer?.text ?? ''}
              onChange={(e) => setText(question.id, e.target.value)}
              placeholder={
                question.options.length > 0
                  ? t.intake.otherLabel
                  : t.intake.textPlaceholder
              }
              aria-label={t.intake.answerLabel}
              className="w-full px-2.5 py-1.5 text-xs bg-surface-700 border border-surface-600 rounded-lg text-text-primary placeholder-text-muted focus:outline-none focus:border-ocean-500 transition-colors"
            />
          </section>
        )
      })}

      <p className="text-[11px] text-text-muted">{t.intake.optionalHint}</p>

      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => void start()} disabled={starting}>
          {starting && <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />}
          {answeredCount > 0 ? t.intake.start : t.intake.startAnyway}
          <ArrowRight className="w-3.5 h-3.5 ml-1.5" aria-hidden="true" />
        </Button>
      </div>

      {/* A switch, not a third button: it changes what happens next time and
          starts nothing now. Placed here because this is the moment someone
          decides they have had enough of being asked. */}
      <div className="pt-2 border-t border-surface-700">
        <Toggle
          checked={askNextTime}
          onChange={setAskNextTime}
          label={t.intake.askNextTime}
          hint={t.intake.askNextTimeHint}
        />
      </div>
    </div>
  )
}
