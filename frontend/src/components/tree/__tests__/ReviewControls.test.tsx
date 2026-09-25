import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ReviewControls, { ReviewStatusBadge } from '../ReviewControls.tsx'
import { LanguageProvider } from '../../../i18n/index.tsx'
import type { ReviewStatus } from '../../../types/reasoning.ts'

function renderControls(
  props: Partial<React.ComponentProps<typeof ReviewControls>> = {},
) {
  const defaults: React.ComponentProps<typeof ReviewControls> = {
    targetType: 'claim',
    status: 'accepted',
    isActive: true,
    userNote: null,
    onReview: vi.fn(),
  }
  const merged = { ...defaults, ...props }
  return {
    ...render(
      <LanguageProvider>
        <ReviewControls {...merged} />
      </LanguageProvider>,
    ),
    onReview: merged.onReview as ReturnType<typeof vi.fn>,
  }
}

describe('ReviewControls status', () => {
  it('marks the current status as pressed', () => {
    renderControls({ status: 'uncertain' })
    expect(screen.getByRole('button', { name: /uncertain/i })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('applies a non-destructive status immediately', async () => {
    const { onReview } = renderControls()
    await userEvent.click(screen.getByRole('button', { name: /business critical/i }))
    expect(onReview).toHaveBeenCalledWith({ review_status: 'business_critical' })
  })

  it('marks a claim as needing evidence', async () => {
    const { onReview } = renderControls()
    await userEvent.click(screen.getByRole('button', { name: /needs evidence/i }))
    expect(onReview).toHaveBeenCalledWith({ review_status: 'needs_evidence' })
  })
})

describe('ReviewControls destructive confirmation', () => {
  it('asks for confirmation before rejecting', async () => {
    const { onReview } = renderControls()

    await userEvent.click(screen.getByRole('button', { name: /^reject/i }))

    expect(screen.getByText(/removes this from every future theory/i)).toBeInTheDocument()
    expect(onReview).not.toHaveBeenCalled()
  })

  it('rejects once confirmed', async () => {
    const { onReview } = renderControls()

    await userEvent.click(screen.getByRole('button', { name: /^reject/i }))
    await userEvent.click(screen.getByRole('button', { name: /yes, reject it/i }))

    expect(onReview).toHaveBeenCalledWith({ review_status: 'rejected' })
  })

  it('can back out of a rejection', async () => {
    const { onReview } = renderControls()

    await userEvent.click(screen.getByRole('button', { name: /^reject/i }))
    await userEvent.click(screen.getByRole('button', { name: /^cancel$/i }))

    expect(onReview).not.toHaveBeenCalled()
    expect(
      screen.queryByText(/removes this from every future theory/i),
    ).not.toBeInTheDocument()
  })
})

describe('ReviewControls activation', () => {
  it('disables an active element', async () => {
    const { onReview } = renderControls({ isActive: true })
    await userEvent.click(screen.getByRole('button', { name: /disable/i }))
    expect(onReview).toHaveBeenCalledWith({ is_active: false })
  })

  it('restores an inactive element', async () => {
    const { onReview } = renderControls({ isActive: false })
    await userEvent.click(screen.getByRole('button', { name: /restore/i }))
    expect(onReview).toHaveBeenCalledWith({ is_active: true })
  })

  it('explains what inactive means', () => {
    renderControls({ isActive: false })
    expect(screen.getByText(/kept in the graph, ignored by theories/i)).toBeInTheDocument()
  })
})

describe('ReviewControls notes', () => {
  it('saves a note', async () => {
    const { onReview } = renderControls()

    await userEvent.type(screen.getByLabelText(/your note/i), 'Confirmed with procurement')
    await userEvent.click(screen.getByRole('button', { name: /save note/i }))

    expect(onReview).toHaveBeenCalledWith({ user_note: 'Confirmed with procurement' })
  })

  it('only offers to save once the note is edited', () => {
    renderControls({ userNote: 'Existing note' })
    expect(screen.queryByRole('button', { name: /save note/i })).not.toBeInTheDocument()
  })
})

describe('ReviewControls strength override', () => {
  it('is not offered on claims', () => {
    renderControls({ targetType: 'claim' })
    expect(screen.queryByText(/override causal strength/i)).not.toBeInTheDocument()
  })

  it('is offered on edges', () => {
    renderControls({ targetType: 'edge', aiStrength: 0.8 })
    expect(screen.getByText(/override causal strength/i)).toBeInTheDocument()
    expect(screen.getByText(/ai estimate: 0.80/i)).toBeInTheDocument()
  })

  it('flags an overridden edge', () => {
    renderControls({ targetType: 'edge', aiStrength: 0.8, strengthOverride: 0.2 })
    expect(screen.getByText(/overridden/i)).toBeInTheDocument()
  })

  it('can clear an override', async () => {
    const { onReview } = renderControls({
      targetType: 'edge',
      aiStrength: 0.8,
      strengthOverride: 0.2,
    })

    await userEvent.click(screen.getByRole('button', { name: /clear override/i }))

    expect(onReview).toHaveBeenCalledWith({ clear_strength_override: true })
  })
})

describe('ReviewControls staleness warning', () => {
  it('warns that editing invalidates current theories', () => {
    renderControls({ hasTheories: true })
    expect(screen.getByText(/mark current theories stale/i)).toBeInTheDocument()
  })

  it('stays quiet when there is nothing to invalidate', () => {
    renderControls({ hasTheories: false })
    expect(screen.queryByText(/mark current theories stale/i)).not.toBeInTheDocument()
  })
})

describe('ReviewControls busy state', () => {
  it('disables the controls while a review is in flight', () => {
    renderControls({ busy: true })
    expect(screen.getByRole('button', { name: /disable/i })).toBeDisabled()
  })
})

describe('ReviewStatusBadge accessibility', () => {
  const statuses: ReviewStatus[] = [
    'accepted',
    'rejected',
    'uncertain',
    'business_critical',
    'not_relevant',
    'needs_evidence',
  ]

  it.each(statuses)('renders %s with a text label, not colour alone', (status) => {
    render(
      <LanguageProvider>
        <ReviewStatusBadge status={status} />
      </LanguageProvider>,
    )
    // Every status has a human-readable label and a title attribute.
    expect(screen.getByTitle(/.+/)).toHaveTextContent(/\w/)
  })

  it('signals inactive state separately from status', () => {
    const { container } = render(
      <LanguageProvider>
        <ReviewStatusBadge status="uncertain" isActive={false} />
      </LanguageProvider>,
    )
    // Two icons: the status glyph plus the excluded-from-reasoning marker.
    expect(container.querySelectorAll('svg')).toHaveLength(2)
  })
})
