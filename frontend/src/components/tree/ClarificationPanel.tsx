import { useState } from 'react'
import {
  AlertTriangle, ArrowRight, Check, HelpCircle, Loader2, RotateCcw, Send,
  SkipForward, Sparkles, Trash2, X,
} from 'lucide-react'
import { useT } from '../../i18n/index.tsx'
import type {
  ApplyAnswersResult, ClarificationQuestion, ProposedGraphChange, QuestionStatus,
  Theory,
} from '../../types/reasoning.ts'

/**
 * The AI Questions tab.
 *
 * Answering never triggers regeneration: the user answers what they can, sees
 * which theories went stale, then decides when to regenerate. Answers that
 * read like graph corrections surface as *proposals* — applying one is an
 * explicit click that routes through the normal review path.
 */

const PRIORITY_CLASSES: Record<ClarificationQuestion['priority'], string> = {
  critical: 'bg-red-500/15 text-red-400 border-red-500/30',
  high: 'bg-orange-500/15 text-orange-400 border-orange-500/30',
  medium: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30',
  low: 'bg-surface-600/40 text-text-muted border-surface-500/30',
}

const GAIN_BARS: Record<ClarificationQuestion['expectedInformationGain'], number> = {
  high: 3,
  medium: 2,
  low: 1,
}

function GainIndicator({
  gain,
}: {
  gain: ClarificationQuestion['expectedInformationGain']
}) {
  const { t } = useT()
  const filled = GAIN_BARS[gain]
  return (
    <span
      className="inline-flex items-center gap-1 text-[10px] text-text-muted"
      title={`${t.clarifications.informationGain}: ${t.clarifications.gain[gain]}`}
    >
      <span className="flex items-end gap-[1px]" aria-hidden="true">
        {[1, 2, 3].map((level) => (
          <span
            key={level}
            className={`w-[2px] rounded-sm bg-ocean-400 ${level <= filled ? '' : 'opacity-25'}`}
            style={{ height: `${3 + level * 2}px` }}
          />
        ))}
      </span>
      {t.clarifications.gain[gain]}
    </span>
  )
}

/** Renders the input appropriate to the question's declared answer type. */
function AnswerInput({
  question,
  onSubmit,
  disabled,
}: {
  question: ClarificationQuestion
  onSubmit: (value: unknown, note?: string) => void
  disabled?: boolean
}) {
  const { t } = useT()
  const [text, setText] = useState('')
  const [multi, setMulti] = useState<string[]>([])
  const [note, setNote] = useState('')

  const submit = (value: unknown) => onSubmit(value, note.trim() || undefined)
  const inputId = `answer-${question.id}`

  const noteField = (
    <input
      type="text"
      value={note}
      onChange={(e) => setNote(e.target.value)}
      placeholder={t.clarifications.notePlaceholder}
      aria-label={t.clarifications.noteLabel}
      className="w-full mt-1.5 px-2 py-1 text-[11px] bg-surface-700 border border-surface-600 rounded-md text-text-primary placeholder-text-muted focus:outline-none focus:border-ocean-500"
    />
  )

  if (question.answerType === 'yes_no') {
    return (
      <div>
        <div className="flex gap-2" role="group" aria-label={question.question}>
          {[
            { value: true, label: t.clarifications.yes },
            { value: false, label: t.clarifications.no },
          ].map((option) => (
            <button
              key={String(option.value)}
              type="button"
              disabled={disabled}
              onClick={() => submit(option.value)}
              className="flex-1 px-2 py-1.5 text-[11px] rounded-md bg-surface-700 text-text-secondary border border-surface-600 hover:bg-ocean-500/15 hover:text-ocean-300 hover:border-ocean-500/30 transition-colors disabled:opacity-50"
            >
              {option.label}
            </button>
          ))}
        </div>
        {noteField}
      </div>
    )
  }

  if (question.answerType === 'single_choice') {
    return (
      <div>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label={question.question}>
          {(question.options ?? []).map((option) => (
            <button
              key={option}
              type="button"
              disabled={disabled}
              onClick={() => submit(option)}
              className="px-2 py-1 text-[11px] rounded-md bg-surface-700 text-text-secondary border border-surface-600 hover:bg-ocean-500/15 hover:text-ocean-300 hover:border-ocean-500/30 transition-colors disabled:opacity-50"
            >
              {option}
            </button>
          ))}
        </div>
        {noteField}
      </div>
    )
  }

  if (question.answerType === 'multi_choice') {
    return (
      <div>
        <fieldset className="space-y-1">
          <legend className="sr-only">{question.question}</legend>
          {(question.options ?? []).map((option) => (
            <label
              key={option}
              className="flex items-center gap-2 text-[11px] text-text-secondary cursor-pointer"
            >
              <input
                type="checkbox"
                checked={multi.includes(option)}
                onChange={(e) =>
                  setMulti((prev) =>
                    e.target.checked
                      ? [...prev, option]
                      : prev.filter((item) => item !== option),
                  )
                }
                className="accent-ocean-500"
              />
              {option}
            </label>
          ))}
        </fieldset>
        {noteField}
        <button
          type="button"
          disabled={disabled || multi.length === 0}
          onClick={() => submit(multi)}
          className="mt-1.5 inline-flex items-center gap-1 px-2 py-1 text-[10px] rounded-md bg-ocean-500/15 text-ocean-300 border border-ocean-500/30 hover:bg-ocean-500/25 transition-colors disabled:opacity-40"
        >
          <Send className="w-3 h-3" aria-hidden="true" />
          {t.clarifications.saveAnswer}
        </button>
      </div>
    )
  }

  const inputType =
    question.answerType === 'number'
      ? 'number'
      : question.answerType === 'date'
        ? 'date'
        : 'text'

  return (
    <div>
      <label htmlFor={inputId} className="sr-only">
        {question.question}
      </label>
      <input
        id={inputId}
        type={inputType}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={
          question.answerType === 'free_text'
            ? t.clarifications.answerPlaceholder
            : undefined
        }
        className="w-full px-2 py-1.5 text-[11px] bg-surface-700 border border-surface-600 rounded-md text-text-primary placeholder-text-muted focus:outline-none focus:border-ocean-500"
      />
      {noteField}
      <button
        type="button"
        disabled={disabled || !text.trim()}
        onClick={() =>
          submit(question.answerType === 'number' ? Number(text) : text.trim())
        }
        className="mt-1.5 inline-flex items-center gap-1 px-2 py-1 text-[10px] rounded-md bg-ocean-500/15 text-ocean-300 border border-ocean-500/30 hover:bg-ocean-500/25 transition-colors disabled:opacity-40"
      >
        <Send className="w-3 h-3" aria-hidden="true" />
        {t.clarifications.saveAnswer}
      </button>
    </div>
  )
}

