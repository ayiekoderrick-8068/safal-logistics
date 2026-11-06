import { expect, test, type Page } from '@playwright/test'

// Isolated e2e database; each browser project uses its own part numbers (parallel runs).
const USERNAME = process.env.E2E_USERNAME!
const PASSWORD = process.env.E2E_PASSWORD!
const SHOTS = process.env.SHOTS_DIR

const post = (page: Page, path: string, body: unknown) =>
  page.evaluate(async ([p, b]) => {
    const r = await fetch(p as string, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) })
    return { status: r.status, body: (await r.json()) as { id: number } }
  }, [path, body] as const)
const onHand = (page: Page, id: number) =>
  page.evaluate(async (pid) => ((await (await fetch(`/api/maintenance/parts/${pid}`)).json()) as { on_hand: number }).on_hand, id)

test('stores: add a part, receive, issue to a work order once, return and count', async ({ page }, info) => {
  test.setTimeout(180_000) // a long end-to-end story; the emulated phone is the slowest project
  const p = info.project.name.slice(0, 3).toUpperCase()
  // Any page wider than the viewport fails the test, checked on every page we visit.
  const noOverflow = async () =>
    expect(await page.evaluate<number>('document.documentElement.scrollWidth - document.documentElement.clientWidth')).toBeLessThanOrEqual(1)
  await page.goto('/maintenance/login')
  await page.getByLabel('Username or email', { exact: true }).fill(USERNAME)
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Maintenance Dashboard' })).toBeVisible()

  // A few catalogue items through the API so the page shows realistic variety.
  for (const part of [
    { part_number: `${p}-BLT-A68`, name: 'V-belt A68', unit: 'each', category: 'Belts', reorder_level: '4', unit_cost: '850', opening_quantity: '12', location: 'Store A / Bin 7' },
    { part_number: `${p}-FLT-AC30`, name: 'Compressor intake filter', unit: 'each', category: 'Filters', reorder_level: '2', unit_cost: '2400', opening_quantity: '1', location: 'Store B / Bin 2' },
    { part_number: `${p}-OIL-68`, name: 'Hydraulic oil ISO 68', unit: 'litre', category: 'Lubricants', reorder_level: '40', unit_cost: '420', opening_quantity: '55', location: 'Oil store' },
  ]) {
    expect((await post(page, '/api/maintenance/parts', part)).status).toBe(201)
  }

  // Add a part through the form.
  await page.goto('/maintenance/spare-parts')
  await expect(page.getByRole('article', { name: 'Stock Value' })).toContainText('KES')
  await noOverflow()
  await page.getByRole('button', { name: /Add part/ }).click()
  const form = page.getByRole('dialog')
  await form.getByLabel('Part number', { exact: true }).fill(`${p}-brg-6205`)
  await form.getByLabel('Name', { exact: true }).fill('Bearing 6205-2RS')
  await form.getByLabel('Category (optional)', { exact: true }).fill('Bearings')
  await form.getByLabel('Opening stock', { exact: true }).fill('3')
  await form.getByLabel('Reorder level', { exact: true }).fill('4')
  await form.getByLabel('Unit cost, KES (optional)', { exact: true }).fill('350')
  await form.getByLabel('Store location (optional)', { exact: true }).fill('Store A / Bin 3')
  await form.getByRole('button', { name: 'Add part' }).click()
  await expect(page.getByText(`${p}-BRG-6205 added`)).toBeVisible()
  await expect(page.getByRole('status').filter({ hasText: /needs? reordering/ })).toBeVisible()

  // Receive stock against a GRN.
  await page.getByLabel('Search spare parts', { exact: true }).fill(`${p}-BRG`)
  await page.getByRole('button', { name: new RegExp(`${p}-BRG-6205`) }).click()
  await page.getByRole('button', { name: 'Receive', exact: true }).click()
  const receive = page.getByRole('dialog')
  await receive.getByLabel(/^Quantity/).fill('7')
  await receive.getByLabel('GRN / delivery note (optional)', { exact: true }).fill('GRN-2210')
  await receive.getByRole('button', { name: 'Receive stock' }).click()
  await expect(page.getByText(`${p}-BRG-6205: now 10 each`)).toBeVisible()
  const bearing = (await page.evaluate(async (code) =>
    ((await (await fetch(`/api/maintenance/parts?q=${code}`)).json()) as { items: { id: number }[] }).items[0].id, `${p}-BRG-6205`))

  // A work order in progress to draw parts against.
  const eq = await post(page, '/api/maintenance/equipment', { code: `${p}-CNV-301`, name: 'Bottling line conveyor', category: 'conveyor', facility: 'Nairobi Plant' })
  const me = await page.evaluate(async () => ((await (await fetch('/api/auth/me')).json()) as { id: number }).id)
  const wo = await post(page, '/api/maintenance/work-orders', {
    equipment_id: eq.body.id, maintenance_type: 'corrective', priority: 'high',
    fault_description: 'Idler bearings noisy at drive end', assigned_technician_id: me,
  })
  await post(page, `/api/maintenance/work-orders/${wo.body.id}/transition`, { to: 'in_progress' })

  await page.goto(`/maintenance/work-orders?view=all&wo=${wo.body.id}`)
  await page.getByRole('button', { name: 'Issue parts', exact: true }).click()
  const issue = page.getByRole('dialog')
  await issue.getByLabel('Part', { exact: true }).selectOption({ value: String(bearing) })
  await issue.getByLabel(/^Quantity/).fill('2')
  // Double-click: the same request id is sent twice, the stock moves once.
  await issue.getByRole('button', { name: 'Issue parts' }).dblclick()
  await expect(page.getByText(/Parts issued to WO-/)).toBeVisible()
  expect(await onHand(page, bearing)).toBe(8)
  const parts = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Parts consumed' }) }).last()
  await expect(parts).toContainText(`${p}-BRG-6205`)
  await expect(parts).toContainText('KES 700.00')

  // Return the unused one.
  await parts.getByRole('button', { name: 'Return', exact: true }).click()
  const ret = page.getByRole('dialog')
  await ret.getByLabel('Quantity', { exact: true }).fill('1')
  await ret.getByRole('button', { name: 'Return to stock' }).click()
  await expect(page.getByText(/Parts returned from WO-/)).toBeVisible()
  expect(await onHand(page, bearing)).toBe(9)
  if (SHOTS) {
    await page.waitForTimeout(400)
    await page.screenshot({ path: `${SHOTS}/work-order-parts-${info.project.name}.png`, fullPage: info.project.name !== 'desktop' })
  }

  // Stock count with a reason.
  await page.goto('/maintenance/spare-parts')
  await page.getByLabel('Search spare parts', { exact: true }).fill(`${p}-BRG`)
  await page.getByRole('button', { name: new RegExp(`${p}-BRG-6205`) }).click()
  await page.getByRole('button', { name: 'Stock count', exact: true }).click()
  const count = page.getByRole('dialog')
  await count.getByLabel('Counted quantity', { exact: true }).fill('8')
  await count.getByLabel('Reason', { exact: true }).fill('Weekly count: one damaged, written off')
  await count.getByRole('button', { name: 'Record count' }).click()
  await expect(page.getByText(`${p}-BRG-6205: count recorded, 8 each`)).toBeVisible()
  const ledger = page.getByRole('list', { name: 'Stock movements' })
  for (const line of ['Stock count', 'Returned', 'Issued', 'Received']) await expect(ledger).toContainText(line)

  if (SHOTS) {
    await page.getByLabel('Search spare parts', { exact: true }).fill(p)
    await page.waitForTimeout(600)
    await page.screenshot({ path: `${SHOTS}/spare-parts-${info.project.name}.png`, fullPage: info.project.name !== 'desktop' })
  }
  const overflow = await page.evaluate<number>('document.documentElement.scrollWidth - document.documentElement.clientWidth')
  expect(overflow).toBeLessThanOrEqual(1)
})
