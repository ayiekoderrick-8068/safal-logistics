import { expect, test, type Page } from '@playwright/test'

// Runs against the isolated e2e database (reset per run). Each browser project uses its own
// Equipment IDs because the projects run in parallel against the same database.
const USERNAME = process.env.E2E_USERNAME!
const PASSWORD = process.env.E2E_PASSWORD!
const SHOTS = process.env.SHOTS_DIR // optional: save screenshots for review

async function signInMaintenance(page: Page) {
  await page.goto('/maintenance/login')
  await page.getByLabel('Username or email').fill(USERNAME)
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Maintenance Dashboard' })).toBeVisible()
}

function isoDaysFromToday(days: number) {
  const d = new Date(Date.now() + days * 86_400_000)
  return d.toISOString().slice(0, 10)
}

test('register, edit, archive and restore equipment with a recorded history', async ({ page }, info) => {
  const p = info.project.name.slice(0, 3).toUpperCase() // DES / TAB / MOB
  await signInMaintenance(page)

  // A few assets through the API (same session cookie) so the register has realistic variety.
  const seed = [
    { code: `${p}-CNV-001`, name: 'Line 1 conveyor drive', category: 'conveyor', facility: 'Nairobi Plant',
      location: 'Line 1', status: 'operational', next_service_on: isoDaysFromToday(-3) },
    { code: `${p}-PMP-004`, name: 'Cooling water pump', category: 'pump', facility: 'Nairobi Plant',
      location: 'Utilities', status: 'under_maintenance', next_service_on: isoDaysFromToday(6) },
    { code: `${p}-GEN-001`, name: 'Standby generator 500 kVA', category: 'generator', facility: 'Thika Depot',
      location: 'Generator house', status: 'out_of_service' },
  ]
  for (const body of seed) {
    const status = await page.evaluate(async (b) => (await fetch('/api/maintenance/equipment', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b),
    })).status, body)
    expect(status).toBe(201)
  }

  await page.goto('/maintenance/equipment')
  await expect(page.getByRole('heading', { name: 'Equipment Register' })).toBeVisible()

  // Register one through the form, including server-side duplicate detection.
  await page.getByRole('button', { name: /Add Equipment/ }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Equipment ID').fill(`${p}-cnv-001`)
  await dialog.getByLabel('Equipment name').fill('Duplicate test')
  await dialog.getByLabel('Facility').fill('Nairobi Plant')
  await dialog.getByRole('button', { name: 'Register equipment' }).click()
  await expect(dialog.getByRole('alert')).toHaveText('That Equipment ID is already registered.')
  await dialog.getByLabel('Equipment ID').fill(`${p}-cmp-002`)
  await dialog.getByLabel('Equipment name').fill('Air compressor 2')
  await dialog.getByLabel('Category').selectOption('compressor')
  await dialog.getByLabel('Manufacturer (optional)').fill('Atlas Copco')
  await dialog.getByLabel('Location (optional)').fill('Compressor house')
  await dialog.getByLabel('Next service date (optional)').fill(isoDaysFromToday(30))
  await dialog.getByRole('button', { name: 'Register equipment' }).click()
  await expect(page.getByText(`${p}-CMP-002 registered`).first()).toBeVisible()

  // Find it, change its status, and check the history records it.
  await page.getByLabel('Search equipment').fill(`${p}-CMP`)
  await page.getByRole('button', { name: `${p}-CMP-002` }).first().click()
  await page.getByRole('button', { name: 'Edit' }).click()
  await page.getByRole('dialog').getByLabel('Operational status').selectOption('under_maintenance')
  await page.getByRole('dialog').getByRole('button', { name: 'Save changes' }).click()
  const history = page.getByRole('list', { name: 'Maintenance history' })
  await expect(history).toContainText('Status changed to under maintenance')
  await expect(history).toContainText(`${p}-CMP-002 registered`)

  // Archive with a reason, then restore.
  await page.getByRole('button', { name: 'Archive' }).click()
  await page.getByRole('dialog').getByLabel('Reason').fill('Moved to Thika Depot')
  await page.getByRole('dialog').getByRole('button', { name: 'Archive equipment' }).click()
  await expect(page.getByText('No equipment matches your filters')).toBeVisible()
  await page.getByLabel('Register view').selectOption('archived')
  await page.getByRole('button', { name: `${p}-CMP-002` }).first().click()
  await page.getByRole('button', { name: 'Restore' }).click()
  await expect(page.getByText(`${p}-CMP-002 restored to the active register`)).toBeVisible()

  await page.getByLabel('Search equipment').fill(p)
  // getByRole ignores the hidden layout (cards on phones, table elsewhere).
  await expect(page.getByRole('button', { name: `${p}-CNV-001` }).first()).toBeVisible()
  if (SHOTS) {
    await page.getByRole('button', { name: `${p}-CNV-001` }).first().click()
    await page.waitForTimeout(400)
    await page.evaluate('window.scrollTo(0, 0)')
    await page.screenshot({ path: `${SHOTS}/equipment-${info.project.name}.png`, fullPage: info.project.name !== 'desktop' })
  }
  // (string form: the e2e tsconfig has no DOM types)
  const overflow = await page.evaluate<number>(
    'document.documentElement.scrollWidth - document.documentElement.clientWidth',
  )
  expect(overflow).toBeLessThanOrEqual(1)
})
