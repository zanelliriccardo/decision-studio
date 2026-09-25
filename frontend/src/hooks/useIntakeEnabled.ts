import { useCallback, useState } from 'react'

/**
 * Whether to ask questions before analysing, remembered per browser.
 *
 * Defaults to **on**, including when localStorage cannot be read at all. A
 * feature that silently disables itself in private browsing or under a strict
 * storage policy is one nobody can rely on, and the cost of being wrong in this
 * direction is a screen the user skips with one click.
 */

const STORAGE_KEY = 'decision_studio-intake'

function read(): boolean {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return stored === null ? true : stored === 'true'
  } catch {
    return true
  }
}

export function useIntakeEnabled() {
  const [enabled, setEnabledState] = useState(read)

  const setEnabled = useCallback((next: boolean) => {
    setEnabledState(next)
    try {
      localStorage.setItem(STORAGE_KEY, String(next))
    } catch {
      // Storage unavailable: the preference holds for this session only, which
      // is better than refusing to change it.
    }
  }, [])

  return { enabled, setEnabled }
}
