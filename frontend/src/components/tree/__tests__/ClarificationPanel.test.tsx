import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ClarificationPanel from '../ClarificationPanel.tsx'
import { LanguageProvider } from '../../../i18n/index.tsx'
import { makeQuestion, makeTheory } from '../../../test/fixtures.ts'

function renderPanel(
  props: Partial<React.ComponentProps<typeof ClarificationPanel>> = {},
) {
  const defaults: React.ComponentProps<typeof ClarificationPanel> = {
    questions: [],
    theories: [],
    loading: false,
    generating: false,
    error: null,
    onGenerate: vi.fn(),
    onAnswer: vi.fn(),
    onStatus: vi.fn(),
    onApply: vi.fn().mockResolvedValue(null),
    onApplyProposal: vi.fn(),
    onRegenerate: vi.fn(),
    onClose: vi.fn(),
  }
  const merged = { ...defaults, ...props }
  return {
    ...render(
      <LanguageProvider>
        <ClarificationPanel {...merged} />
      </LanguageProvider>,
    ),
    props: merged,
  }
}

describe('ClarificationPanel states', () => {
  it('shows a loading indicator', () => {
    renderPanel({ loading: true })
    expect(screen.getByTestId('questions-loading')).toBeInTheDocument()
  })

  it('shows an error with an alert role', () => {
    renderPanel({ error: 'Question generation failed' })
    expect(screen.getByRole('alert')).toHaveTextContent(/question generation failed/i)
  })

  it('shows an empty state', () => {
    renderPanel()
    expect(screen.getByTestId('questions-empty')).toBeInTheDocument()
  })

  it('triggers generation', async () => {
    const onGenerate = vi.fn()
    renderPanel({ onGenerate })
    await userEvent.click(screen.getByRole('button', { name: /ask what is missing/i }))
    expect(onGenerate).toHaveBeenCalledOnce()
  })
})

describe('ClarificationPanel question rendering', () => {
  it('shows the question, its reason and its priority', () => {
    renderPanel({ questions: [makeQuestion()] })
    expect(
      screen.getByText(/is the contractual delivery date fixed or extendable/i),
    ).toBeInTheDocument()
    expect(screen.getByText(/schedule exposure depends on whether/i)).toBeInTheDocument()
    expect(screen.getByTitle(/priority: high/i)).toBeInTheDocument()
  })

  it('shows which theories an answer would affect', () => {
    const theory = makeTheory()
    renderPanel({
      questions: [makeQuestion({ linkedTheoryIds: [theory.id] })],
      theories: [theory],
    })
    expect(screen.getByText(/would affect/i)).toBeInTheDocument()
    expect(screen.getByText(theory.title)).toBeInTheDocument()
  })

  it('groups questions by lifecycle state', () => {
    renderPanel({
      questions: [
        makeQuestion({ id: 'q1' }),
        makeQuestion({ id: 'q2', status: 'answered', answer: 'Fixed' }),
        makeQuestion({ id: 'q3', status: 'dismissed' }),
      ],
    })
    expect(screen.getByText(/^Open \(1\)$/)).toBeInTheDocument()
    expect(screen.getByText(/^Answered \(1\)$/)).toBeInTheDocument()
    expect(screen.getByText(/skipped and dismissed \(1\)/i)).toBeInTheDocument()
  })

  it('shows a saved answer', () => {
    renderPanel({
      questions: [
        makeQuestion({ status: 'answered', answer: 'Fixed', answerNote: 'Clause 7.2' }),
      ],
    })
    expect(screen.getByText('Fixed')).toBeInTheDocument()
    expect(screen.getByText('Clause 7.2')).toBeInTheDocument()
  })
})

