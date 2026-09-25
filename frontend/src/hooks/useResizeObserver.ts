import { useEffect, useRef, useState, type RefObject } from 'react'

export interface Size {
  width: number
  height: number
}

/**
 * The element's size, updated only when it meaningfully changes.
 *
 * Two guards, both there because of the same symptom: opening the graph made it
 * appear to load several times in the first second.
 *
 * The cause was that anything consuming this size re-ran on every observer
 * callback, and there are several in the first moments of a mount — the initial
 * measurement, the scrollbar appearing, web fonts landing, a panel settling.
 * Each one restarted the force simulation from alpha = 1, so the graph
 * re-animated from scratch three or four times.
 *
 * So: identical sizes produce no state update at all, and sub-pixel differences
 * are treated as identical. A layout that settles from 1184.4 to 1184.0 is not
 * a resize anyone asked to react to, and reacting to it costs a full re-layout.
 */

/** Below this, a change is layout noise rather than a resize. */
const MEANINGFUL_CHANGE_PX = 1

export function useResizeObserver(ref: RefObject<HTMLElement | null>): Size {
  const [size, setSize] = useState<Size>({ width: 0, height: 0 })
  // Read inside the observer callback without making it a dependency.
  const sizeRef = useRef<Size>(size)

  useEffect(() => {
    const el = ref.current
    if (!el) return

    const apply = (width: number, height: number) => {
      const current = sizeRef.current
      const settled =
        Math.abs(current.width - width) < MEANINGFUL_CHANGE_PX &&
        Math.abs(current.height - height) < MEANINGFUL_CHANGE_PX
      if (settled) return

      // Rounded, so a fractional layout cannot produce an endless trickle of
      // updates that each differ by a hair.
      const next = { width: Math.round(width), height: Math.round(height) }
      sizeRef.current = next
      setSize(next)
    }

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        apply(entry.contentRect.width, entry.contentRect.height)
      }
    })
    observer.observe(el)

    const rect = el.getBoundingClientRect()
    apply(rect.width, rect.height)

    return () => observer.disconnect()
  }, [ref])

  return size
}
