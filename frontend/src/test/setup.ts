import '@testing-library/jest-dom/vitest'
import { vi } from 'vitest'

// Toasts are side-effects, not assertions; stub them everywhere.
vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
}))