describe('ClarificationPanel answer types', () => {
  it('renders single_choice as option buttons', async () => {
    const onAnswer = vi.fn()
    renderPanel({ questions: [makeQuestion()], onAnswer })

    await userEvent.click(screen.getByRole('button', { name: 'Extendable' }))

    expect(onAnswer).toHaveBeenCalledWith('question-1', 'Extendable', undefined)
  })

  it('renders yes_no as two buttons', async () => {
    const onAnswer = vi.fn()
    renderPanel({
      questions: [makeQuestion({ answerType: 'yes_no', options: null })],
      onAnswer,
    })

    await userEvent.click(screen.getByRole('button', { name: 'Yes' }))

    expect(onAnswer).toHaveBeenCalledWith('question-1', true, undefined)
  })

  it('renders multi_choice as checkboxes', async () => {
    const onAnswer = vi.fn()
    renderPanel({
      questions: [
        makeQuestion({ answerType: 'multi_choice', options: ['A', 'B', 'C'] }),
      ],
      onAnswer,
    })

    await userEvent.click(screen.getByRole('checkbox', { name: 'A' }))
    await userEvent.click(screen.getByRole('checkbox', { name: 'C' }))
    await userEvent.click(screen.getByRole('button', { name: /save answer/i }))

    expect(onAnswer).toHaveBeenCalledWith('question-1', ['A', 'C'], undefined)
  })

  it('renders free_text as a text field', async () => {
    const onAnswer = vi.fn()
    renderPanel({
      questions: [makeQuestion({ answerType: 'free_text', options: null })],
      onAnswer,
    })

    await userEvent.type(screen.getByLabelText(/contractual delivery date/i), 'It is fixed')
    await userEvent.click(screen.getByRole('button', { name: /save answer/i }))

    expect(onAnswer).toHaveBeenCalledWith('question-1', 'It is fixed', undefined)
  })

  it('renders number as a numeric field and submits a number', async () => {
    const onAnswer = vi.fn()
    renderPanel({
      questions: [
        makeQuestion({
          answerType: 'number',
          options: null,
          question: 'How many weeks of contingency remain?',
        }),
      ],
      onAnswer,
    })

    const input = screen.getByLabelText(/how many weeks/i)
    expect(input).toHaveAttribute('type', 'number')
    await userEvent.type(input, '6')
    await userEvent.click(screen.getByRole('button', { name: /save answer/i }))

    expect(onAnswer).toHaveBeenCalledWith('question-1', 6, undefined)
  })

  it('renders date as a date field', () => {
    renderPanel({
      questions: [
        makeQuestion({
          answerType: 'date',
          options: null,
          question: 'When does the freeze end?',
        }),
      ],
    })
    expect(screen.getByLabelText(/when does the freeze end/i)).toHaveAttribute(
      'type',
      'date',
    )
  })

  it('passes an optional note alongside the answer', async () => {
    const onAnswer = vi.fn()
    renderPanel({ questions: [makeQuestion()], onAnswer })

    await userEvent.type(screen.getByLabelText(/optional note/i), 'Per procurement')
    await userEvent.click(screen.getByRole('button', { name: 'Fixed' }))

    expect(onAnswer).toHaveBeenCalledWith('question-1', 'Fixed', 'Per procurement')
  })

  it('does not offer an answer input on a closed question', () => {
    renderPanel({ questions: [makeQuestion({ status: 'dismissed' })] })
    expect(screen.queryByRole('button', { name: 'Fixed' })).not.toBeInTheDocument()
  })
})

describe('ClarificationPanel lifecycle actions', () => {
  it('skips a question', async () => {
    const onStatus = vi.fn()
    renderPanel({ questions: [makeQuestion()], onStatus })
    await userEvent.click(screen.getByRole('button', { name: /skip/i }))
    expect(onStatus).toHaveBeenCalledWith('question-1', 'skipped')
  })

  it('dismisses a question', async () => {
    const onStatus = vi.fn()
    renderPanel({ questions: [makeQuestion()], onStatus })
    await userEvent.click(screen.getByRole('button', { name: /dismiss/i }))
    expect(onStatus).toHaveBeenCalledWith('question-1', 'dismissed')
  })

  it('reopens a dismissed question', async () => {
    const onStatus = vi.fn()
    renderPanel({ questions: [makeQuestion({ status: 'dismissed' })], onStatus })
    await userEvent.click(screen.getByRole('button', { name: /reopen/i }))
    expect(onStatus).toHaveBeenCalledWith('question-1', 'open')
  })
})

