import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiClarificationQuestion, ApiTheory } from '../../../types/reasoning.ts'

// Stub the low-level client so these tests cover transformation, not fetch.
const apiGet = vi.fn()
const apiPost = vi.fn()
const apiPatch = vi.fn()

vi.mock('../client.ts', () => ({
  apiGet: (...args: unknown[]) => apiGet(...args),
  apiPost: (...args: unknown[]) => apiPost(...args),
  apiPatch: (...args: unknown[]) => apiPatch(...args),
}))

const {
  answerQuestion,
  applyAnswers,
  fetchQuestions,
  fetchTheories,
  generateTheories,
  regenerateTheories,
  reviewClaim,
  reviewEdge,
  transformQuestion,
  transformTheory,
} = await import('../reasoning.ts')

const apiTheory: ApiTheory = {
  id: 'theory-1',
  project_id: 'project-1',
  theory_key: 'key-1',
  title: 'Schedule exposure',
  summary: 'Vendor readiness is unconfirmed.',
  status: 'supported',
  causal_chain: [
    { claim_id: 'claim-1', label: 'Vendor readiness unconfirmed' },
    {
      edge_id: 'edge-1',
      source_claim_id: 'claim-1',
      target_claim_id: 'claim-2',
      label: 'delays integration',
    },
  ],
  supporting_claim_ids: ['claim-1', 'claim-2'],
  supporting_edge_ids: ['edge-1'],
  supporting_evidence_ids: ['evidence-1'],
  contradicting_evidence_ids: ['evidence-2'],
  weak_assumptions: ['Unconfirmed critical path'],
  confidence: 0.72,
  business_impact: 'high',
  recommendation: 'Confirm vendor readiness.',
  open_question_ids: ['question-1'],
  graph_revision: 3,
  theory_revision: 2,
  version: 2,
  is_current: true,
  is_stale: false,
  stale_reason: null,
  change_kind: 'changed',
  change_explanation: 'confidence fell',
  created_at: '2026-07-01T00:00:00Z',
}

const apiQuestion: ApiClarificationQuestion = {
  id: 'question-1',
  project_id: 'project-1',
  question: 'Is the date fixed?',
  reason: 'It determines schedule exposure.',
  expected_information_gain: 'high',
  priority: 'critical',
  answer_type: 'single_choice',
  options: ['Fixed', 'Extendable'],
  linked_theory_ids: ['theory-1'],
  linked_claim_ids: ['claim-1'],
  linked_edge_ids: ['edge-1'],
  status: 'open',
  answer: undefined,
  answer_note: null,
  graph_revision: 3,
  answered_at: null,
  applied_at: null,
  created_at: '2026-07-01T00:00:00Z',
}

beforeEach(() => {
  apiGet.mockReset()
  apiPost.mockReset()
  apiPatch.mockReset()
})

describe('transformTheory', () => {
  it('maps every wire field to its camelCase counterpart', () => {
    const theory = transformTheory(apiTheory)

    expect(theory.theoryKey).toBe('key-1')
    expect(theory.supportingClaimIds).toEqual(['claim-1', 'claim-2'])
    expect(theory.contradictingEvidenceIds).toEqual(['evidence-2'])
    expect(theory.businessImpact).toBe('high')
    expect(theory.graphRevision).toBe(3)
    expect(theory.changeKind).toBe('changed')
    expect(theory.changeExplanation).toBe('confidence fell')
  })

  it('maps the causal chain, preserving claim and edge steps', () => {
    const theory = transformTheory(apiTheory)

    expect(theory.causalChain).toHaveLength(2)
    expect(theory.causalChain[0]).toMatchObject({ claimId: 'claim-1' })
    expect(theory.causalChain[1]).toMatchObject({
      edgeId: 'edge-1',
      sourceClaimId: 'claim-1',
      targetClaimId: 'claim-2',
    })
  })

  it('tolerates missing array fields', () => {
    const sparse = { ...apiTheory } as Partial<ApiTheory>
    delete sparse.weak_assumptions
    delete sparse.causal_chain
    delete sparse.supporting_claim_ids

    const theory = transformTheory(sparse as ApiTheory)

    expect(theory.weakAssumptions).toEqual([])
    expect(theory.causalChain).toEqual([])
    expect(theory.supportingClaimIds).toEqual([])
  })
})

describe('transformQuestion', () => {
  it('maps every wire field', () => {
    const question = transformQuestion(apiQuestion)

    expect(question.expectedInformationGain).toBe('high')
    expect(question.answerType).toBe('single_choice')
    expect(question.options).toEqual(['Fixed', 'Extendable'])
    expect(question.linkedTheoryIds).toEqual(['theory-1'])
    expect(question.linkedEdgeIds).toEqual(['edge-1'])
  })

  it('normalizes absent options to null', () => {
    const question = transformQuestion({ ...apiQuestion, options: null })
    expect(question.options).toBeNull()
  })
})

