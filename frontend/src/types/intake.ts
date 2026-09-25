/** Questions asked about the material before the pipeline starts. */

export type IntakeKind = 'authority' | 'ambiguity' | 'scope' | 'absence' | 'frame'

export interface IntakeQuestion {
  id: string
  kind: IntakeKind
  question: string
  /** The sentence this is about, verbatim. Absent when unverifiable. */
  quoted_source: string | null
  /** What answering would change about the analysis. */
  rationale: string
  /** 0 to 3 readings. Free text is always available alongside. */
  options: string[]
  answer_choice: number | null
  answer_text: string | null
}

export interface IntakeResponse {
  project_id: string
  status: 'awaiting_questions' | 'ready'
}

export interface IntakeQuestionsResponse {
  project_id: string
  questions: IntakeQuestion[]
}

export interface IntakeAnswer {
  question_id: string
  text?: string
  choice?: number | null
}
