import { expect, test, type Page } from '@playwright/test'

// Isolated e2e database; each browser project uses its own Equipment IDs (parallel runs).
const USERNAME = process.env.E2E_USERNAME!
const PASSWORD = process.env.E2E_PASSWORD!
const SHOTS = process.env.SHOTS_DIR

const post = (page: Page, path: string, body: unknown) =>
  page.evaluate(async ([p, b]) => {
    const r = await fetch(p as string, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) })
    return { status: r.status, body: (await r.json()) as { id: number; detail?: string } }
  }, [path, body] as const)

test('breakdown to repaired: log, raise work order, work it and restore the equipment', async ({ page }, info) => {
  const p = info.project.name.slice(0, 3).toUpperCase()
  await page.goto('/maintenance/login')
  await page.getByLabel('Username or email', { exact: true }).fill(USERNAME)
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Maintenance Dashboard' })).toBeVisible()

  const eq = await post(page, '/api/maintenance/equipment', {
    code: `${p}-CNV-201`, name: 'Packing line conveyor', category: 'conveyor', facility: 'Nairobi Plant', location: 'Line 2',
  })
  expect(eq.status).toBe(201)
  const pump = await post(page, '/api/maintenance/equipment', {
    code: `${p}-PMP-201`, name: 'Hydraulic power pack', category: 'hydraulic_system', facility: 'Nairobi Plant',
  })
  // A restored earlier failure on the pump, so the analysis shows more than one asset.
  const old = await post(page, '/api/maintenance/breakdowns', {
    equipment_id: pump.body.id, started_at: new Date(Date.now() - 26 * 3_600_000).toISOString(), severity: 'major',
    category: 'hydraulic', description: 'Pressure loss on main circuit', create_work_order: false,
  })
  expect(old.status).toBe(201)
  expect((await post(page, `/api/maintenance/breakdowns/${old.body.id}/restore`, {
    restored_at: new Date(Date.now() - 22 * 3_600_000).toISOString(), actions_taken: 'Replaced leaking hose and refilled',
  })).status).toBe(200)

  // Log a breakdown in the UI; it raises a critical corrective work order.
  await page.goto('/maintenance/breakdowns')
  await page.getByRole('button', { name: /Log breakdown/ }).click()
  const log = page.getByRole('dialog')
  await log.getByLabel('Equipment', { exact: true }).selectOption({ label: `${p}-CNV-201 · Packing line conveyor` })
  await log.getByLabel('Severity', { exact: true }).selectOption('critical')
  await log.getByLabel('Fault category', { exact: true }).selectOption('electrical')
  await log.getByLabel('What failed', { exact: true }).fill('Drive motor tripped on overload and will not restart')
  await log.getByLabel('Possible cause (optional)', { exact: true }).fill('Seized idler roller overloading the motor')
  await log.getByRole('button', { name: 'Log breakdown' }).click()
  await expect(page.getByText(/BD-\d{4}-\d{5} logged · WO-\d{4}-\d{5} raised/)).toBeVisible()

  // The same failure cannot be logged twice.
  const dup = await post(page, '/api/maintenance/breakdowns', {
    equipment_id: eq.body.id, started_at: new Date().toISOString(), severity: 'minor', category: 'other', description: 'Again',
  })
  expect(dup.status).toBe(409)

  // The breakdown card (the "most frequently failing" ranking also lists the Equipment ID).
  const card = page.getByRole('listitem').filter({ hasText: `${p}-CNV-201` }).filter({ hasText: /BD-\d{4}-\d{5}/ })
  await expect(card).toContainText('Down')
  if (SHOTS) {
    await page.getByLabel('Search breakdowns', { exact: true }).fill(p)
    await page.getByRole('button', { name: 'All', exact: true }).click()
    await page.waitForTimeout(600)
    await page.screenshot({ path: `${SHOTS}/breakdowns-${info.project.name}.png`, fullPage: info.project.name !== 'desktop' })
  }

  // Open the work order, assign, start, wait for parts, resume, complete and restore.
  await card.getByRole('link', { name: /WO-/ }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Work Orders', exact: true })).toBeVisible()
  // The detail panel (filter chips have similar names, e.g. "Awaiting parts", "Assigned").
  const panel = page.locator('section').filter({ has: page.getByRole('list', { name: 'Status history' }) })
  await panel.getByRole('button', { name: 'Assign', exact: true }).click()
  const edit = page.getByRole('dialog')
  await edit.getByLabel('Assigned technician', { exact: true }).selectOption({ index: 1 })
  await edit.getByRole('button', { name: 'Save' }).click()
  await panel.getByRole('button', { name: 'Start work', exact: true }).click()
  await panel.getByRole('button', { name: 'Awaiting parts', exact: true }).click()
  await panel.getByRole('button', { name: 'Resume', exact: true }).click()
  await panel.getByRole('button', { name: 'Complete', exact: true }).click()
  const done = page.getByRole('dialog')
  await done.getByLabel('Work performed').fill('Replaced seized idler roller, reset overload, motor current normal.')
  await expect(done.getByRole('checkbox', { name: /Equipment is back in service/ })).toBeChecked()
  await done.getByRole('button', { name: 'Complete work order' }).click()
  await expect(page.getByText(/WO-\d{4}-\d{5} completed/)).toBeVisible()

  const history = page.getByRole('list', { name: 'Status history' })
  for (const step of ['Work order raised', 'Work started', 'Waiting for parts', 'Work resumed', 'Completed']) {
    await expect(history).toContainText(step)
  }
  await expect(page.getByText('Restored', { exact: true }).first()).toBeVisible()
  if (SHOTS) {
    await page.waitForTimeout(400)
    await page.screenshot({ path: `${SHOTS}/work-orders-${info.project.name}.png`, fullPage: info.project.name !== 'desktop' })
  }

  // The equipment is operational again, with the whole story in its history.
  const status = await page.evaluate(async (id) => {
    const body = (await (await fetch(`/api/maintenance/equipment/${id}`)).json()) as { status: string }
    return body.status
  }, eq.body.id)
  expect(status).toBe('operational')
  const overflow = await page.evaluate<number>('document.documentElement.scrollWidth - document.documentElement.clientWidth')
  expect(overflow).toBeLessThanOrEqual(1)
})
