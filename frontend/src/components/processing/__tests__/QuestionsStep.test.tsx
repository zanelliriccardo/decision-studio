// DEAD-CODE-CANDIDATE DC-35 [test]: tests a dead component; failing. See docs/DEAD_CODE_REPORT.md
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import QuestionsStep from '../QuestionsStep.tsx'
import { LanguageProvider } from '../../../i18n/index.tsx'
import { makeFrame } from '../../../test/fixtures.ts'

/**
 * The two kinds of question are asked together but hold different things: intake
 * stops the pipeline, framing only stops theory generation. Conflating them in
 * the UI would leave the user unable to tell why the run is waiting.
 */

function renderStep(props: Partial<React.ComponentProps<typeof QuestionsStep>> = {}) {
  const defaults: React.ComponentProps<typeof QuestionsStep> = {
    intakeQuestions: [
      {
        id: 'q1',
        question: 'Which delay does "the delay" refer to?',
        reason: 'Changes whether these become one node or two.',
        answer_type: 'single_choice',
        options: ['The vendor delay', 'The engineering freeze'],
      },
    ],
    frame: makeFrame({
      isComplete: false,
      canGenerateTheories: false,
      missingRequired: ['decision'],
    }),
    submitting: false,
    onAnswerIntake: vi.fn().mockResolvedValue(true),
    onSkipIntake: vi.fn().mockResolvedValue(true),
    onSaveFrame: vi.fn(),
  }
  const merged = { ...defaults, ...props }
  return {
    ...render(
      <LanguageProvider>
        <QuestionsStep {...merged} />
      </LanguageProvider>,
    ),
    props: merged,
  }
}

describe('QuestionsStep', () => {
  it('does not offer to resume — the pipeline never stopped', () => {
    renderStep()
    expect(screen.queryByTestId('continue-analysis')).not.toBeInTheDocument()
  })

  it('says the analysis carries on regardless', () => {
    renderStep()
    expect(screen.getByText(/carries on either way/i)).toBeInTheDocument()
  })

  it('asks both kinds in one place', () => {
    renderStep()
    expect(screen.getByTestId('intake-questions')).toBeInTheDocument()
    expect(screen.getByTestId('framing-questions')).toBeInTheDocument()
  })


  it('records an intake answer', async () => {
    const onAnswerIntake = vi.fn().mockResolvedValue(true)
    renderStep({ onAnswerIntake })

    await userEvent.click(screen.getByRole('button', { name: 'The vendor delay' }))
    await userEvent.click(screen.getByRole('button', { name: /^answer$/i }))

    expect(onAnswerIntake).toHaveBeenCalledWith('q1', 'The vendor delay')
  })

  it('lets an unanswerable question be skipped', async () => {
    const onSkipIntake = vi.fn().mockResolvedValue(true)
    renderStep({ onSkipIntake })
    await userEvent.click(screen.getByRole('button', { name: /skip/i }))
    expect(onSkipIntake).toHaveBeenCalledWith('q1')
  })




})
