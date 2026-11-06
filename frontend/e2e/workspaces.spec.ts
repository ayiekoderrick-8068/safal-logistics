import { expect, test, type Page } from '@playwright/test'

// Provided by playwright.config.ts (throwaway admin in the isolated e2e database).
// Administrators may enter both workspaces.
const USERNAME = process.env.E2E_USERNAME!
const PASSWORD = process.env.E2E_PASSWORD!

const status = (page: Page, path: string) => page.evaluate(async (p) => (await fetch(p)).status, path)

test('the home page offers both workspaces', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/welcome$/)
  await page.getByRole('link', { name: /Maintenance Operations/ }).click()
  await expect(page).toHaveURL(/\/maintenance\/login$/)
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Reliable equipment.')
})

test('a maintenance session cannot read logistics data, and switching needs the password', async ({ page }) => {
  await page.goto('/maintenance/login')
  await page.getByLabel('Username or email').fill(USERNAME)
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Maintenance Dashboard' })).toBeVisible()

  // Enforced by the API, not just the UI.
  expect(await status(page, '/api/maintenance/access')).toBe(200)
  expect(await status(page, '/api/dashboard/overview')).toBe(403)

  // A logistics URL asks for the password instead of showing the page.
  await page.goto('/fleet')
  await expect(page.getByRole('heading', { name: "Confirm it's you" })).toBeVisible()
  expect(await status(page, '/api/dashboard/overview')).toBe(403)
  // (Wrong-password and lockout behaviour is covered by the API tests; repeating it here would
  // count failures against the shared e2e account and could trip its sign-in lockout.)
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Open Logistics Operations' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Fleet Management' })).toBeVisible()
  expect(await status(page, '/api/dashboard/overview')).toBe(200)
  expect(await status(page, '/api/maintenance/access')).toBe(403) // the old workspace is closed
})
