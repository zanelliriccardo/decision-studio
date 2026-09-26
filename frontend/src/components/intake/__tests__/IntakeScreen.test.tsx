import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import IntakeScreen from '../IntakeScreen.tsx'
import { LanguageProvider } from '../../../i18n/index.tsx'
import { AnalysisProvider } from '../../../context/AnalysisContext.tsx'
import * as client from '../../../lib/api/client.ts'
import type { IntakeQuestion } from '../../../types/intake.ts'

const navigate = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  )
  return { ...actual, useNavigate: () => navigate }
})

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

function makeQuestion(overrides: Partial<IntakeQuestion> = {}): IntakeQuestion {
  return {
    id: 'q1',
    kind: 'ambiguity',
    question: 'Which team is meant here?',
    quoted_source: null,
    rationale: 'Three of eight is an event; three of thirty is noise.',
    options: ['Platform team', 'Product team', 'All of engineering'],
    answer_choice: null,
    answer_text: null,
    ...overrides,
  }
}

function renderScreen() {
  return render(
    <LanguageProvider>
      <AnalysisProvider>
        <MemoryRouter initialEntries={['/intake/p1']}>
          <Routes>
            <Route path="/intake/:projectId" element={<IntakeScreen />} />
          </Routes>
        </MemoryRouter>
      </AnalysisProvider>
    </LanguageProvider>,
  )
}

/** GET returns nothing stored; POST /questions returns `questions`. */
function stubApi(questions: IntakeQuestion[]) {
  const post = vi.spyOn(client, 'apiPost').mockImplementation(async (path) => {
    if (path.endsWith('/questions')) {
      return { project_id: 'p1', status: 'intake', questions } as never
    }
    return {
      project_id: 'p1',
      status: 'processing',
      answered: 0,
      context_chars: 0,
    } as never
  })
  const get = vi.spyOn(client, 'apiGet').mockResolvedValue({
    project_id: 'p1',
    status: 'intake',
    questions: [],
  } as never)
  return { post, get }
}

type SpiedPost = { mock: { calls: unknown[][] } }

function startCall(post: SpiedPost) {
  return post.mock.calls.find((call) => String(call[0]).endsWith('/start'))
}

beforeEach(() => {
  vi.restoreAllMocks()
  navigate.mockClear()
})