describe('theory endpoints', () => {
  it('fetches and transforms the theory list', async () => {
    apiGet.mockResolvedValue({
      theories: [apiTheory],
      graph_revision: 3,
      stale_count: 1,
    })

    const result = await fetchTheories('project-1')

    expect(apiGet).toHaveBeenCalledWith('/api/v1/graph/project-1/theories')
    expect(result.theories[0].title).toBe('Schedule exposure')
    expect(result.staleCount).toBe(1)
  })

  it('posts to the generate endpoint', async () => {
    apiPost.mockResolvedValue({
      graph_revision: 3,
      theory_revision: 1,
      theories: [apiTheory],
      change_summary: {
        new_theory_ids: ['theory-1'],
        changed_theory_ids: [],
        unchanged_theory_ids: [],
        superseded_theory_ids: [],
      },
      validation: {},
    })

    const result = await generateTheories('project-1')

    expect(apiPost).toHaveBeenCalledWith(
      '/api/v1/graph/project-1/theories/generate',
      {},
    )
    expect(result.changeSummary.newTheoryIds).toEqual(['theory-1'])
  })

  it('posts to the regenerate endpoint', async () => {
    apiPost.mockResolvedValue({
      graph_revision: 4,
      theory_revision: 2,
      theories: [],
      change_summary: {
        new_theory_ids: [],
        changed_theory_ids: [],
        unchanged_theory_ids: [],
        superseded_theory_ids: ['old'],
      },
      validation: {},
    })

    const result = await regenerateTheories('project-1')

    expect(apiPost).toHaveBeenCalledWith(
      '/api/v1/graph/project-1/theories/regenerate',
      {},
    )
    expect(result.changeSummary.supersededTheoryIds).toEqual(['old'])
  })
})

describe('review endpoints', () => {
  const reviewResponse = {
    element: {
      id: 'claim-1',
      target_type: 'claim',
      review_status: 'rejected',
      is_active: false,
      user_note: 'Wrong',
      strength_override: null,
      reviewed_at: '2026-07-01T00:00:00Z',
    },
    operation: {
      id: 'op-1',
      operation_type: 'set_review_status',
      target_type: 'claim',
      claim_id: 'claim-1',
      edge_id: null,
      revision_before: 3,
      revision_after: 4,
      source: 'user',
      note: null,
      undone_at: null,
      created_at: '2026-07-01T00:00:00Z',
    },
    graph_revision: 4,
    stale_theory_count: 2,
  }

  it('reviews a claim and reports the new revision', async () => {
    apiPatch.mockResolvedValue(reviewResponse)

    const result = await reviewClaim('project-1', 'claim-1', {
      review_status: 'rejected',
    })

    expect(apiPatch).toHaveBeenCalledWith(
      '/api/v1/graph/project-1/claims/claim-1/review',
      { review_status: 'rejected' },
    )
    expect(result.element.isActive).toBe(false)
    expect(result.graphRevision).toBe(4)
    expect(result.staleTheoryCount).toBe(2)
  })

  it('reviews an edge with a strength override', async () => {
    apiPatch.mockResolvedValue({
      ...reviewResponse,
      element: {
        ...reviewResponse.element,
        id: 'edge-1',
        target_type: 'edge',
        review_status: 'accepted',
        is_active: true,
        strength_override: 0.25,
      },
    })

    const result = await reviewEdge('project-1', 'edge-1', {
      strength_override: 0.25,
    })

    expect(apiPatch).toHaveBeenCalledWith(
      '/api/v1/graph/project-1/edges/edge-1/review',
      { strength_override: 0.25 },
    )
    expect(result.element.strengthOverride).toBe(0.25)
  })
})

describe('clarification endpoints', () => {
  it('fetches and transforms questions', async () => {
    apiGet.mockResolvedValue({ questions: [apiQuestion], open_count: 1 })

    const result = await fetchQuestions('project-1')

    expect(result.questions[0].priority).toBe('critical')
    expect(result.openCount).toBe(1)
  })

  it('posts an answer with its note', async () => {
    apiPost.mockResolvedValue({
      question: { ...apiQuestion, status: 'answered', answer: 'Fixed' },
      affected_theory_ids: ['theory-1'],
    })

    const result = await answerQuestion('project-1', 'question-1', 'Fixed', 'Clause 7.2')

    expect(apiPost).toHaveBeenCalledWith(
      '/api/v1/graph/project-1/clarifications/question-1/answer',
      { value: 'Fixed', note: 'Clause 7.2' },
    )
    expect(result.question.status).toBe('answered')
    expect(result.affectedTheoryIds).toEqual(['theory-1'])
  })

  it('transforms proposed graph changes', async () => {
    apiPost.mockResolvedValue({
      applied_question_ids: ['question-1'],
      answered_count: 1,
      proposed_graph_changes: [
        {
          target_type: 'edge',
          target_id: 'edge-1',
          suggested_review_status: 'uncertain',
          rationale: 'The answer contradicts this link.',
          question_id: 'question-1',
        },
      ],
    })

    const result = await applyAnswers('project-1')

    expect(result.proposedGraphChanges[0]).toEqual({
      targetType: 'edge',
      targetId: 'edge-1',
      suggestedReviewStatus: 'uncertain',
      rationale: 'The answer contradicts this link.',
      questionId: 'question-1',
    })
  })
})
