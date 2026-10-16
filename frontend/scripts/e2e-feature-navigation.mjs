/** 四个功能入口的浏览器回归。使用已有平台会话或显式提供的平台登录信息。 */
import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'
import assert from 'node:assert/strict'

const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173'
const repo = process.env.E2E_REPO || 'main'
const project = process.env.E2E_PROJECT || 'gsb'
const out = process.env.E2E_OUT_DIR || '/tmp/testplat-feature-navigation'
fs.mkdirSync(out, { recursive: true })
const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  ...(process.env.E2E_STORAGE_STATE ? { storageState: process.env.E2E_STORAGE_STATE } : {}),
})
const page = await context.newPage()
const errors = []
page.on('pageerror', (error) => errors.push(error.name))
const nav = page.getByRole('navigation', { name: '功能菜单' })
const report = {}
try {
  await page.goto(`${base}/apis/${repo}/${project}`, { waitUntil: 'networkidle' })
  if (await page.getByTestId('login-page').isVisible()) {
    assert(process.env.E2E_USERNAME && process.env.E2E_PASSWORD, '需要已有平台会话或 E2E_USERNAME / E2E_PASSWORD')
    await page.getByTestId('auth-username').fill(process.env.E2E_USERNAME)
    await page.getByTestId('auth-password').fill(process.env.E2E_PASSWORD)
    await page.getByTestId('auth-submit').click()
  }
  await page.getByTestId('feature-project-select').waitFor()
  assert.equal(await nav.getByRole('link').count(), 4)
  await page.locator('[data-asset-id="api"]').waitFor()
  assert.equal(await page.locator('[data-asset-id="config"], [data-asset-id="scenarios"]').count(), 0)
  await page.screenshot({ path: path.join(out, 'apis-desktop.png'), fullPage: true, animations: 'disabled' })
  report.apis = 'passed'

  if (process.env.E2E_RUN_API === '1') {
    const asset = process.env.E2E_API_ID || 'api.gsb.account.balance'
    await page.getByLabel('过滤资产').fill(asset)
    await page.locator(`[data-asset-id="${asset}"]`).click()
    await page.getByTestId('api-execution-panel').waitFor()
    const responsePromise = page.waitForResponse((response) => response.request().method() === 'POST' && new URL(response.url()).pathname.endsWith(`/assets/${asset}/run`), { timeout: 60000 })
    await page.getByRole('button', { name: '执行 API', exact: true }).click()
    const response = await responsePromise
    assert.equal(response.status(), 200)
    const run = await response.json()
    assert.equal(run.status, 'success')
    report.api_run = { status: run.status, record_id: run.record_id }
  }

  await nav.getByRole('link', { name: 'Page 管理', exact: true }).click()
  await page.getByRole('heading', { name: 'Page 管理', exact: true }).waitFor()
  assert.equal(await page.getByTestId('execution-history').count(), 0)
  assert.equal(await page.locator('[data-asset-id="api"], [data-asset-id="scenarios"], [data-asset-id="config"]').count(), 0)
  report.pages = 'passed'

  await nav.getByRole('link', { name: '场景测试', exact: true }).click()
  await page.locator('[data-asset-id="scenarios"]').waitFor()
  assert.equal(await page.locator('[data-asset-id="api"], [data-asset-id="config"]').count(), 0)
  await page.screenshot({ path: path.join(out, 'scenarios-desktop.png'), fullPage: true, animations: 'disabled' })
  report.scenarios = 'passed'

  await nav.getByRole('link', { name: '配置', exact: true }).click()
  await page.getByRole('tab', { name: '项目配置', exact: true }).waitFor()
  await page.locator('[data-asset-id="config"]').waitFor()
  assert.equal(await page.locator('[data-asset-id="api"], [data-asset-id="scenarios"]').count(), 0)
  await page.getByRole('tab', { name: '环境管理', exact: true }).click()
  await page.getByTestId('environment-manager').waitFor()
  await page.getByRole('tab', { name: '测试账号', exact: true }).click()
  await page.getByTestId('account-manager').waitFor()
  await page.screenshot({ path: path.join(out, 'configuration-desktop.png'), fullPage: true, animations: 'disabled' })
  report.configuration = 'passed'

  await page.setViewportSize({ width: 390, height: 844 })
  await nav.getByRole('link', { name: '接口管理', exact: true }).click()
  await page.getByRole('button', { name: '打开资产浏览' }).click()
  await page.getByRole('dialog').waitFor()
  await page.getByRole('dialog').getByLabel('过滤资产').waitFor()
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
  await page.screenshot({ path: path.join(out, 'apis-mobile.png'), fullPage: false, animations: 'disabled' })
  report.mobile = 'passed'
  assert.deepEqual(errors, [])
  report.page_errors = errors.length
  fs.writeFileSync(path.join(out, 'report.json'), `${JSON.stringify(report, null, 2)}\n`)
  console.log(JSON.stringify(report))
} finally {
  await browser.close()
}
