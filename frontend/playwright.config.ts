import { randomBytes } from 'node:crypto'
import { defineConfig, devices } from '@playwright/test'

/**
 * End-to-end tests against the real backend and an isolated PostgreSQL database
 * (`logitrack_e2e`), rebuilt from migrations + labelled sample data on every run, so
 * tests never touch development data.
 *
 * Credentials for the throwaway admin are generated per run unless provided.
 */
process.env.E2E_USERNAME ??= 'e2e-admin'
process.env.E2E_PASSWORD ??= `E2e-${randomBytes(12).toString('base64url')}-1!`

const API_PORT = 8091
const WEB_PORT = 4190

export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1600, height: 1000 } } },
    { name: 'mobile', use: { ...devices['Pixel 7'] }, testIgnore: /workflow/ },
  ],
  webServer: [
    {
      command:
        `cd ../backend && uv run python -m app.cli reset-e2e --yes && ` +
        `uv run uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      env: { LOGITRACK_DATABASE_NAME: 'logitrack_e2e' },
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: 'npm run build && npx vite preview --strictPort',
      url: `http://localhost:${WEB_PORT}`,
      env: { LOGITRACK_API_URL: `http://127.0.0.1:${API_PORT}` },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
})
