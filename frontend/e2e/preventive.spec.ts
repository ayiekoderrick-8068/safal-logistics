import { expect, test, type Page } from '@playwright/test'

// Isolated e2e database; each browser project uses its own Equipment IDs (parallel runs).
const USERNAME = process.env.E2E_USERNAME!
const PASSWORD = process.env.E2E_PASSWORD!
const SHOTS = process.env.SHOTS_DIR

const isoDays = (n: number) => new Date(Date.now() + n * 86_400_000).toISOString().slice(0, 10)
const call = (page: Page, path: string, body: unknown): Promise<{ status: number; body: { id: number } }> =>
  page.evaluate(async ([p, b]) => {
    const r = await fetch(p as string, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) })
    return { status: r.status, body: (await r.json()) as { id: number } }
  }, [path, body] as const)

test('plan recurring maintenance, complete overdue work and get the next task', async ({ page }, info) => {
  const p = info.project.name.slice(0, 3).toUpperCase()
  await page.goto('/maintenance/login')
  await page.getByLabel('Username or email').fill(USERNAME)
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Maintenance Dashboard' })).toBeVisible()

  const eq = await call(page, '/api/maintenance/equipment', {
    code: `${p}-CMP-101`, name: 'Air compressor 1', category: 'compressor', facility: 'Nairobi Plant',
    location: 'Compressor house',
  })
  expect(eq.status).toBe(201)
  const pump = await call(page, '/api/maintenance/equipment', {
    code: `${p}-PMP-101`, name: 'Cooling water pump', category: 'pump', facility: 'Nairobi Plant',
  })
  // A second, upcoming plan so the board shows a realistic mix.
  expect((await call(page, '/api/maintenance/plans', {
    equipment_id: pump.body.id, title: 'Pump seal inspection', interval_value: 2, interval_unit: 'weeks', start_on: isoDays(3),
  })).status).toBe(201)

  // Create a monthly plan through the form, first due a week ago -> overdue immediately.
  await page.goto('/maintenance/preventive')
  await page.getByRole('button', { name: /New plan/ }).click()
  const form = page.getByRole('dialog')
  await form.getByLabel('Equipment').selectOption({ label: `${p}-CMP-101 · Air compressor 1` })
  await form.getByLabel('Plan title').fill('Monthly compressor service')
  await form.getByLabel('Repeat every').fill('1')
  await form.getByLabel('Unit').selectOption('months')
  await form.getByLabel('First due date').fill(isoDays(-7))
  await form.getByLabel('Instructions (optional)').fill('Drain condensate. Check belt tension. Replace intake filter.')
  await form.getByRole('button', { name: 'Create plan' }).click()
  await expect(page.getByText(/Plan created; first task due/)).toBeVisible()

  // The overdue alert and the overdue view both show it.
  await expect(page.getByTestId('pm-alert-count')).toBeVisible()
  await page.getByRole('button', { name: /^Overdue/ }).click()
  await page.getByLabel('Search tasks').fill(`${p}-CMP`)
  // Scoped to this project's asset: the other browser projects create the same plan title.
  const card = page.getByRole('listitem').filter({ hasText: `${p}-CMP-101` }).filter({ hasText: 'Monthly compressor service' })
  await expect(card).toContainText('7 days overdue')
  if (SHOTS) {
    await page.getByLabel('Search tasks').fill(p)
    await page.getByRole('button', { name: 'All open' }).click()
    await page.waitForTimeout(500)
    await page.screenshot({ path: `${SHOTS}/preventive-tasks-${info.project.name}.png`, fullPage: info.project.name !== 'desktop' })
    await page.getByRole('button', { name: /^Overdue/ }).click()
    await page.getByLabel('Search tasks').fill(`${p}-CMP`)
  }

  // Completing requires the work performed; then the next cycle is generated (due date + 1 month).
  await card.getByRole('button', { name: 'Complete' }).click()
  const done = page.getByRole('dialog')
  await expect(done).toContainText('Replace intake filter.')
  await done.getByRole('button', { name: 'Mark as completed' }).click()
  await expect(done.getByRole('alert')).toHaveText('Describe the work performed.')
  await done.getByLabel('Work performed').fill('Drained condensate, re-tensioned belt, new intake filter fitted.')
  await done.getByRole('button', { name: 'Mark as completed' }).click()
  await expect(page.getByText(`${p}-CMP-101: Monthly compressor service completed`)).toBeVisible()
  await expect(page.getByText('Nothing is overdue').or(card.filter({ hasText: 'overdue' }))).toBeVisible()

  await page.getByRole('button', { name: 'Completed' }).click()
  await expect(page.getByRole('listitem').filter({ hasText: `${p}-CMP-101` }).first()).toContainText('(late)')

  // Plans tab: the next task is a month after the original due date.
  await page.getByRole('tab', { name: 'Plans' }).click()
  await page.getByLabel('Search plans').fill(`${p}-CMP`)
  const plan = page.getByRole('listitem').filter({ hasText: `${p}-CMP-101` })
  await expect(plan).toContainText('Every month')
  const res: string[] = await page.evaluate(async (code) => {
    const r = await fetch(`/api/maintenance/tasks?view=open&q=${code}`)
    const data = (await r.json()) as { items: { due_on: string }[] }
    return data.items.map((t) => t.due_on)
  }, `${p}-CMP`)
  const due = new Date(Date.now() - 7 * 86_400_000)
  due.setMonth(due.getMonth() + 1)
  expect(res).toHaveLength(1)
  expect(Math.abs(new Date(res[0]).getTime() - due.getTime())).toBeLessThan(3 * 86_400_000)

  if (SHOTS) {
    await page.getByLabel('Search plans').fill(p)
    await page.waitForTimeout(500)
    await page.screenshot({ path: `${SHOTS}/preventive-plans-${info.project.name}.png`, fullPage: info.project.name !== 'desktop' })
    await page.getByLabel('Search plans').fill(`${p}-CMP`)
  }

  // Stopping a plan needs a reason and cancels its open task.
  await plan.getByRole('button', { name: 'Stop plan' }).click()
  await page.getByRole('dialog').getByLabel('Reason').fill('Compressor replaced by new unit')
  await page.getByRole('dialog').getByRole('button', { name: 'Stop plan' }).click()
  await expect(page.getByText('Plan “Monthly compressor service” stopped')).toBeVisible()

  const overflow = await page.evaluate<number>('document.documentElement.scrollWidth - document.documentElement.clientWidth')
  expect(overflow).toBeLessThanOrEqual(1)
})
