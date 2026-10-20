/** Isolated real Control + Engine browser acceptance; launched by the Python harness. */
import { chromium } from 'playwright'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const base = process.env.E2E_BASE_URL
const out = process.env.E2E_OUT_DIR
const problem = process.env.E2E_PROBLEM
if (!base || !out || !problem) throw new Error('Use verify_pending_workspace.py')
assert.equal(new URL(base).hostname, '127.0.0.1')
fs.mkdirSync(out, { recursive: true })
const id = 'case.go2.order.full_pay.items_create_pending'
const api = `${base}/api/repos/isolated/projects/demo`
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
page.setDefaultTimeout(15000)
const errors = []
page.on('pageerror', error => errors.push(error.name))
const findPath = (steps, predicate, prefix = []) => {
  for (let i = 0; i < steps.length; i++) {
    const path = [...prefix, i]
    if (predicate(steps[i])) return path
    const found = findPath(steps[i].trace?.children ?? [], predicate, path)
    if (found) return found
  }
}
const openPath = async (scope, path) => {
  for (let depth = 1; depth <= path.length; depth++) {
    const number = path.slice(0, depth).map(n => n + 1).join('.')
    const label = new RegExp(`^${number.replaceAll('.', '\\.')}($| ·)`)
    const header = scope.locator('.ant-collapse-header').filter({ has: page.locator('code').filter({ hasText: label }) })
    if (await header.getAttribute('aria-expanded') !== 'true') await header.click()
  }
}
const selectCase = async () => {
  await page.getByTestId('asset-tree').waitFor()
  const response = await page.request.get(`${api}/assets`)
  assert.equal(response.status(), 200)
  const tree = await response.json()
  const ancestors = (node, parents = []) => {
    if (node.id === id) return parents
    for (const child of node.children ?? []) {
      const found = ancestors(child, [...parents, node.id])
      if (found) return found
    }
  }
  for (const nodeId of ancestors(tree) ?? []) {
    if (nodeId === 'assets') continue
    const element = page.locator(`[data-asset-id="${nodeId}"]`)
    const node = element.locator('xpath=ancestor::*[contains(@class,"ant-tree-treenode")][1]')
    if (await node.getAttribute('aria-expanded') !== 'true') await element.click()
  }
  await page.locator(`[data-asset-id="${id}"]`).click()
  await page.getByTestId('scenario-step-outline').waitFor()
}
try {
  await page.goto(`${base}/scenarios/isolated/demo`)
  await selectCase()
  const outline = page.getByTestId('scenario-step-outline')
  const detail = page.getByTestId('scenario-step-detail')
  for (const [type, expected] of [['有序遍历', '下列子步骤为每项复用定义'], ['数据提取', '选择器'], ['金额计算', 'HALF_UP'], ['条件断言', '操作'], ['列表处理', '操作']]) {
    await outline.locator('.tp-scenario-outline__item').filter({ hasText: type }).first().click()
    await detail.getByText(expected, { exact: false }).first().waitFor()
  }
  const pendingResponse = page.waitForResponse(response => new URL(response.url()).pathname.endsWith(`/cases/${id}/run`))
  await page.getByTestId('case-run-button').click()
  const response = await pendingResponse
  assert.equal(response.status(), 200)
  const run = await response.json()
  assert.equal(run.result.status, problem === 'success' ? 'success' : 'failed')
  const view = page.getByTestId('case-result-view')
  await view.waitFor()
  if (problem === 'success') {
    assert.equal(run.result.steps[0].trace.outputs.web_order_amount, '11.200')
    for (const [type, evidence] of [['extract', '提取证据'], ['decimal', '金额计算证据'], ['assert', '断言证据'], ['transform', '列表处理证据']]) {
      await openPath(view, findPath(run.result.steps, step => step.type === type))
      await view.getByRole('region', { name: evidence }).first().waitFor()
    }
    const path = findPath(run.result.steps, step => step.type === 'api')
    await openPath(view, path)
    await view.getByLabel('search request', { exact: true }).waitFor()
    await view.getByLabel('search response', { exact: true }).waitFor()
  } else if (problem === 'no_second_sku') {
    await view.getByText('遍历项 2（index=1）', { exact: true }).waitFor()
    const evidence = view.getByRole('region', { name: '提取证据' }).filter({ hasText: '命中数' })
    assert.match(await evidence.last().innerText(), /\b0\b/)
    assert.equal(run.result.steps[1].status, 'skipped')
  } else {
    const evidence = view.getByRole('region', { name: '断言证据' }).filter({ hasText: '11.21' })
    await evidence.waitFor()
    assert.match(await evidence.innerText(), /11.20/)
    assert.equal(run.result.steps[1].status, 'skipped')
  }
  await page.screenshot({ path: `${out}/${problem}-desktop.png`, fullPage: true, animations: 'disabled' })
  const stored = await page.request.get(`${api}/case-execution-records/${run.record_id}`)
  assert.equal(stored.status(), 200)
  assert.deepEqual((await stored.json()).result, run.result)
  await page.reload()
  await selectCase()
  await page.getByRole('button', { name: `查看记录 ${run.record_id}` }).click()
  const history = page.getByTestId('execution-detail')
  await history.getByTestId('case-result-view').waitFor()
  if (problem === 'success') {
    await openPath(history, findPath(run.result.steps, step => step.type === 'api'))
    await history.getByLabel('search request', { exact: true }).waitFor()
  } else {
    await history.getByRole('region', { name: problem === 'no_second_sku' ? '提取证据' : '断言证据' }).first().waitFor()
  }
  await page.screenshot({ path: `${out}/${problem}-history.png`, fullPage: false, animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 844 })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
  await page.screenshot({ path: `${out}/${problem}-mobile-history.png`, fullPage: false, animations: 'disabled' })
  await page.locator('.ant-drawer-close').click()
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
  await page.screenshot({ path: `${out}/${problem}-mobile.png`, fullPage: false, animations: 'disabled' })
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ definition_types: 7, evidence_and_nested_history: true, mobile_no_overflow: true, page_errors: errors.length }))
} catch (error) {
  await page.screenshot({ path: `${out}/${problem}-failure.png`, fullPage: true, animations: 'disabled' })
  throw error
} finally {
  await browser.close()
}
