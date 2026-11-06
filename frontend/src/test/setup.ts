import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// findBy*/waitFor wait up to 5 s (default 1 s). Lazy-loaded pages and polling components
// can take longer than 1 s on slow or heavily loaded CI machines; this only extends how
// long a test waits for something that should appear, never what it asserts.
configure({ asyncUtilTimeout: 5000 })

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})