function formatAnswer(value: unknown): string {
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return String(value ?? '')
}

function QuestionCard({
  question,
  theories,
  onAnswer,
  onStatus,
  busy,
}: {
  question: ClarificationQuestion
  theories: Theory[]
  onAnswer: (value: unknown, note?: string) => void
  onStatus: (status: QuestionStatus) => void
  busy?: boolean
}) {
  const { t } = useT()
  const affected = theories.filter((theory) =>
    question.linkedTheoryIds.includes(theory.id),
  )
  const isOpen = question.status === 'open'

  return (
    <article
      className={`rounded-lg border p-3 space-y-2 ${
        isOpen
          ? 'border-surface-600 bg-surface-800'
          : 'border-surface-700 bg-surface-800/50 opacity-75'
      }`}
      data-testid="question-card"
      data-status={question.status}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <span
          className={`px-1.5 py-0.5 rounded text-[9px] font-medium border ${PRIORITY_CLASSES[question.priority]}`}
          title={`${t.clarifications.priorityLabel}: ${t.clarifications.priority[question.priority]}`}
        >
          {t.clarifications.priority[question.priority]}
        </span>
        <GainIndicator gain={question.expectedInformationGain} />
        {question.status !== 'open' && (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-medium bg-surface-700 text-text-muted border border-surface-600">
            {question.status === 'answered' && (
              <Check className="w-2.5 h-2.5" aria-hidden="true" />
            )}
            {t.clarifications.status[question.status]}
          </span>
        )}
      </div>

      <p className="text-xs font-medium text-text-primary leading-snug">
        {question.question}
      </p>

      {question.reason && (
        <p className="text-[11px] text-text-muted leading-relaxed">
          <span className="font-medium text-text-secondary">
            {t.clarifications.why}:{' '}
          </span>
          {question.reason}
        </p>
      )}

      {affected.length > 0 && (
        <div className="px-2 py-1.5 rounded-md bg-surface-700/60 border border-surface-600">
          <p className="text-[10px] font-medium text-text-muted mb-0.5">
            {t.clarifications.affects}
          </p>
          <ul className="space-y-0.5">
            {affected.map((theory) => (
              <li key={theory.id} className="text-[10px] text-text-secondary flex gap-1">
                <ArrowRight className="w-2.5 h-2.5 mt-0.5 shrink-0" aria-hidden="true" />
                {theory.title}
              </li>
            ))}
          </ul>
        </div>
      )}

      {question.status === 'answered' && (
        <div className="px-2 py-1.5 rounded-md bg-emerald-500/10 border border-emerald-500/25">
          <p className="text-[11px] text-emerald-300">
            {formatAnswer(question.answer)}
          </p>
          {question.answerNote && (
            <p className="text-[10px] text-text-muted mt-0.5">{question.answerNote}</p>
          )}
        </div>
      )}

      {isOpen && (
        <AnswerInput question={question} onSubmit={onAnswer} disabled={busy} />
      )}

      <div className="flex items-center gap-2 pt-1">
        {isOpen && (
          <>
            <button
              type="button"
              onClick={() => onStatus('skipped')}
              className="inline-flex items-center gap-1 px-2 py-1 text-[10px] rounded-md text-text-muted hover:text-text-secondary hover:bg-surface-700 transition-colors"
            >
              <SkipForward className="w-3 h-3" aria-hidden="true" />
              {t.clarifications.skip}
            </button>
            <button
              type="button"
              onClick={() => onStatus('dismissed')}
              className="inline-flex items-center gap-1 px-2 py-1 text-[10px] rounded-md text-text-muted hover:text-red-400 hover:bg-surface-700 transition-colors"
            >
              <Trash2 className="w-3 h-3" aria-hidden="true" />
              {t.clarifications.dismiss}
            </button>
          </>
        )}
        {!isOpen && (
          <button
            type="button"
            onClick={() => onStatus('open')}
            className="inline-flex items-center gap-1 px-2 py-1 text-[10px] rounded-md text-text-muted hover:text-ocean-400 hover:bg-surface-700 transition-colors"
          >
            <RotateCcw className="w-3 h-3" aria-hidden="true" />
            {t.clarifications.reopen}
          </button>
        )}
      </div>
    </article>
  )
}

