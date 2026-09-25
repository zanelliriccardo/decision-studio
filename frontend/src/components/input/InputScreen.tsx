import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { Send, Cat, Upload, FileText, Image, X, Clock, CheckCircle2, Loader2, AlertCircle } from 'lucide-react'
import { Button, Textarea, Toggle } from '../ui/index.ts'
import DemoScenarios from './DemoScenarios.tsx'
import { apiPost, apiGet } from '../../lib/api/client.ts'
import { useT } from '../../i18n/index.tsx'
import { useIntakeEnabled } from '../../hooks/useIntakeEnabled.ts'
import type { AnalyzeRequest, AnalyzeResponse, ProjectSummary } from '../../types/api.ts'
import type { IntakeResponse } from '../../types/intake.ts'

const ACCEPTED_FILE_TYPES = '.txt,.md,.csv,.json,.pdf,.png,.jpg,.jpeg,.webp,.gif'

interface UploadResponse {
  document_id: string
  title: string
  filename: string
  size_bytes: number
  char_count: number
  text: string
  extraction_error: string | null
}

/** An attached document. Its full text stays on the server. */
interface AttachedDocument {
  id: string
  filename: string
  charCount: number
  sizeBytes: number
  error: string | null
}

function timeAgo(dateStr: string): string {
  const now = Date.now()
  const then = new Date(dateStr).getTime()
  const seconds = Math.floor((now - then) / 1000)
  if (seconds < 60) return '<1m'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h`
  const days = Math.floor(hours / 24)
  return `${days}d`
}

export default function InputScreen() {
  const [title, setTitle] = useState('')
  const [objective, setObjective] = useState('')
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [documents, setDocuments] = useState<AttachedDocument[]>([])
  const [history, setHistory] = useState<ProjectSummary[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()
  const { t } = useT()
  const { enabled: intakeEnabled, setEnabled: setIntakeEnabled } = useIntakeEnabled()

  // Fetch project history on mount
  useEffect(() => {
    let cancelled = false
    async function fetchHistory() {
      try {
        const result = await apiGet<{ projects: ProjectSummary[] }>('/api/v1/projects')
        if (!cancelled) setHistory(result.projects)
      } catch {
        // Silently fail
      }
    }
    void fetchHistory()
    return () => { cancelled = true }
  }, [])

  // A document with readable text is enough on its own: requiring typed text
  // as well would mean the attachment does not count as input.
  const hasReadableDocument = documents.some((d) => !d.error && d.charCount > 0)
  const canSubmit =
    title.trim().length > 0 && (text.trim().length >= 10 || hasReadableDocument)

  async function handleSubmit() {
    if (!canSubmit) return

    setLoading(true)
    try {
      const body = {
        title: title.trim(),
        text: text.trim(),
        document_ids: documents.map((d) => d.id),
        decision_objective: objective.trim(),
      } satisfies AnalyzeRequest

      // The switch chooses between two paths that both already existed, rather
      // than adding a mode to one of them. Turned off, this is byte-for-byte
      // the request the application made before the questions were built.
      if (!intakeEnabled) {
        const response = await apiPost<AnalyzeResponse>('/api/v1/analyze', body)
        navigate(`/analysis/${response.project_id}`)
        return
      }

      // Creates the project and returns at once — no model call, no pipeline.
      // The intake screen asks for the questions itself, which is what lets it
      // hold an id from the first frame and offer a working "start anyway"
      // while the model is still reading.
      const response = await apiPost<IntakeResponse>('/api/v1/intake', body)
      navigate(`/intake/${response.project_id}`)
    } catch (err) {
      const message = err instanceof Error ? err.message : t.errors.analysisFailed
      toast.error(message)
    } finally {
      setLoading(false)
    }
  }

  async function handleFileUpload(file: File) {
    setUploading(true)
    try {
      const formData = new FormData()
      formData.append('file', file)

      const res = await fetch('/api/v1/upload', {
        method: 'POST',
        body: formData,
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || `Upload failed: ${res.status}`)
      }

      const data: UploadResponse = await res.json()

      // Attach, do not paste. Dropping the whole document into the textarea
      // overwrote whatever the user had typed and made a long file unreadable;
      // the text stays on the server and is read when analysis starts.
      setDocuments((prev) => [
        ...prev,
        {
          id: data.document_id,
          filename: data.filename,
          charCount: data.char_count,
          sizeBytes: data.size_bytes,
          error: data.extraction_error,
        },
      ])
      if (!title.trim()) setTitle(data.title)

      if (data.extraction_error) {
        toast.warning(t.toasts.extractionFailed.replace('{name}', file.name))
      } else {
        toast.success(
          t.toasts.documentAttached
            .replace('{name}', file.name)
            .replace('{chars}', data.char_count.toLocaleString()),
        )
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : t.errors.uploadFailed
      toast.error(message)
    } finally {
      setUploading(false)
    }
  }

  function handleFileInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) handleFileUpload(file)
    e.target.value = '' // Reset so same file can be re-uploaded
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    e.stopPropagation()
    const file = e.dataTransfer.files?.[0]
    if (file) handleFileUpload(file)
  }

  function handleDragOver(e: React.DragEvent) {
    e.preventDefault()
    e.stopPropagation()
  }


  function handleDemoSelect(demoTitle: string, demoText: string) {
    setTitle(demoTitle)
    setText(demoText)
    setDocuments([])
    setObjective('')
  }


  return (
    <div className="max-w-3xl mx-auto px-4 py-12 sm:py-20">
      {/* Hero */}
      <div className="text-center mb-10">
        <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-ocean-500/10 border border-ocean-500/20 mb-4">
          <Cat className="w-8 h-8 text-ocean-400" />
        </div>
        <h1 className="text-3xl sm:text-4xl font-bold text-text-primary mb-2">
          {t.common.appName}
        </h1>
        <p className="text-text-secondary text-base italic">
          {t.common.tagline}
        </p>
        <p className="text-text-muted text-sm mt-1.5">
          {t.common.heroDescription}
        </p>
      </div>

      {/* Title input */}
      <div className="mb-3">
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={t.input.titlePlaceholder}
          className="
            w-full bg-surface-800 text-text-primary
            border border-surface-700 rounded-xl
            px-4 py-3 text-sm
            placeholder:text-text-muted
            focus:outline-none focus:border-ocean-500/50 focus:ring-1 focus:ring-ocean-500/25
            transition-colors
          "
        />
      </div>

      {/* The decision. Optional, because an analysis with no stated decision is
          still worth having — but everything after the graph reads this, so the
          field says what is lost by leaving it empty rather than silently
          producing a weaker result. */}
      <div className="mb-3">
        <input
          type="text"
          value={objective}
          onChange={(e) => setObjective(e.target.value)}
          placeholder={t.input.objectivePlaceholder}
          aria-label={t.input.objectiveLabel}
          className="
            w-full bg-surface-800 text-text-primary
            border border-surface-700 rounded-xl
            px-4 py-3 text-sm
            placeholder:text-text-muted
            focus:outline-none focus:border-ocean-500/50 focus:ring-1 focus:ring-ocean-500/25
            transition-colors
          "
        />
        <p className="mt-1.5 px-1 text-[11px] text-text-muted leading-relaxed">
          {objective.trim()
            ? t.input.objectiveHint
            : t.input.objectiveMissingHint}
        </p>
      </div>

      {/* Text input with drop zone */}
      <div
        className="mb-4"
        onDrop={handleDrop}
        onDragOver={handleDragOver}
      >
        <Textarea
          value={text}
          onChange={(e) => { setText(e.target.value); setDocuments([]) }}
          placeholder={t.input.textPlaceholder}
          rows={8}
          className="min-h-[200px]"
        />
        <div className="flex items-center justify-between mt-2">
          <span className="text-xs text-text-muted">
            {text.length} {t.input.charCount}
            {text.length > 0 && text.length < 10 && ` ${t.input.minChars}`}
          </span>

          {/* Attached documents. Several are allowed; each is analysed. */}
          {documents.length > 0 && (
            <div className="flex flex-wrap gap-1.5" data-testid="attached-documents">
              {documents.map((doc) => (
                <span
                  key={doc.id}
                  title={
                    doc.error
                      ? t.input.extractionFailedHint
                      : t.input.charsExtracted.replace(
                          '{chars}',
                          doc.charCount.toLocaleString(),
                        )
                  }
                  className={`flex items-center gap-1.5 text-xs px-2 py-1 rounded-md border ${
                    doc.error
                      ? 'text-amber-400 bg-amber-500/10 border-amber-500/30'
                      : 'text-ocean-400 bg-ocean-500/10 border-ocean-500/30'
                  }`}
                >
                  {doc.filename.match(/\.(png|jpg|jpeg|webp|gif)$/i) ? (
                    <Image className="w-3 h-3 shrink-0" />
                  ) : (
                    <FileText className="w-3 h-3 shrink-0" />
                  )}
                  {doc.filename}
                  <span className="text-text-muted">
                    {doc.error
                      ? t.input.notReadable
                      : `${(doc.charCount / 1000).toFixed(1)}k`}
                  </span>
                  <button
                    onClick={() =>
                      setDocuments((prev) => prev.filter((d) => d.id !== doc.id))
                    }
                    aria-label={t.common.close}
                    className="hover:text-text-primary"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex gap-3 mb-2">
        <Button
          onClick={handleSubmit}
          disabled={!canSubmit}
          loading={loading}
          size="lg"
          className="flex-1"
        >
          <Send className="w-4 h-4" />
          {t.input.analyze}
        </Button>

        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_FILE_TYPES}
          onChange={handleFileInputChange}
          className="hidden"
        />
        <Button
          variant="secondary"
          onClick={() => fileInputRef.current?.click()}
          loading={uploading}
          size="lg"
        >
          <Upload className="w-4 h-4" />
          {t.input.upload}
        </Button>
      </div>

      <div className="flex justify-center mb-3">
        <Toggle
          checked={intakeEnabled}
          onChange={setIntakeEnabled}
          label={t.input.intakeToggle}
          hint={intakeEnabled ? t.input.intakeToggleOn : t.input.intakeToggleOff}
        />
      </div>

      <p className="text-xs text-text-muted text-center mb-6">
        {t.input.supportedFormats}
      </p>

      {/* Demo scenarios */}
      <DemoScenarios onSelect={handleDemoSelect} />

      {/* History */}
      {history.length > 0 && (
        <div className="mt-8">
          <div className="flex items-center gap-2 mb-3">
            <Clock className="w-4 h-4 text-text-muted" />
            <h2 className="text-sm font-semibold text-text-secondary">{t.history.title}</h2>
          </div>
          <div className="space-y-2">
            {history.map((project) => (
              <button
                key={project.id}
                onClick={() => {
                  if (project.status === 'completed') {
                    navigate(`/graph/${project.id}`)
                  } else if (project.status === 'processing') {
                    navigate(`/analysis/${project.id}`)
                  }
                }}
                className="w-full text-left px-4 py-3 bg-surface-800 border border-surface-700 rounded-xl hover:border-surface-600 hover:bg-surface-800/80 transition-colors group"
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm text-text-primary group-hover:text-ocean-300 transition-colors truncate mr-3">
                    {project.title}
                  </span>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-xs text-text-muted">{timeAgo(project.created_at)}</span>
                    {project.status === 'completed' && (
                      <span className="flex items-center gap-1 text-xs text-confidence-high">
                        <CheckCircle2 className="w-3 h-3" />
                        {t.history.status.completed}
                      </span>
                    )}
                    {project.status === 'processing' && (
                      <span className="flex items-center gap-1 text-xs text-ocean-400">
                        <Loader2 className="w-3 h-3 animate-spin" />
                        {t.history.status.processing}
                      </span>
                    )}
                    {project.status === 'failed' && (
                      <span className="flex items-center gap-1 text-xs text-confidence-low">
                        <AlertCircle className="w-3 h-3" />
                        {t.history.status.failed}
                      </span>
                    )}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
