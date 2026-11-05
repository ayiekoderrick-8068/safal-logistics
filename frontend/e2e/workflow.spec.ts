import { expect, test, type Page } from '@playwright/test'

/**
 * The core operational workflow, driven entirely through the UI:
 * register truck -> schedule loading -> arrival / loading start / loading finish
 * -> dispatch -> delivery -> turnaround recorded.
 */
const REG = 'KZE 123X'
const DRIVER = 'Grace Wanjiru'
const BAY = 'Bay E2E'

async function signIn(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Username or email').fill(process.env.E2E_USERNAME!)
  await page.getByLabel('Password', { exact: true }).fill(process.env.E2E_PASSWORD!)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Operations Overview' })).toBeVisible()
}

async function submitDialog(page: Page, button: string) {
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: button }).click()
  await expect(dialog).toBeHidden()
}

test('truck registration through delivery records turnaround', async ({ page }) => {
  await signIn(page)

  // 1. Register a driver and a truck
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'Fleet & Trucks' }).click()
  await page.getByRole('button', { name: 'Add Driver' }).click()
  await page.getByLabel('Full name').fill(DRIVER)
  await page.getByLabel('Licence number').fill('DL-E2E-001')
  await submitDialog(page, 'Save driver')

  await page.getByRole('button', { name: 'Add Truck' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'Register truck' }).click()
  await expect(dialog.getByText('Enter the registration number')).toBeVisible() // client validation
  await page.getByLabel('Registration number').fill(REG.toLowerCase())
  await page.getByLabel('Make (optional)').fill('Isuzu')
  await page.getByLabel('Capacity (tonnes)').fill('12')
  await page.getByLabel('Assigned driver').selectOption({ label: DRIVER })
  await submitDialog(page, 'Register truck')
  await expect(page.getByRole('status').filter({ hasText: `${REG} registered` })).toBeVisible()

  await page.getByRole('searchbox', { name: 'Search trucks' }).fill('KZE')
  await expect(page.getByRole('row', { name: new RegExp(REG) })).toContainText('Available')

  // 2. Create a dedicated bay, then book it from the truck panel
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'Loading Bays' }).click()
  await page.getByRole('button', { name: 'Add Bay' }).click()
  await page.getByLabel('Code', { exact: true }).fill('BAY-E2E')
  await page.getByLabel('Name', { exact: true }).fill(BAY)
  await submitDialog(page, 'Add bay')

  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'Fleet & Trucks' }).click()
  await page.getByRole('searchbox', { name: 'Search trucks' }).fill('KZE')
  await page.getByRole('button', { name: REG }).click()
  await page.getByRole('button', { name: 'Schedule Loading' }).click()
  await expect(page).toHaveURL(/loading-bays\?truck=/)
  await expect(page.getByLabel('Truck', { exact: true })).toHaveValue(/\d+/)
  await page.getByLabel('Loading bay').selectOption({ label: `${BAY} (target 120 min)` })
  await submitDialog(page, 'Book bay')

  // 3. Record arrival, loading start and loading finish
  await page.getByLabel('Filter by bay').selectOption({ label: BAY })
  const row = page.getByRole('row', { name: new RegExp(REG) })
  for (const action of ['Record arrival', 'Start loading', 'Finish loading']) {
    await row.getByRole('button', { name: action }).click()
    await submitDialog(page, action)
  }
  await expect(row).toContainText('Loaded')

  // 4. Dispatch is blocked: the new truck has no mandatory compliance documents yet
  await row.getByRole('button', { name: 'Dispatch' }).click()
  await expect(page).toHaveURL(/dispatch\?schedule=/)
  const dlg = page.getByRole('dialog')
  await expect(dlg.getByText(`${REG} cannot be dispatched`)).toBeVisible()
  await expect(dlg.getByText('Insurance is missing.')).toBeVisible()
  await page.getByLabel('Route', { exact: true }).selectOption({ index: 1 })
  await dlg.getByRole('button', { name: 'Dispatch truck' }).click()
  await expect(dlg.getByText(`Dispatch blocked for ${REG}`, { exact: false })).toBeVisible() // server-side gate

  // 5. Record the mandatory documents in Compliance Records (one with a supporting PDF)
  await dlg.getByRole('link', { name: 'Open compliance documents' }).click()
  await expect(page).toHaveURL(/compliance\?truck=/)
  const docs = ['Insurance', 'Vehicle licence', 'Inspection certificate']
  for (const [i, label] of docs.entries()) {
    await page.getByRole('dialog').getByRole('row', { name: new RegExp(`^${label}`) })
      .getByRole('button', { name: 'Add' }).click()
    await page.getByLabel('Document reference').fill(`E2E-${i}`)
    await page.getByLabel('Expiry date').fill('2030-01-01')
    if (i === 0) {
      await page.getByLabel('Supporting document (optional)').setInputFiles({
        name: 'policy.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\n%%EOF\n'),
      })
    }
    await page.getByRole('dialog').getByRole('button', { name: 'Save record' }).click()
    await expect(page.getByRole('status').filter({ hasText: `${label} added` })).toBeVisible()
  }
  await expect(page.getByRole('dialog').getByText('Eligible for dispatch')).toBeVisible()
  await expect(page.getByRole('dialog').getByRole('link', { name: 'Download policy.pdf' })).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: 'Close dialog' }).click()

  // 6. Dispatch now succeeds
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'Dispatch' }).click()
  await page.getByRole('button', { name: 'New Dispatch' }).click()
  const load = page.getByLabel('Loaded truck')
  await load.selectOption(await load.locator('option', { hasText: REG }).getAttribute('value') ?? '')
  await page.getByLabel('Route', { exact: true }).selectOption({ index: 1 })
  await expect(page.getByRole('dialog').getByText('Turnaround', { exact: true })).toBeVisible() // live preview
  await expect(page.getByRole('dialog').getByText('cannot be dispatched')).toHaveCount(0)
  await submitDialog(page, 'Dispatch truck')
  await expect(page.getByRole('status').filter({ hasText: `${REG} dispatched` })).toBeVisible()

  // 7. Deliver
  const dispatchRow = page.getByRole('row', { name: new RegExp(REG) })
  await expect(dispatchRow).toContainText('In Transit')
  await dispatchRow.getByRole('button', { name: 'Delivered' }).click()
  await expect(page.getByRole('dialog').getByText('On time.')).toBeVisible()
  await submitDialog(page, 'Confirm delivery')

  // 8. Turnaround recorded; truck is free again
  await expect(dispatchRow).toContainText('Delivered')
  await expect(dispatchRow.getByRole('cell').nth(6)).toHaveText(/^\d+ min$/)

  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'Fleet & Trucks' }).click()
  await page.getByRole('searchbox', { name: 'Search trucks' }).fill('KZE')
  await expect(page.getByRole('row', { name: new RegExp(REG) })).toContainText('Available')
  await expect(page.getByRole('row', { name: new RegExp(REG) })).toContainText('Nairobi →')
})