interface ClarificationPanelProps {
  questions: ClarificationQuestion[]
  theories: Theory[]
  loading: boolean
  generating: boolean
  error: string | null
  onGenerate: () => void
  onAnswer: (questionId: string, value: unknown, note?: string) => void
  onStatus: (questionId: string, status: QuestionStatus) => void
  onApply: () => Promise<ApplyAnswersResult | null>
  onApplyProposal: (change: ProposedGraphChange) => void
  onRegenerate: () => void
  onClose: () => void
}

export default function ClarificationPanel({
  questions,
  theories,
  loading,
  generating,
  error,
  onGenerate,
  onAnswer,
  onStatus,
  onApply,
  onApplyProposal,
  onRegenerate,
  onClose,
}: ClarificationPanelProps) {
  const { t } = useT()
  const [proposals, setProposals] = useState<ProposedGraphChange[]>([])
  const [applying, setApplying] = useState(false)

  const open = questions.filter((q) => q.status === 'open')
  const answered = questions.filter((q) => q.status === 'answered')
  const closed = questions.filter(
    (q) => q.status === 'dismissed' || q.status === 'skipped',
  )

  const handleApply = async () => {
    setApplying(true)
    try {
      const result = await onApply()
      setProposals(result?.proposedGraphChanges ?? [])
    } finally {
      setApplying(false)
    }
  }

  return (
    <div className="w-full bg-surface-800 border-l border-surface-700 h-full overflow-y-auto flex flex-col">
      <div className="flex items-center justify-between p-4 border-b border-surface-700 shrink-0">
        <div className="flex items-center gap-2">
          <HelpCircle className="w-4 h-4 text-ocean-400" aria-hidden="true" />
          <h3 className="text-sm font-semibold text-text-primary">
            {t.clarifications.title}
          </h3>
          {open.length > 0 && (
            <span className="text-[10px] text-ocean-300 bg-ocean-500/15 px-1.5 py-0.5 rounded-full">
              {open.length}
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
        <button
          type="button"
          onClick={onGenerate}
          disabled={generating}
          className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg bg-ocean-500/15 text-ocean-300 border border-ocean-500/30 hover:bg-ocean-500/25 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {generating ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
          ) : (
            <Sparkles className="w-3.5 h-3.5" aria-hidden="true" />
          )}
          {generating ? t.clarifications.generating : t.clarifications.generate}
        </button>

        {loading && (
          <div
            className="flex items-center justify-center gap-2 py-8 text-text-muted"
            data-testid="questions-loading"
          >
            <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
            <span className="text-xs">{t.common.loading}</span>
          </div>
        )}

        {!loading && error && (
          <div
            className="px-3 py-3 rounded-lg bg-red-500/10 border border-red-500/30"
            role="alert"
            data-testid="questions-error"
          >
            <p className="text-xs text-red-300">{error}</p>
          </div>
        )}

        {!loading && !error && questions.length === 0 && (
          <div className="py-8 text-center" data-testid="questions-empty">
            <HelpCircle className="w-6 h-6 text-text-muted mx-auto mb-2" aria-hidden="true" />
            <p className="text-xs text-text-muted">{t.clarifications.empty}</p>
            <p className="text-[10px] text-text-muted/70 mt-1">
              {t.clarifications.emptyHint}
            </p>
          </div>
        )}

        {open.length > 0 && (
          <section className="space-y-2.5">
            <h4 className="text-[11px] font-semibold text-text-muted">
              {t.clarifications.openSection} ({open.length})
            </h4>
            {open.map((question) => (
              <QuestionCard
                key={question.id}
                question={question}
                theories={theories}
                onAnswer={(value, note) => onAnswer(question.id, value, note)}
                onStatus={(status) => onStatus(question.id, status)}
              />
            ))}
          </section>
        )}

        {answered.length > 0 && (
          <section className="space-y-2.5">
            <h4 className="text-[11px] font-semibold text-text-muted">
              {t.clarifications.answeredSection} ({answered.length})
            </h4>
            {answered.map((question) => (
              <QuestionCard
                key={question.id}
                question={question}
                theories={theories}
                onAnswer={(value, note) => onAnswer(question.id, value, note)}
                onStatus={(status) => onStatus(question.id, status)}
              />
            ))}

            <div className="space-y-2 pt-1">
              <button
                type="button"
                onClick={handleApply}
                disabled={applying}
                className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg bg-surface-700 text-text-secondary border border-surface-600 hover:bg-surface-600 transition-colors disabled:opacity-50"
              >
                {applying ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
                ) : (
                  <Check className="w-3.5 h-3.5" aria-hidden="true" />
                )}
                {t.clarifications.apply}
              </button>
              <button
                type="button"
                onClick={onRegenerate}
                className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg bg-ocean-500/15 text-ocean-300 border border-ocean-500/30 hover:bg-ocean-500/25 transition-colors"
              >
                <Sparkles className="w-3.5 h-3.5" aria-hidden="true" />
                {t.clarifications.regenerateNow}
              </button>
              <p className="text-[10px] text-text-muted text-center">
                {t.clarifications.regenerateHint}
              </p>
            </div>
          </section>
        )}

        {/* Proposed graph changes — surfaced, never applied automatically */}
        {proposals.length > 0 && (
          <section
            className="space-y-2 px-2.5 py-2 rounded-lg bg-amber-500/10 border border-amber-500/30"
            data-testid="graph-proposals"
          >
            <h4 className="flex items-center gap-1.5 text-[11px] font-semibold text-amber-300">
              <AlertTriangle className="w-3 h-3" aria-hidden="true" />
              {t.clarifications.proposalsTitle}
            </h4>
            <p className="text-[10px] text-amber-200/80">
              {t.clarifications.proposalsHint}
            </p>
            {proposals.map((change) => (
              <div
                key={`${change.questionId}-${change.targetId}`}
                className="px-2 py-1.5 rounded-md bg-surface-800/60 border border-surface-600 space-y-1.5"
              >
                <p className="text-[10px] text-text-secondary">{change.rationale}</p>
                <div className="flex gap-1.5">
                  <button
                    type="button"
                    onClick={() => {
                      onApplyProposal(change)
                      setProposals((prev) =>
                        prev.filter((item) => item.targetId !== change.targetId),
                      )
                    }}
                    className="px-2 py-1 text-[10px] rounded-md bg-amber-500/20 text-amber-300 border border-amber-500/40 hover:bg-amber-500/30 transition-colors"
                  >
                    {t.clarifications.applyProposal}
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      setProposals((prev) =>
                        prev.filter((item) => item.targetId !== change.targetId),
                      )
                    }
                    className="px-2 py-1 text-[10px] rounded-md bg-surface-700 text-text-muted border border-surface-600 hover:bg-surface-600 transition-colors"
                  >
                    {t.clarifications.ignoreProposal}
                  </button>
                </div>
              </div>
            ))}
          </section>
        )}

        {closed.length > 0 && (
          <section className="space-y-2.5">
            <h4 className="text-[11px] font-semibold text-text-muted">
              {t.clarifications.closedSection} ({closed.length})
            </h4>
            {closed.map((question) => (
              <QuestionCard
                key={question.id}
                question={question}
                theories={theories}
                onAnswer={(value, note) => onAnswer(question.id, value, note)}
                onStatus={(status) => onStatus(question.id, status)}
              />
            ))}
          </section>
        )}
      </div>
    </div>
  )
}
