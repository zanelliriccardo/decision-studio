import { useState } from 'react'
import {
  AlertTriangle, Check, ChevronDown, ChevronRight, ClipboardList,
  HelpCircle, Loader2, SkipForward,
} from 'lucide-react'
import { useT } from '../../i18n/index.tsx'
import type { DecisionFrame, FramingQuestion } from '../../types/reasoning.ts'

/**
 * Every question the system needs, in one place, on the screen the user is
 * already watching while the pipeline runs.
 *
 * There are two kinds, asked together because being asked twice in two
 * different places is worse than a longer single form:
 *
 *  - **Intake** — ambiguity in the extracted claims. These hold the pipeline,
 *    because correcting a misread claim now edits one row and correcting it
 *    after inference means re-inferring its links and re-propagating everything
 *    downstream.
 *  - **Framing** — what decision this is, by when, how reversible. These do not
 *    hold the pipeline: the graph does not need them. They gate *theory
 *    generation*, which is why leaving them until the graph screen meant
 *    discovering the gate as a 409 with nowhere to go.
 *
 * Neither stops the pipeline. It runs to completion while these are open, and
 * an answer given afterwards proposes graph changes rather than being applied
 * silently — the same path a post-theory clarification takes. Holding an
 * expensive run open on someone who may have stepped away costs more than
 * correcting the graph once they return.
 */

export interface IntakeQuestion {
  id: string
  question: string
  reason: string
  answer_type: 'free_text' | 'single_choice' | 'yes_no'
  options: string[]
}

const SECTION_ORDER: FramingQuestion['section'][] = [
  'role', 'decision', 'criteria', 'belief', 'sources',
]

function FieldFor({
  question,
  value,
  onChange,
}: {
  question: FramingQuestion
  value: unknown
  onChange: (value: unknown) => void
}) {
  const base =
    'w-full px-2 py-1.5 text-xs bg-surface-700 border border-surface-600 rounded-lg ' +
    'text-text-primary placeholder-text-muted focus:outline-none focus:border-ocean-500 ' +
    'transition-colors'

  if (question.answerType === 'single_choice') {
    return (
      <div className="flex flex-wrap gap-1.5" role="group" aria-label={question.question}>
        {question.options.map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={value === option}
            onClick={() => onChange(option)}
            className={`px-2 py-1 text-[11px] rounded-md border transition-colors ${
              value === option
                ? 'bg-ocean-500/20 text-ocean-300 border-ocean-500/40'
                : 'bg-surface-700 text-text-secondary border-surface-600 hover:bg-surface-600'
            }`}
          >
            {option}
          </button>
        ))}
      </div>
    )
  }

  if (question.answerType === 'multi_choice') {
    const selected = Array.isArray(value) ? (value as string[]) : []
    return (
      <fieldset className="space-y-1">
        <legend className="sr-only">{question.question}</legend>
        {question.options.map((option) => (
          <label
            key={option}
            className="flex items-center gap-2 text-[11px] text-text-secondary cursor-pointer"
          >
            <input
              type="checkbox"
              checked={selected.includes(option)}
              onChange={(e) =>
                onChange(
                  e.target.checked
                    ? [...selected, option]
                    : selected.filter((item) => item !== option),
                )
              }
              className="accent-ocean-500"
            />
            {option}
          </label>
        ))}
      </fieldset>
    )
  }

  if (question.answerType === 'date') {
    return (
      <input
        type="date"
        aria-label={question.question}
        value={typeof value === 'string' ? value : ''}
        onChange={(e) => onChange(e.target.value)}
        className={base}
      />
    )
  }

  return (
    <textarea
      aria-label={question.question}
      value={typeof value === 'string' ? value : ''}
      onChange={(e) => onChange(e.target.value)}
      placeholder={question.placeholder ?? ''}
      rows={2}
      className={`${base} resize-none`}
    />
  )
}

interface QuestionsStepProps {
  intakeQuestions: IntakeQuestion[]
  frame: DecisionFrame | null
  submitting: boolean
  onAnswerIntake: (id: string, value: string) => Promise<boolean>
  onSkipIntake: (id: string) => Promise<boolean>
  onSaveFrame: (answers: Record<string, unknown>) => Promise<void> | void
}