test('a delay can be reported, assigned and resolved with accurate timing', async ({ page }) => {
  await signIn(page)
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'Delay Reports' }).click()
  await page.getByRole('button', { name: 'Report Delay' }).click()
  const dlg = page.getByRole('dialog')
  await dlg.getByLabel('Dispatch / delivery').check()
  await dlg.getByLabel('Dispatch', { exact: true }).selectOption({ index: 1 })
  await dlg.getByLabel('Delay category').selectOption('vehicle_breakdown')
  await dlg.getByLabel('Estimated impact (minutes)').fill('30')
  await dlg.getByLabel('Responsible staff member (optional)').selectOption({ index: 1 })
  await dlg.getByLabel('Description').fill('E2E: tyre puncture on the highway')
  await dlg.getByRole('button', { name: 'Report delay' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Delay reported' })).toBeVisible()

  await page.getByRole('searchbox', { name: 'Search delays' }).fill('E2E: tyre')
  const row = page.getByRole('row', { name: /Vehicle breakdown/ })
  await expect(row).toContainText('Open')
  await expect(row).toContainText('E2E Admin')
  await expect(row).toContainText('Ongoing')
  await row.getByRole('button', { name: /Update delay/ }).click()
  await page.getByRole('dialog').getByLabel('Status', { exact: true }).selectOption('resolved')
  await page.getByRole('dialog').getByLabel('Resolution notes').fill('Spare fitted, truck continued')
  await submitDialog(page, 'Save changes')
  await expect(row).toContainText('Resolved')
  await expect(row).not.toContainText('Ongoing')
})

test('double-booking a bay is rejected with a clear message', async ({ page }) => {
  await signIn(page)
  await page.goto('/loading-bays')
  for (const attempt of [1, 2]) {
    await page.getByRole('button', { name: 'Schedule Loading' }).click()
    await page.getByLabel('Truck', { exact: true }).selectOption({ index: attempt })
    await page.getByLabel('Loading bay').selectOption({ label: `${BAY} (target 120 min)` })
    await page.getByLabel('Start', { exact: true }).fill('2030-01-15T10:00')
    await page.getByRole('dialog').getByRole('button', { name: 'Book bay' }).click()
    if (attempt === 1) await expect(page.getByRole('dialog')).toBeHidden()
  }
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText(`${BAY} is already booked`)
})
