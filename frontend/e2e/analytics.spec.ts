import { readFileSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'

// Isolated e2e database; each browser project uses its own Equipment IDs (parallel runs).
const USERNAME = process.env.E2E_USERNAME!
const PASSWORD = process.env.E2E_PASSWORD!
const SHOTS = process.env.SHOTS_DIR

const post = (page: Page, path: string, body: unknown) =>
  page.evaluate(async ([p, b]) => {
    const r = await fetch(p as string, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) })
    return { status: r.status, body: (await r.json()) as { id: number; work_orders?: { id: number }[] } }
  }, [path, body] as const)
const hoursAgo = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString()
const daysAgo = (d: number) => new Date(Date.now() - d * 86_400_000).toISOString().slice(0, 10)

test('dashboard and reports show live reliability figures and export CSV, Excel and PDF', async ({ page }, info) => {
  test.setTimeout(180_000)
  const p = info.project.name.slice(0, 3).toUpperCase()
  await page.goto('/maintenance/login')
  await page.getByLabel('Username or email', { exact: true }).fill(USERNAME)
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Maintenance Dashboard' })).toBeVisible()
  const me = await page.evaluate(async () => ((await (await fetch('/api/auth/me')).json()) as { id: number }).id)

  // Real records: two assets, a repaired breakdown, an open one, a preventive plan due in the past.
  const eq = await post(page, '/api/maintenance/equipment', { code: `${p}-CNV-401`, name: 'Packing conveyor', category: 'conveyor', facility: 'Nairobi Plant' })
  const pump = await post(page, '/api/maintenance/equipment', { code: `${p}-PMP-401`, name: 'Cooling pump', category: 'pump', facility: 'Nairobi Plant' })
  const bd = await post(page, '/api/maintenance/breakdowns', { equipment_id: eq.body.id, started_at: hoursAgo(5), severity: 'major', category: 'mechanical', description: 'Gearbox seized' })
  const woId = bd.body.work_orders![0].id
  await page.evaluate(async ([id, tech]) => {
    await fetch(`/api/maintenance/work-orders/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ assigned_technician_id: tech }) })
    await fetch(`/api/maintenance/work-orders/${id}/transition`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ to: 'in_progress' }) })
  }, [woId, me] as const)
  expect((await post(page, `/api/maintenance/work-orders/${woId}/complete`, { work_performed: 'Replaced gearbox bearings and oil seal', restore_breakdown: true })).status).toBe(200)
  await post(page, '/api/maintenance/breakdowns', { equipment_id: pump.body.id, started_at: hoursAgo(1), severity: 'critical', category: 'electrical', description: 'Motor tripped', create_work_order: false })
  await post(page, '/api/maintenance/plans', { equipment_id: pump.body.id, title: 'Weekly pump check', interval_value: 1, interval_unit: 'weeks', start_on: daysAgo(3) })

  await page.goto('/maintenance')
  await expect(page.getByRole('article', { name: 'MTTR' })).not.toContainText('Insufficient data')
  // A real figure (hours, or minutes when short), never a rounded "0 h".
  const mtbf = page.getByRole('article', { name: 'MTBF' })
  await expect(mtbf.getByTestId('metric-value')).toHaveText(/^((< )?[\d,.]+ (h|min)|Insufficient data)$/)
  await expect(mtbf).not.toContainText(/(^|\s)0(\.0)? h\b/)
  await expect(page.getByRole('list', { name: 'Recent activity' })).toContainText(p)
  const failing = page.getByRole('group', { name: 'Most frequently failing view' })
  await failing.getByRole('button', { name: /Table/ }).click()
  await expect(page.getByRole('table', { name: 'Most frequently failing' })).toContainText(`${p}-`)
  await failing.getByRole('button', { name: /Chart/ }).click()
  if (SHOTS) {
    await page.waitForTimeout(800)
    await page.screenshot({ path: `${SHOTS}/dashboard-${info.project.name}.png`, fullPage: info.project.name !== 'desktop' })
  }

  // Reports: preview, then the three export formats as real downloads.
  await page.goto('/maintenance/reports')
  await expect(page.getByRole('heading', { name: 'Maintenance Reports' })).toBeVisible()
  await page.getByRole('option', { name: /Repair duration/ }).click()
  await expect(page.getByRole('table').last()).toContainText('WO-')
  for (const [name, signature] of [['CSV', 'Report'], ['Excel', 'PK'], ['PDF', '%PDF-']] as const) {
    const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name }).click()])
    const content = readFileSync(await download.path())
    expect(download.suggestedFilename()).toMatch(/^logitrack-repair-duration-\d{4}-\d{2}-\d{2}-\d{4}-\d{2}-\d{2}\.(csv|xlsx|pdf)$/)
    expect(content.toString('latin1')).toContain(signature)
  }
  if (SHOTS) {
    await page.waitForTimeout(500)
    await page.screenshot({ path: `${SHOTS}/reports-${info.project.name}.png`, fullPage: info.project.name !== 'desktop' })
  }
  const overflow = await page.evaluate<number>('document.documentElement.scrollWidth - document.documentElement.clientWidth')
  expect(overflow).toBeLessThanOrEqual(1)
})
