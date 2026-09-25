import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import LinkDialog from '../LinkDialog.tsx'
import { LanguageProvider } from '../../../i18n/index.tsx'

/**
 * The mechanism requirement is the point of this dialog. A link without one is
 * a correlation with an arrow drawn on it, and the moment of drawing is the
 * cheapest place to catch that.
 */

function renderDialog(props: Partial<React.ComponentProps<typeof LinkDialog>> = {}) {
  const defaults: React.ComponentProps<typeof LinkDialog> = {
    sourceText: 'Contingency budget is exhausted',
    targetText: 'Vendor readiness is unconfirmed',
    saving: false,
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
  }
  const merged = { ...defaults, ...props }
  return {
    ...render(
      <LanguageProvider>
        <LinkDialog {...merged} />
      </LanguageProvider>,
    ),
    props: merged,
  }
}

describe('LinkDialog', () => {
  it('shows which claims are being connected', () => {
    renderDialog()
    expect(screen.getByText(/contingency budget is exhausted/i)).toBeInTheDocument()
    expect(screen.getByText(/vendor readiness is unconfirmed/i)).toBeInTheDocument()
  })

  it('cannot save without a mechanism', () => {
    renderDialog()
    expect(screen.getByRole('button', { name: /add the link/i })).toBeDisabled()
  })

  it('explains why the mechanism is required', () => {
    renderDialog()
    expect(
      screen.getByText(/if you cannot, the link may not be causal/i),
    ).toBeInTheDocument()
  })

  it('saves with the mechanism and the two scores', async () => {
    const onConfirm = vi.fn()
    renderDialog({ onConfirm })

    await userEvent.type(
      screen.getByLabelText(/how does the cause act/i),
      'No budget means no expediting fee',
    )
    await userEvent.click(screen.getByRole('button', { name: /add the link/i }))

    expect(onConfirm).toHaveBeenCalledWith('No budget means no expediting fee', 0.5, 0.5)
  })

  it('trims whitespace-only input rather than accepting it', async () => {
    const onConfirm = vi.fn()
    renderDialog({ onConfirm })
    await userEvent.type(screen.getByLabelText(/how does the cause act/i), '   ')
    expect(screen.getByRole('button', { name: /add the link/i })).toBeDisabled()
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('defaults both scores to the middle, not to confident', () => {
    /** A link just thought of has not been evidenced. */
    renderDialog()
    expect(screen.getAllByText('0.50').length).toBeGreaterThanOrEqual(2)
  })

  it('says evidence has not been searched yet', () => {
    renderDialog()
    expect(
      screen.getByText(/absence of evidence is not refutation/i),
    ).toBeInTheDocument()
  })

  it('can be cancelled', async () => {
    const onCancel = vi.fn()
    renderDialog({ onCancel })
    await userEvent.click(screen.getByRole('button', { name: /^cancel$/i }))
    expect(onCancel).toHaveBeenCalledOnce()
  })

  it('disables saving while in flight', async () => {
    renderDialog({ saving: true })
    await userEvent.type(screen.getByLabelText(/how does the cause act/i), 'because')
    expect(screen.getByRole('button', { name: /add the link/i })).toBeDisabled()
  })

  it('is a labelled modal dialog', () => {
    renderDialog()
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog).toHaveAccessibleName()
  })
})