export default function QuestionsStep({
  intakeQuestions,
  frame,
  submitting,
  onAnswerIntake,
  onSkipIntake,
  onSaveFrame,
}: QuestionsStepProps) {
  const { t } = useT()
  const [intakeAnswers, setIntakeAnswers] = useState<Record<string, string>>({})
  const [handled, setHandled] = useState<Set<string>>(new Set())
  const [frameDraft, setFrameDraft] = useState<Record<string, unknown> | null>(null)
  const [openSections, setOpenSections] = useState<Set<string>>(new Set(SECTION_ORDER))

  const remainingIntake = intakeQuestions.filter((q) => !handled.has(q.id))

  // Seeded lazily from the frame so a save does not discard in-progress typing.
  const draft =
    frameDraft ??
    Object.fromEntries(
      (frame?.questions ?? [])
        .filter((q) => q.answer !== null && q.answer !== undefined)
        .map((q) => [q.id, q.answer]),
    )

  const missing = new Set(frame?.missingRequired ?? [])
  const bySection = new Map<string, FramingQuestion[]>()
  // A profile question already answered is not re-asked here: it was answered
  // once on purpose, and showing it again invites re-answering it every time.
  frame?.questions
    .filter(
      (q) =>
        q.scope !== 'profile' ||
        q.answer === null ||
        q.answer === undefined ||
        q.answer === '',
    )
    .forEach((q) => {
      bySection.set(q.section, [...(bySection.get(q.section) ?? []), q])
    })

  const reusedFromProfile =
    frame?.questions.filter(
      (q) => q.scope === 'profile' && q.answer !== null && q.answer !== undefined,
    ).length ?? 0

  const frameDirty =
    frame?.questions.some(
      (q) => JSON.stringify(q.answer ?? null) !== JSON.stringify(draft[q.id] ?? null),
    ) ?? false

  async function submitIntake(question: IntakeQuestion) {
    const value = (intakeAnswers[question.id] ?? '').trim()
    if (!value) return
    if (await onAnswerIntake(question.id, value)) {
      setHandled((prev) => new Set(prev).add(question.id))
    }
  }

  async function skip(question: IntakeQuestion) {
    if (await onSkipIntake(question.id)) {
      setHandled((prev) => new Set(prev).add(question.id))
    }
  }

  const toggle = (section: string) =>
    setOpenSections((prev) => {
      const next = new Set(prev)
      if (next.has(section)) next.delete(section)
      else next.add(section)
      return next
    })

  return (
    <div className="space-y-4" data-testid="questions-step">
      {/* ── Intake: these hold the pipeline ── */}
      {remainingIntake.length > 0 && (
        <section
          className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 space-y-3"
          data-testid="intake-questions"
        >
          <div className="flex items-start gap-2">
            <HelpCircle
              className="w-4 h-4 text-amber-400 mt-0.5 shrink-0"
              aria-hidden="true"
            />
            <div>
              <h3 className="text-sm font-semibold text-text-primary">
                {t.intake.title}
              </h3>
              <p className="text-[11px] text-text-muted mt-0.5 leading-relaxed">
                {t.intake.whyNotBlocking}
              </p>
            </div>
          </div>

          {remainingIntake.map((question) => (
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
                      aria-pressed={intakeAnswers[question.id] === option}
                      onClick={() =>
                        setIntakeAnswers((prev) => ({ ...prev, [question.id]: option }))
                      }
                      className={`px-2 py-1 text-[11px] rounded-md border transition-colors ${
                        intakeAnswers[question.id] === option
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
                      aria-pressed={intakeAnswers[question.id] === option}
                      onClick={() =>
                        setIntakeAnswers((prev) => ({ ...prev, [question.id]: option }))
                      }
                      className={`px-2 py-1 text-[11px] rounded-md border transition-colors ${
                        intakeAnswers[question.id] === option
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
                  value={intakeAnswers[question.id] ?? ''}
                  onChange={(e) =>
                    setIntakeAnswers((prev) => ({
                      ...prev,
                      [question.id]: e.target.value,
                    }))
                  }
                  rows={2}
                  className="w-full px-2 py-1.5 text-xs bg-surface-700 border border-surface-600 rounded-lg text-text-primary focus:outline-none focus:border-ocean-500 transition-colors resize-none"
                />
              )}

              <div className="flex gap-1.5">
                <button
                  type="button"
                  disabled={!(intakeAnswers[question.id] ?? '').trim() || submitting}
                  onClick={() => void submitIntake(question)}
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
        </section>
      )}

      {/* ── Framing: these gate theories, not the pipeline ── */}
      {frame && (
        <section
          className="rounded-xl border border-surface-700 bg-surface-800 p-4 space-y-3"
          data-testid="framing-questions"
        >
          <div className="flex items-start gap-2">
            <ClipboardList
              className="w-4 h-4 text-ocean-400 mt-0.5 shrink-0"
              aria-hidden="true"
            />
            <div>
              <h3 className="text-sm font-semibold text-text-primary">
                {t.framing.title}
              </h3>
              <p className="text-[11px] text-text-muted mt-0.5 leading-relaxed">
                {t.framing.intro}
              </p>
            </div>
          </div>

          <div
            className={`px-2.5 py-2 rounded-lg border ${
              frame.canGenerateTheories
                ? 'bg-emerald-500/10 border-emerald-500/30'
                : 'bg-amber-500/10 border-amber-500/30'
            }`}
            role="status"
            data-testid="framing-status"
          >
            <p
              className={`text-[11px] flex items-start gap-1.5 ${
                frame.canGenerateTheories ? 'text-emerald-300' : 'text-amber-300'
              }`}
            >
              {frame.canGenerateTheories ? (
                <Check className="w-3 h-3 mt-0.5 shrink-0" aria-hidden="true" />
              ) : (
                <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" aria-hidden="true" />
              )}
              {frame.canGenerateTheories
                ? t.framing.ready
                : t.framing.blocked.replace('{n}', String(frame.missingRequired.length))}
            </p>
            <p className="text-[10px] text-text-muted mt-1">
              {t.framing.progress
                .replace('{answered}', String(frame.answeredCount))
                .replace('{total}', String(frame.totalCount))}
              {reusedFromProfile > 0 && (
                <>
                  {' · '}
                  {t.framing.reusedFromProfile.replace(
                    '{n}',
                    String(reusedFromProfile),
                  )}
                </>
              )}
            </p>
          </div>

          {SECTION_ORDER.map((section) => {
            const questions = bySection.get(section) ?? []
            if (questions.length === 0) return null
            const open = openSections.has(section)
            const sectionMissing = questions.filter((q) => missing.has(q.id)).length

            return (
              <div key={section} className="rounded-lg border border-surface-600">
                <button
                  type="button"
                  onClick={() => toggle(section)}
                  aria-expanded={open}
                  className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-surface-700/50 transition-colors"
                >
                  <span className="text-xs font-medium text-text-primary flex items-center gap-1.5">
                    {open ? (
                      <ChevronDown className="w-3 h-3" aria-hidden="true" />
                    ) : (
                      <ChevronRight className="w-3 h-3" aria-hidden="true" />
                    )}
                    {t.framing.sections[section]}
                  </span>
                  {sectionMissing > 0 && (
                    <span className="text-[10px] text-amber-400">
                      {sectionMissing} {t.framing.stillNeeded}
                    </span>
                  )}
                </button>

                {open && (
                  <div className="px-3 pb-3 space-y-3">
                    {questions.map((question) => (
                      <div key={question.id}>
                        <span className="text-[11px] font-medium text-text-primary block">
                          {question.question}
                          {question.required && (
                            <span
                              className="ml-1 text-amber-400"
                              title={t.framing.requiredHint}
                            >
                              *
                            </span>
                          )}
                        </span>
                        <p className="text-[10px] text-text-muted mb-1.5 leading-relaxed">
                          {question.why}
                        </p>
                        <FieldFor
                          question={question}
                          value={draft[question.id]}
                          onChange={(value) =>
                            setFrameDraft({ ...draft, [question.id]: value })
                          }
                        />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )
          })}

          <button
            type="button"
            disabled={!frameDirty || submitting}
            onClick={() => {
              void onSaveFrame(draft)
              setFrameDraft(null)
            }}
            className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg bg-ocean-500/15 text-ocean-300 border border-ocean-500/30 hover:bg-ocean-500/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {submitting ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <Check className="w-3.5 h-3.5" aria-hidden="true" />
            )}
            {t.framing.save}
          </button>
        </section>
      )}

    </div>
  )
}
