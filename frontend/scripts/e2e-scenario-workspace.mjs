/** Browser acceptance for the isolated schema 0.3 scenario example. */
import { chromium } from 'playwright'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const base = process.env.E2E_BASE_URL
const out = process.env.E2E_OUT_DIR
if (!base || !out) throw new Error('Run through scripts/verify_scenario_workspace.py')
assert.equal(new URL(base).hostname, '127.0.0.1')
fs.mkdirSync(out, { recursive: true })
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
page.setDefaultTimeout(15000)
const errors = []
const runs = []
page.on('pageerror', error => errors.push(error.name))
page.on('request', request => {
  if (new URL(request.url()).pathname.endsWith('/run')) runs.push(request.method())
})
try {
  await page.goto(`${base}/scenarios/isolated/demo`)
  await page.getByTestId('asset-tree').waitFor()
  const treeResponse = await page.request.get(`${base}/api/repos/isolated/projects/demo/assets`)
  assert.equal(treeResponse.status(), 200)
  const tree = await treeResponse.json()
  const ancestors = (node, id, parents = []) => {
    if (node.id === id) return parents
    for (const child of node.children ?? []) {
      const found = ancestors(child, id, [...parents, node.id])
      if (found) return found
    }
    return null
  }
  const selectCase = async () => {
    for (const id of ancestors(tree, 'case.demo.repeat') ?? []) {
      if (id === 'assets') continue
      const element = page.locator(`[data-asset-id="${id}"]`)
      const node = element.locator('xpath=ancestor::*[contains(@class,"ant-tree-treenode")][1]')
      if (await node.getAttribute('aria-expanded') !== 'true') await element.click()
    }
    await page.locator('[data-asset-id="case.demo.repeat"]').click()
  }
  await selectCase()
  await page.getByTestId('case-execution-panel').waitFor()
  const outline = page.getByTestId('scenario-step-outline')
  const detail = page.getByTestId('scenario-step-detail')
  await outline.getByText('执行顺序').waitFor()
  await detail.getByText('步骤 1').waitFor()
  await detail.getByRole('heading', { name: '回显并导出' }).waitFor()
  await outline.locator('.tp-scenario-outline__item').nth(2).click()
  await detail.getByText('步骤 2').waitFor()
  await detail.getByRole('heading', { name: '回显并导出' }).waitFor()
  await outline.locator('.tp-scenario-outline__item').first().click()
  await page.getByRole('button', { name: '本次参数' }).click()
  await page.getByText('common', { exact: true }).waitFor()
  await page.getByText('private.first.quantity', { exact: true }).waitFor()
  await page.getByRole('button', { name: 'JSON' }).click()
  await page.getByLabel('本次场景参数 JSON').waitFor()
  await page.getByRole('button', { name: '完成' }).click()
  await page.screenshot({ path: `${out}/scenario-workbench-desktop.png`, fullPage: true, animations: 'disabled' })

  const response = page.waitForResponse(item =>
    new URL(item.url()).pathname.endsWith('/cases/case.demo.repeat/run'),
  )
  await page.getByTestId('case-run-button').click()
  const run = await response
  assert.equal(run.status(), 200)
  const result = await run.json()
  assert.equal(result.result.status, 'success')
  assert.equal(result.result.result_version, '0.3')
  assert.equal(result.result.steps.length, 3)
  assert.equal(result.result.steps[0].trace.outputs.value.item.quantity, 1)
  assert.equal(result.result.steps[1].trace.outputs.value.item.quantity, 2)
  assert.deepEqual(result.result.steps[2].trace.inputs.value.second.item, { quantity: 2 })
  await page.getByTestId('case-result-view').waitFor()
  await page.getByRole('button', { name: /1 · first/ }).click()
  await page.getByRole('button', { name: /1\.1.*echo/ }).click()
  await page.getByText(`POST ${result.result.steps[0].trace.children[0].request.url}`).waitFor()
  await page.getByLabel('echo request').waitFor()
  await page.getByLabel('echo response').waitFor()
  await page.screenshot({ path: `${out}/scenario-nested-result-desktop.png`, fullPage: true, animations: 'disabled' })

  await page.reload()
  await page.getByTestId('asset-tree').waitFor()
  await selectCase()
  await page.getByText('执行历史', { exact: true }).waitFor()
  await page.getByRole('button', { name: `查看记录 ${result.record_id}` }).click()
  const history = page.getByTestId('execution-detail')
  await history.getByTestId('case-result-view').waitFor()
  await history.getByRole('button', { name: /1 · first/ }).click()
  await history.getByRole('button', { name: /1\.1.*echo/ }).click()
  await history.getByLabel('echo request').waitFor()
  await history.getByLabel('echo response').waitFor()
  await page.screenshot({ path: `${out}/scenario-history-desktop.png`, fullPage: false, animations: 'disabled' })
  await page.locator('.ant-drawer-close').click()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.evaluate(() => window.scrollTo(0, 0))
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
  await page.screenshot({ path: `${out}/scenario-mobile.png`, fullPage: false, animations: 'disabled' })
  assert.deepEqual(errors, [])
  assert.equal(runs.length, 1)
  console.log(JSON.stringify({
    scenario_parameters_and_bindings: true,
    repeated_flow_calls_and_nested_outputs: true,
    nested_history: true,
    mobile_no_overflow: true,
    case_runs: runs.length,
    page_errors: errors.length,
  }))
} catch (error) {
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true, animations: 'disabled' })
  throw error
} finally {
  await browser.close()
}
