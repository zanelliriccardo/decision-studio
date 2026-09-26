// DEAD-CODE-CANDIDATE DC-33 [file]: first intake UI; unreachable from main.tsx. See docs/DEAD_CODE_REPORT.md
import { useState } from 'react'
import { HelpCircle, Loader2, SkipForward } from 'lucide-react'
import { useT } from '../../i18n/index.tsx'

/**
 * The intake questions, shown where the pipeline actually stops.
 *
 * These are asked between claim extraction and causal inference, because a
 * misread claim is cheap to correct now and expensive later: once inference has
 * run, fixing it means re-inferring its links, re-grounding its evidence and
 * re-propagating every belief downstream.
 *
 * So they belong on the processing screen, in front of the progress bar the
 * user is already watching. Putting them behind a panel elsewhere would mean
 * the run appears stalled while the thing that would unstick it sits somewhere
 * the user has no reason to look.
 *
 * Skipping is always available. A question the user cannot answer must not be
 * able to strand a run — and "I don't know" is itself worth recording, since it
 * marks a claim nobody can pin down.
 */

export interface IntakeQuestion {
  id: string
  question: string
  reason: string
  answer_type: 'free_text' | 'single_choice' | 'yes_no'
  options: string[]
}

export default function IntakeQuestions({
  questions,
  submitting,
  onAnswer,
  onSkip,
  onContinue,
}: {
  questions: IntakeQuestion[]
  submitting: boolean
  onAnswer: (id: string, value: string) => Promise<boolean>
  onSkip: (id: string) => Promise<boolean>
  onContinue: () => void
}) {
  const { t } = useT()
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [done, setDone] = useState<Set<string>>(new Set())

  const remaining = questions.filter((q) => !done.has(q.id))
  const allHandled = remaining.length === 0

  async function submit(question: IntakeQuestion) {
    const value = (answers[question.id] ?? '').trim()
    if (!value) return
    if (await onAnswer(question.id, value)) {
      setDone((prev) => new Set(prev).add(question.id))
    }
  }

  async function skip(question: IntakeQuestion) {
    if (await onSkip(question.id)) {
      setDone((prev) => new Set(prev).add(question.id))
    }
  }

  return (
    <div
      className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 space-y-3"
      data-testid="intake-questions"
    >
      <div className="flex items-start gap-2">
        <HelpCircle className="w-4 h-4 text-amber-400 mt-0.5 shrink-0" aria-hidden="true" />
        <div>
          <h3 className="text-sm font-semibold text-text-primary">
            {t.intake.title}
          </h3>
          <p className="text-[11px] text-text-muted mt-0.5 leading-relaxed">
            {t.intake.why}
          </p>
        </div>
      </div>

      {allHandled ? (
        <div className="space-y-2" data-testid="intake-complete">
          <p className="text-xs text-emerald-400">{t.intake.allAnswered}</p>
          <button
            type="button"
            onClick={onContinue}
            disabled={submitting}
            className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg bg-ocean-500/15 text-ocean-300 border border-ocean-500/30 hover:bg-ocean-500/25 transition-colors disabled:opacity-50"
          >
            {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />}
            {t.intake.continueAnalysis}
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {remaining.map((question) => (
            <div
              key={question.id}
              className="rounded-lg border border-surface-600 bg-surface-800 p-3 space-y-2"
            >
              <p className="text-xs text-text-primary">{question.question}</p>
              {question.reason && (
                <p className="text-[10px] text-text-muted leading-relaxed">
                  {question.reason}
                </p>
              )}

              {question.answer_type === 'single_choice' && question.options.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {question.options.map((option) => (
                    <button
                      key={option}
                      type="button"
                      aria-pressed={answers[question.id] === option}
                      onClick={() =>
                        setAnswers((prev) => ({ ...prev, [question.id]: option }))
                      }
                      className={`px-2 py-1 text-[11px] rounded-md border transition-colors ${
                        answers[question.id] === option
                          ? 'bg-ocean-500/20 text-ocean-300 border-ocean-500/40'
                          : 'bg-surface-700 text-text-secondary border-surface-600 hover:bg-surface-600'
                      }`}
                    >
                      {option}
                    </button>
                  ))}
                </div>
              ) : question.answer_type === 'yes_no' ? (
                <div className="flex gap-1.5">
                  {[t.common.yes, t.common.no].map((option) => (
                    <button
                      key={option}
                      type="button"
                      aria-pressed={answers[question.id] === option}
                      onClick={() =>
                        setAnswers((prev) => ({ ...prev, [question.id]: option }))
                      }
                      className={`px-2 py-1 text-[11px] rounded-md border transition-colors ${
                        answers[question.id] === option
                          ? 'bg-ocean-500/20 text-ocean-300 border-ocean-500/40'
                          : 'bg-surface-700 text-text-secondary border-surface-600 hover:bg-surface-600'
                      }`}
                    >
                      {option}
                    </button>
                  ))}
                </div>
              ) : (
                <textarea
                  aria-label={question.question}
                  value={answers[question.id] ?? ''}
                  onChange={(e) =>
                    setAnswers((prev) => ({ ...prev, [question.id]: e.target.value }))
                  }
                  rows={2}
                  className="w-full px-2 py-1.5 text-xs bg-surface-700 border border-surface-600 rounded-lg text-text-primary placeholder-text-muted focus:outline-none focus:border-ocean-500 transition-colors resize-none"
                />
              )}

              <div className="flex gap-1.5">
                <button
                  type="button"
                  disabled={!(answers[question.id] ?? '').trim() || submitting}
                  onClick={() => void submit(question)}
                  className="px-2 py-1 text-[11px] rounded-md bg-ocean-500/15 text-ocean-300 border border-ocean-500/30 hover:bg-ocean-500/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {t.intake.answer}
                </button>
                <button
                  type="button"
                  disabled={submitting}
                  onClick={() => void skip(question)}
                  title={t.intake.skipHint}
                  className="inline-flex items-center gap-1 px-2 py-1 text-[11px] rounded-md bg-surface-700 text-text-muted border border-surface-600 hover:bg-surface-600 transition-colors disabled:opacity-50"
                >
                  <SkipForward className="w-3 h-3" aria-hidden="true" />
                  {t.intake.skip}
                </button>
              </div>
            </div>
          ))}

          <p className="text-[10px] text-text-muted">
            {t.intake.remaining.replace('{n}', String(remaining.length))}
          </p>
        </div>
      )}
    </div>
  )
}
