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
  await expect(page.getByRole('alert')).toHaveText('Invalid username or password')
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
  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)
})
