import { useEffect, useState } from 'react'
import { History } from 'lucide-react'
import { useT } from '../../i18n/index.tsx'
import { fetchTimeline, type Timeline } from '../../lib/api/workspace.ts'

const COMPACT = 8

/**
 * The decision journal: what was believed, and what changed it. Material events
 * by default, most recent first; every event comes from a dated record.
 */
export default function TimelineCard({
  projectId,
  refreshKey,
  timeline: preloaded,
}: {
  projectId: string
  refreshKey?: unknown
  timeline?: Timeline
}) {
  const { t, lang } = useT()
  const [timeline, setTimeline] = useState<Timeline | null>(preloaded ?? null)
  const [all, setAll] = useState(false)

  useEffect(() => {
    if (preloaded) return
    let cancelled = false
    fetchTimeline(projectId)
      .then((loaded) => !cancelled && setTimeline(loaded))
      .catch(() => !cancelled && setTimeline(null))
    return () => {
      cancelled = true
    }
  }, [projectId, refreshKey, preloaded])

  if (!timeline) return null
  const newestFirst = [...timeline.events].reverse()
  const shown = all ? newestFirst : newestFirst.filter((e) => e.material).slice(0, COMPACT)
  const date = (iso: string) =>
    new Date(iso).toLocaleDateString(lang === 'zh' ? 'zh-CN' : 'en-GB', { day: '2-digit', month: 'short', year: 'numeric' })

  return (
    <section className="rounded-xl border border-surface-700 bg-surface-800 p-4 space-y-2.5" data-testid="timeline">
      <h2 className="text-xs font-semibold text-text-primary flex items-center gap-1.5">
        <History className="w-3.5 h-3.5 text-text-muted" aria-hidden="true" />
        {t.workspace.timelineTitle}
      </h2>
      <p className="text-[11px] text-text-muted leading-relaxed">{t.workspace.timelineHint}</p>
      {shown.length === 0 ? (
        <p className="text-[11px] text-text-muted">{t.workspace.timelineEmpty}</p>
      ) : (
        <ol className="relative border-l border-surface-600 ml-1 space-y-2">
          {shown.map((event, index) => (
            <li key={`${event.at}-${index}`} className="pl-3 text-xs" data-testid="timeline-event" data-material={event.material}>
              <span
                className={`absolute -left-[4px] mt-1 w-2 h-2 rounded-full ${event.material ? 'bg-ocean-400' : 'bg-surface-500'}`}
                aria-hidden="true"
              />
              <span className="text-[10px] text-text-muted">{date(event.at)}</span>
              <span className="block text-text-primary">{event.title}</span>
              {event.beliefChange && (
                <span className="block text-[11px] text-ocean-300" data-testid="belief-change">{event.beliefChange}</span>
              )}
              {event.detail && <span className="block text-[10px] text-text-muted">{event.detail}</span>}
            </li>
          ))}
        </ol>
      )}
      {timeline.total > 0 && (
        <button
          type="button"
          onClick={() => setAll(!all)}
          className="text-[10px] text-text-muted hover:text-text-secondary"
        >
          {all ? t.workspace.showMaterial : t.workspace.showAll.replace('{n}', String(timeline.total))}
        </button>
      )}
    </section>
  )
}