describe('IntakeScreen', () => {
  it('shows the questions once the material has been read', async () => {
    stubApi([makeQuestion()])
    renderScreen()

    expect(await screen.findByText('Which team is meant here?')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Platform team' })).toBeInTheDocument()
  })

  it('starts straight away when there is nothing to ask', async () => {
    // The common case on clear material. Showing an empty screen the user has
    // to dismiss would make silence feel like a failure.
    const { post } = stubApi([])
    renderScreen()

    await waitFor(() => expect(startCall(post)).toBeTruthy())
    expect(startCall(post)?.[1]).toEqual({ answers: [] })
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/analysis/p1'))
  })

  it('offers a working escape hatch while the model is still reading', async () => {
    // The property the three removed question systems never had. The project id
    // exists before any model call, so this button starts a run rather than
    // waiting for one.
    let release: (value: unknown) => void = () => {}
    const post = vi.spyOn(client, 'apiPost').mockImplementation(async (path) => {
      if (path.endsWith('/questions')) {
        return new Promise((resolve) => {
          release = resolve
        }) as never
      }
      return { project_id: 'p1', status: 'processing' } as never
    })
    vi.spyOn(client, 'apiGet').mockResolvedValue({
      project_id: 'p1',
      status: 'intake',
      questions: [],
    } as never)

    renderScreen()
    await userEvent.click(await screen.findByRole('button', { name: /start the analysis/i }))

    await waitFor(() => expect(startCall(post)).toBeTruthy())
    expect(startCall(post)?.[1]).toEqual({ answers: [] })

    // The questions land late. They must not drag the user back.
    release({ project_id: 'p1', status: 'intake', questions: [makeQuestion()] })
    await waitFor(() =>
      expect(screen.queryByText('Which team is meant here?')).not.toBeInTheDocument(),
    )
  })

  it('sends a selected option as a choice', async () => {
    const { post } = stubApi([makeQuestion()])
    renderScreen()

    await userEvent.click(await screen.findByRole('button', { name: 'Product team' }))
    await userEvent.click(screen.getByRole('button', { name: /start (the analysis|with these answers)/i }))

    await waitFor(() => expect(startCall(post)).toBeTruthy())
    expect(startCall(post)?.[1]).toEqual({
      answers: [{ question_id: 'q1', choice: 1 }],
    })
  })

  it('lets free text override a selected option', async () => {
    const { post } = stubApi([makeQuestion()])
    renderScreen()

    await userEvent.click(await screen.findByRole('button', { name: 'Platform team' }))
    await userEvent.type(screen.getByPlaceholderText(/or write your own/i), 'The data team')
    await userEvent.click(screen.getByRole('button', { name: /start (the analysis|with these answers)/i }))

    await waitFor(() => expect(startCall(post)).toBeTruthy())
    expect(startCall(post)?.[1]).toEqual({
      answers: [{ question_id: 'q1', text: 'The data team' }],
    })
    // Typing clears the selection rather than sending both.
    expect(screen.getByRole('button', { name: 'Platform team' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
  })

  it('clears a choice when the selected option is clicked again', async () => {
    // Without this the only way out of a mis-click is to type over it, and an
    // answer nobody meant to give is repeated on every inference prompt.
    const { post } = stubApi([makeQuestion()])
    renderScreen()

    const option = await screen.findByRole('button', { name: 'Platform team' })
    await userEvent.click(option)
    await userEvent.click(option)
    await userEvent.click(screen.getByRole('button', { name: /start (the analysis|with these answers)/i }))

    await waitFor(() => expect(startCall(post)).toBeTruthy())
    expect(startCall(post)?.[1]).toEqual({ answers: [] })
  })

  it('omits unanswered questions entirely', async () => {
    const { post } = stubApi([
      makeQuestion(),
      makeQuestion({ id: 'q2', question: 'Who signs this off?', options: [] }),
    ])
    renderScreen()

    await userEvent.click(await screen.findByRole('button', { name: 'Platform team' }))
    await userEvent.click(screen.getByRole('button', { name: /start (the analysis|with these answers)/i }))

    await waitFor(() => expect(startCall(post)).toBeTruthy())
    expect(startCall(post)?.[1]).toEqual({
      answers: [{ question_id: 'q1', choice: 0 }],
    })
  })

  it('never blocks the start on the answers', async () => {
    const { post } = stubApi([makeQuestion()])
    renderScreen()

    // Wait for the questions: the reading screen has a start button of the
    // same name, and grabbing that one races its replacement.
    await screen.findByText('Which team is meant here?')
    const start = screen.getByRole('button', { name: /start (the analysis|with these answers)/i })
    expect(start).not.toBeDisabled()

    await userEvent.click(start)
    await waitFor(() => expect(startCall(post)).toBeTruthy())
    expect(startCall(post)?.[1]).toEqual({ answers: [] })
  })

  it('renders a question that has no options with a free-text field', async () => {
    stubApi([makeQuestion({ options: [] })])
    renderScreen()

    expect(await screen.findByLabelText(/your answer/i)).toBeInTheDocument()
    expect(screen.queryByRole('group')).not.toBeInTheDocument()
  })

  it('shows the quoted sentence when the question is about one', async () => {
    stubApi([
      makeQuestion({ quoted_source: 'The platform team lost three people in Q2.' }),
    ])
    renderScreen()

    expect(
      await screen.findByText('The platform team lost three people in Q2.'),
    ).toBeInTheDocument()
  })

  it('reuses stored questions instead of paying for a second read', async () => {
    const post = vi.spyOn(client, 'apiPost').mockResolvedValue({} as never)
    vi.spyOn(client, 'apiGet').mockResolvedValue({
      project_id: 'p1',
      status: 'intake',
      questions: [makeQuestion()],
    } as never)

    renderScreen()
    await screen.findByText('Which team is meant here?')

    expect(
      post.mock.calls.filter(([path]) => String(path).endsWith('/questions')),
    ).toHaveLength(0)
  })

  it('starts the analysis when the questions cannot be generated', async () => {
    // This step improves a run that can proceed without it. Stranding the user
    // on a broken question screen would invert what it is for.
    const post = vi.spyOn(client, 'apiPost').mockImplementation(async (path) => {
      if (path.endsWith('/questions')) throw new Error('provider timeout')
      return { project_id: 'p1', status: 'processing' } as never
    })
    vi.spyOn(client, 'apiGet').mockResolvedValue({
      project_id: 'p1',
      status: 'intake',
      questions: [],
    } as never)

    renderScreen()

    await waitFor(() => expect(startCall(post)).toBeTruthy())
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/analysis/p1'))
  })
})
