import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderHook, act } from '@testing-library/react'
import Toggle from '../../ui/Toggle.tsx'
import { useIntakeEnabled } from '../../../hooks/useIntakeEnabled.ts'

/**
 * The preference defaults to on, including when storage cannot be read.
 *
 * A feature that silently disables itself in private browsing or under a strict
 * storage policy is one nobody can rely on, and the cost of being wrong in this
 * direction is a screen the user skips with one click.
 */

describe('useIntakeEnabled', () => {
  beforeEach(() => localStorage.clear())

  it('defaults to on', () => {
    const { result } = renderHook(() => useIntakeEnabled())
    expect(result.current.enabled).toBe(true)
  })

  it('remembers being turned off', () => {
    const { result } = renderHook(() => useIntakeEnabled())
    act(() => result.current.setEnabled(false))
    expect(result.current.enabled).toBe(false)

    const { result: reopened } = renderHook(() => useIntakeEnabled())
    expect(reopened.current.enabled).toBe(false)
  })

  it('defaults to on when storage cannot be read', () => {
    const original = Storage.prototype.getItem
    Storage.prototype.getItem = () => {
      throw new Error('denied')
    }
    try {
      const { result } = renderHook(() => useIntakeEnabled())
      expect(result.current.enabled).toBe(true)
    } finally {
      Storage.prototype.getItem = original
    }
  })

  it('still changes for this session when storage cannot be written', () => {
    const original = Storage.prototype.setItem
    Storage.prototype.setItem = () => {
      throw new Error('quota')
    }
    try {
      const { result } = renderHook(() => useIntakeEnabled())
      act(() => result.current.setEnabled(false))
      expect(result.current.enabled).toBe(false)
    } finally {
      Storage.prototype.setItem = original
    }
  })
})

describe('Toggle', () => {
  it('is a switch, not a checkbox', () => {
    /** Assistive technology announces "on"/"off" rather than "checked", which
        is what this actually means. */
    render(<Toggle checked onChange={vi.fn()} label="Ask first" />)
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true')
  })

  it('toggles', async () => {
    const onChange = vi.fn()
    render(<Toggle checked={false} onChange={onChange} label="Ask first" />)
    await userEvent.click(screen.getByRole('switch'))
    expect(onChange).toHaveBeenCalledWith(true)
  })

  it('shows the hint alongside the label', () => {
    render(<Toggle checked onChange={vi.fn()} label="Ask first" hint="Takes a few seconds" />)
    expect(screen.getByText('Takes a few seconds')).toBeInTheDocument()
  })

  it('does not fire when disabled', async () => {
    const onChange = vi.fn()
    render(<Toggle checked onChange={onChange} label="Ask first" disabled />)
    await userEvent.click(screen.getByRole('switch'))
    expect(onChange).not.toHaveBeenCalled()
  })
})
