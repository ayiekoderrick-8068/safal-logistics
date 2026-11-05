import { defineConfig, devices } from '@playwright/test'

/**
 * End-to-end tests against the real backend + PostgreSQL.
 * Requires E2E_USERNAME / E2E_PASSWORD for an active account (see README).
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://localhost:4190',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1600, height: 1000 } } },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
  webServer: [
    {
      command: 'cd ../backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8090',
      url: 'http://127.0.0.1:8090/api/health',
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      // Test the production bundle (served by `vite preview`, which proxies /api like dev).
      command: 'npm run build && npx vite preview --strictPort',
      url: 'http://localhost:4190',
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
})
