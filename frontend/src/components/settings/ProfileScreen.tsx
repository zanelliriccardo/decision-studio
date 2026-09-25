import { useEffect, useState } from 'react'
import { Check, Loader2, UserCog } from 'lucide-react'
import { toast } from 'sonner'
import { useT } from '../../i18n/index.tsx'
import * as reasoningApi from '../../lib/api/reasoning.ts'
import type { DecisionProfile, FramingQuestion } from '../../types/reasoning.ts'

/**
 * The answers that hold across every analysis.
 *
 * Role, authority, who must be convinced, hard constraints, which mistake you
 * would rather make — these describe the decider, not the decision. Re-asking
 * them for every analysis produced identical answers and made a second analysis
 * feel like starting over.
 *
 * Answers here are **copied** into the frame of each new analysis, not read
 * through to it. A frame records what was known when that analysis ran, so
 * revising your stated risk appetite today must not quietly rewrite the basis
 * of a decision taken last month.
 */
export default function ProfileScreen() {
  const { t } = useT()
  const [profile, setProfile] = useState<DecisionProfile | null>(null)
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const loaded = await reasoningApi.fetchProfile()
        if (!cancelled) setProfile(loaded)
      } catch (err) {
        if (!cancelled) {
          toast.error(err instanceof Error ? err.message : t.errors.loadFailed)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [t])

  const answers =
    draft ??
    Object.fromEntries(
      (profile?.questions ?? [])
        .filter((q) => q.answer !== null && q.answer !== undefined)
        .map((q) => [q.id, q.answer]),
    )

  const dirty =
    profile?.questions.some(
      (q) => JSON.stringify(q.answer ?? null) !== JSON.stringify(answers[q.id] ?? null),
    ) ?? false

  async function save() {
    setSaving(true)
    try {
      setProfile(await reasoningApi.saveProfile(answers))
      setDraft(null)
      toast.success(t.profile.saved)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t.profile.saveFailed)
    } finally {
      setSaving(false)
    }
  }

  function field(question: FramingQuestion) {
    const value = answers[question.id]
    const base =
      'w-full px-2 py-1.5 text-xs bg-surface-700 border border-surface-600 rounded-lg ' +
      'text-text-primary placeholder-text-muted focus:outline-none focus:border-ocean-500 ' +
      'transition-colors'

    if (question.answerType === 'single_choice') {
      return (
        <div
          className="flex flex-wrap gap-1.5"
          role="group"
          aria-label={question.question}
        >
          {question.options.map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={value === option}
              onClick={() => setDraft({ ...answers, [question.id]: option })}
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
                  setDraft({
                    ...answers,
                    [question.id]: e.target.checked
                      ? [...selected, option]
                      : selected.filter((item) => item !== option),
                  })
                }
                className="accent-ocean-500"
              />
              {option}
            </label>
          ))}
        </fieldset>
      )
    }

    return (
      <textarea
        aria-label={question.question}
        value={typeof value === 'string' ? value : ''}
        onChange={(e) => setDraft({ ...answers, [question.id]: e.target.value })}
        placeholder={question.placeholder ?? ''}
        rows={2}
        className={`${base} resize-none`}
      />
    )
  }

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <div className="flex items-start gap-2 mb-4">
        <UserCog className="w-5 h-5 text-ocean-400 mt-0.5 shrink-0" aria-hidden="true" />
        <div>
          <h1 className="text-lg font-semibold text-text-primary">{t.profile.title}</h1>
          <p className="text-xs text-text-muted mt-1 leading-relaxed">
            {t.profile.intro}
          </p>
        </div>
      </div>

      {profile === null ? (
        <div className="flex items-center justify-center gap-2 py-16 text-text-muted">
          <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
          <span className="text-xs">{t.common.loading}</span>
        </div>
      ) : (
        <div className="space-y-4">
          <div
            className={`px-3 py-2 rounded-lg border text-xs ${
              profile.isComplete
                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
                : 'bg-surface-800 border-surface-700 text-text-muted'
            }`}
            data-testid="profile-status"
          >
            {t.profile.progress
              .replace('{answered}', String(profile.answeredCount))
              .replace('{total}', String(profile.totalCount))}
          </div>

          {profile.questions.map((question) => (
            <div
              key={question.id}
              className="rounded-lg border border-surface-700 bg-surface-800 p-3"
            >
              <span className="text-xs font-medium text-text-primary block">
                {question.question}
              </span>
              <p className="text-[10px] text-text-muted mb-2 mt-0.5 leading-relaxed">
                {question.why}
              </p>
              {field(question)}
            </div>
          ))}

          <button
            type="button"
            disabled={!dirty || saving}
            onClick={() => void save()}
            className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg bg-ocean-500/15 text-ocean-300 border border-ocean-500/30 hover:bg-ocean-500/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {saving ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <Check className="w-3.5 h-3.5" aria-hidden="true" />
            )}
            {t.profile.save}
          </button>

          {/* Stated because the alternative reading — that this edits past
              analyses — would be alarming and is not what happens. */}
          <p className="text-[10px] text-text-muted leading-relaxed">
            {t.profile.appliesToNew}
          </p>
        </div>
      )}
    </div>
  )
}
