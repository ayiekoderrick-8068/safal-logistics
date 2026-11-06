import { expect, test, type Page } from '@playwright/test'

// Provided by playwright.config.ts (throwaway admin in the isolated e2e database).
const USERNAME = process.env.E2E_USERNAME
const PASSWORD = process.env.E2E_PASSWORD

async function signIn(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Username or email').fill(USERNAME!)
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD!)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Operations Overview' })).toBeVisible()
}

test('anonymous visitors are sent to sign in', async ({ page }) => {
  await page.goto('/dispatch')
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
})

test('wrong password shows an error', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Username or email').fill(USERNAME!)
  await page.getByLabel('Password', { exact: true }).fill('definitely-wrong-1!')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('alert')).toHaveText('The username or password is incorrect.')
})

test('repeated failures pause sign-in with a countdown (server-side rate limit)', async ({ page }, info) => {
  const probe = `lockout-probe-${info.project.name}`
  await page.goto('/login')
  for (let i = 0; i < 5; i++) {
    await page.getByLabel('Username or email').fill(probe)
    await page.getByLabel('Password', { exact: true }).fill(`wrong-${i}`)
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page.getByRole('alert')).toBeVisible()
  }
  await expect(page.getByRole('alert')).toContainText('Too many sign-in attempts')
  await expect(page.getByTestId('lockout-countdown')).toHaveText(/^1[45]:\d{2}$/)
  await expect(page.getByRole('button', { name: 'Sign-in paused' })).toBeDisabled()
})

test('overview loads KPIs from the API', async ({ page }) => {
  const overview = page.waitForResponse((r) => r.url().includes('/api/dashboard/overview') && r.ok())
  await signIn(page)
  const body = await (await overview).json()

  for (const label of ['Loads Processed', 'Avg Turnaround Time', 'On-Time Delivery', 'Delay Incidents', 'Bay Utilization']) {
    await expect(page.getByRole('article', { name: label })).toBeVisible()
  }
  // The rendered figure must be the one the API computed.
  await expect(page.getByRole('article', { name: 'Loads Processed' }).getByTestId('stat-value')).toHaveText(
    String(body.kpis.loads_processed.current),
  )
  await expect(page.getByTestId('sample-data-banner')).toHaveCount(body.sample_data ? 1 : 0)
  await expect(page.getByRole('heading', { name: 'Recent Dispatches' })).toBeVisible()

  await page.getByLabel('Reporting period').selectOption('30')
  await expect(page.getByText(/compared with/)).toBeVisible()
})

test('every sidebar module opens a real page, and sign-out works', async ({ page, isMobile }) => {
  await signIn(page)
  const openNav = async () => {
    if (isMobile) await page.getByRole('button', { name: 'Toggle navigation' }).click()
  }
  const modules: [string, string][] = [
    ['Fleet & Trucks', 'Fleet Management'],
    ['Loading Bays', 'Loading Bays & Scheduling'],
    ['Dispatch', 'Dispatch Management'],
    ['Turnaround Analytics', 'Turnaround-Time Analytics'],
    ['Compliance', 'Compliance Records'],
    ['Delay Reports', 'Delay Reports'],
    ['Reports', 'Reports & Export'],
  ]
  for (const [link, heading] of modules) {
    await openNav()
    await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: link, exact: true }).click()
    await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible()
  }

  await page.getByRole('button', { name: 'Account menu' }).click()
  await page.getByRole('menuitem', { name: 'Sign out' }).click()
  await expect(page).toHaveURL(/\/login$/)
  // Signed out, the home URL opens the workspace chooser.
  await page.goto('/')
  await expect(page).toHaveURL(/\/welcome$/)
})