describe('ClarificationPanel apply flow', () => {
  const answered = makeQuestion({ status: 'answered', answer: 'Fixed' })

  it('does not regenerate automatically after an answer', () => {
    const onRegenerate = vi.fn()
    renderPanel({ questions: [answered], onRegenerate })
    // Regeneration is offered, never performed on the user's behalf.
    expect(screen.getByRole('button', { name: /regenerate theories/i })).toBeInTheDocument()
    expect(onRegenerate).not.toHaveBeenCalled()
  })

  it('explains that answers only take effect on regeneration', () => {
    renderPanel({ questions: [answered] })
    expect(
      screen.getByText(/answers are only used when you regenerate/i),
    ).toBeInTheDocument()
  })

  it('surfaces proposed graph changes without applying them', async () => {
    const onApply = vi.fn().mockResolvedValue({
      appliedQuestionIds: ['question-1'],
      answeredCount: 1,
      proposedGraphChanges: [
        {
          targetType: 'edge' as const,
          targetId: 'edge-1',
          suggestedReviewStatus: 'uncertain' as const,
          rationale: 'The answer contradicts this causal link.',
          questionId: 'question-1',
        },
      ],
    })
    const onApplyProposal = vi.fn()
    renderPanel({ questions: [answered], onApply, onApplyProposal })

    await userEvent.click(screen.getByRole('button', { name: /apply answers/i }))

    const proposals = await screen.findByTestId('graph-proposals')
    expect(within(proposals).getByText(/contradicts this causal link/i)).toBeInTheDocument()
    // Surfaced only — nothing applied until the user clicks.
    expect(onApplyProposal).not.toHaveBeenCalled()
  })

  it('applies a proposal only on an explicit click', async () => {
    const onApply = vi.fn().mockResolvedValue({
      appliedQuestionIds: [],
      answeredCount: 1,
      proposedGraphChanges: [
        {
          targetType: 'edge' as const,
          targetId: 'edge-1',
          suggestedReviewStatus: 'uncertain' as const,
          rationale: 'The answer contradicts this causal link.',
          questionId: 'question-1',
        },
      ],
    })
    const onApplyProposal = vi.fn()
    renderPanel({ questions: [answered], onApply, onApplyProposal })

    await userEvent.click(screen.getByRole('button', { name: /apply answers/i }))
    const proposals = await screen.findByTestId('graph-proposals')
    await userEvent.click(within(proposals).getByRole('button', { name: /mark uncertain/i }))

    expect(onApplyProposal).toHaveBeenCalledWith(
      expect.objectContaining({ targetId: 'edge-1', suggestedReviewStatus: 'uncertain' }),
    )
  })

  it('can ignore a proposal', async () => {
    const onApply = vi.fn().mockResolvedValue({
      appliedQuestionIds: [],
      answeredCount: 1,
      proposedGraphChanges: [
        {
          targetType: 'claim' as const,
          targetId: 'claim-1',
          suggestedReviewStatus: 'uncertain' as const,
          rationale: 'The answer contradicts this claim.',
          questionId: 'question-1',
        },
      ],
    })
    const onApplyProposal = vi.fn()
    renderPanel({ questions: [answered], onApply, onApplyProposal })

    await userEvent.click(screen.getByRole('button', { name: /apply answers/i }))
    const proposals = await screen.findByTestId('graph-proposals')
    await userEvent.click(within(proposals).getByRole('button', { name: /ignore/i }))

    expect(screen.queryByText(/contradicts this claim/i)).not.toBeInTheDocument()
    expect(onApplyProposal).not.toHaveBeenCalled()
  })
})

describe('ClarificationPanel accessibility', () => {
  it('conveys priority as text, not colour alone', () => {
    renderPanel({ questions: [makeQuestion({ priority: 'critical' })] })
    expect(screen.getByTitle(/priority: critical/i)).toHaveTextContent('Critical')
  })

  it('conveys expected information gain with a text label', () => {
    renderPanel({ questions: [makeQuestion({ expectedInformationGain: 'high' })] })
    expect(
      screen.getByTitle(/expected information gain: high/i),
    ).toBeInTheDocument()
  })

  it('marks question status on the card for assertions and styling', () => {
    renderPanel({ questions: [makeQuestion({ status: 'skipped' })] })
    expect(screen.getByTestId('question-card')).toHaveAttribute('data-status', 'skipped')
  })
})
