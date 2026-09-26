// DEAD-CODE-CANDIDATE DC-37 [file]: 15-question framing removed; unreachable. See docs/DEAD_CODE_REPORT.md
import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle, Check, ChevronDown, ChevronRight, ClipboardList, Loader2, X,
} from 'lucide-react'
import { useT } from '../../i18n/index.tsx'
import type { DecisionFrame, FramingQuestion } from '../../types/reasoning.ts'

/**
 * The framing questionnaire, and the gate in front of theory generation.
 *
 * Strategic decisions have no data to appeal to, so output quality is bounded
 * by the quality of the question. Generating before the user has said what is
 * being decided, by whom and by when produces a summary of the uploaded
 * documents wearing a recommendation — which is worse than no answer, because
 * it looks like one.
 *
 * Every question shows *why* it is asked. A questionnaire that reads as
 * bureaucracy gets filled in carelessly, and careless answers are worse than
 * blank ones.
 */

const SECTION_ORDER: FramingQuestion['section'][] = [
  'role',
  'decision',
  'criteria',
  'belief',
  'sources',
]

function QuestionField({
  question,
  value,
  onChange,
}: {
  question: FramingQuestion
  value: unknown
  onChange: (value: unknown) => void
}) {
  const inputId = `frame-${question.id}`
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
        id={inputId}
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
      id={inputId}
      aria-label={question.question}
      value={typeof value === 'string' ? value : ''}
      onChange={(e) => onChange(e.target.value)}
      placeholder={question.placeholder ?? ''}
      rows={2}
      className={`${base} resize-none`}
    />
  )
}

interface FramingPanelProps {
  frame: DecisionFrame | null
  loading: boolean
  saving: boolean
  error: string | null
  onSave: (answers: Record<string, unknown>) => void | Promise<void>
  onClose: () => void
}

export default function FramingPanel({
  frame,
  loading,
  saving,
  error,
  onSave,
  onClose,
}: FramingPanelProps) {
  const { t } = useT()
  const [draft, setDraft] = useState<Record<string, unknown>>({})
  // Open by default: collapsing hides the very questions that gate generation,
  // and a questionnaire the user has to go hunting for gets filled in badly.
  const [openSections, setOpenSections] = useState<Set<string>>(
    new Set(SECTION_ORDER),
  )

  useEffect(() => {
    // Seed the draft from saved answers whenever the frame reloads.
    if (!frame) return
    const seeded: Record<string, unknown> = {}
    frame.questions.forEach((q) => {
      if (q.answer !== null && q.answer !== undefined) seeded[q.id] = q.answer
    })
    setDraft(seeded)
  }, [frame])

  const bySection = useMemo(() => {
    const map = new Map<string, FramingQuestion[]>()
    frame?.questions.forEach((q) => {
      map.set(q.section, [...(map.get(q.section) ?? []), q])
    })
    return map
  }, [frame])

  const dirty = useMemo(() => {
    if (!frame) return false
    return frame.questions.some((q) => {
      const saved = q.answer ?? null
      const current = draft[q.id] ?? null
      return JSON.stringify(saved) !== JSON.stringify(current)
    })
  }, [frame, draft])

  const toggle = (section: string) =>
    setOpenSections((prev) => {
      const next = new Set(prev)
      if (next.has(section)) next.delete(section)
      else next.add(section)
      return next
    })

  const missing = new Set(frame?.missingRequired ?? [])

  return (
    <div className="w-full bg-surface-800 border-l border-surface-700 h-full overflow-y-auto flex flex-col">
      <div className="flex items-center justify-between p-4 border-b border-surface-700 shrink-0">
        <div className="flex items-center gap-2">
          <ClipboardList className="w-4 h-4 text-ocean-400" aria-hidden="true" />
          <h3 className="text-sm font-semibold text-text-primary">{t.framing.title}</h3>
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
        <p className="text-[11px] text-text-muted leading-relaxed">
          {t.framing.intro}
        </p>

        {loading && (
          <div
            className="flex items-center justify-center gap-2 py-8 text-text-muted"
            data-testid="framing-loading"
          >
            <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
            <span className="text-xs">{t.common.loading}</span>
          </div>
        )}

        {!loading && error && (
          <div
            className="px-3 py-3 rounded-lg bg-red-500/10 border border-red-500/30"
            role="alert"
            data-testid="framing-error"
          >
            <p className="text-xs text-red-300">{error}</p>
          </div>
        )}

        {frame && !loading && (
          <>
            {/* Progress and the gate */}
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
                  : t.framing.blocked.replace(
                      '{n}',
                      String(frame.missingRequired.length),
                    )}
              </p>
              <p className="text-[10px] text-text-muted mt-1">
                {t.framing.progress
                  .replace('{answered}', String(frame.answeredCount))
                  .replace('{total}', String(frame.totalCount))}
              </p>
            </div>

            {SECTION_ORDER.map((section) => {
              const questions = bySection.get(section) ?? []
              if (questions.length === 0) return null
              const open = openSections.has(section)
              const sectionMissing = questions.filter((q) => missing.has(q.id)).length

              return (
                <section key={section} className="rounded-lg border border-surface-600">
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
                          <label
                            htmlFor={`frame-${question.id}`}
                            className="text-[11px] font-medium text-text-primary block"
                          >
                            {question.question}
                            {question.required && (
                              <span
                                className="ml-1 text-amber-400"
                                title={t.framing.requiredHint}
                              >
                                *
                              </span>
                            )}
                          </label>
                          {/* Why it is asked, shown rather than assumed. */}
                          <p className="text-[10px] text-text-muted mb-1.5 leading-relaxed">
                            {question.why}
                          </p>
                          <QuestionField
                            question={question}
                            value={draft[question.id]}
                            onChange={(value) =>
                              setDraft((prev) => ({ ...prev, [question.id]: value }))
                            }
                          />
                        </div>
                      ))}
                    </div>
                  )}
                </section>
              )
            })}

            <button
              type="button"
              disabled={!dirty || saving}
              onClick={() => void onSave(draft)}
              className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg bg-ocean-500/15 text-ocean-300 border border-ocean-500/30 hover:bg-ocean-500/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {saving ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
              ) : (
                <Check className="w-3.5 h-3.5" aria-hidden="true" />
              )}
              {t.framing.save}
            </button>
          </>
        )}
      </div>
    </div>
  )
}
