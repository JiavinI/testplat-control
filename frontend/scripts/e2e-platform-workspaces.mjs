/** Read-only acceptance on configured preview; credentials stay in private storage state. */
import { chromium } from 'playwright'
import fs from 'node:fs'
import assert from 'node:assert/strict'

const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173'
assert(process.env.E2E_STORAGE_STATE, 'E2E_STORAGE_STATE required')
const out = process.env.E2E_OUT_DIR || '/tmp/testplat-platform-browser'
fs.mkdirSync(out, { recursive: true })
const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ storageState: process.env.E2E_STORAGE_STATE, viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const errors = []
page.on('pageerror', (e) => errors.push(e.name))
const report = { workspaces: [], config: [], errors }
const choose = async (label, value) => {
  await page.getByTestId(label === '选择平台' ? 'feature-platform-select' : 'feature-project-select').locator('.ant-select-selector').click()
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option').filter({ hasText: new RegExp(`^${value}$`) }).click()
}
try {
  await page.goto(`${base}/apis/main/gsb`, { waitUntil: 'networkidle' })
  await page.getByTestId('workspace-context-title').waitFor()
  assert.equal(await page.getByTestId('workspace-context-title').textContent(), 'GO2 的 GSB')
  await page.getByTestId('feature-platform-select').locator('.ant-select-selector').click()
  const options = await page.locator('.ant-select-dropdown:visible .ant-select-item-option').allTextContents()
  assert.equal(options.length, 6)
  await page.keyboard.press('Escape')
  await choose('选择项目', 'E3E3')
  await page.waitForURL('**/apis/main/gsb_e3e3')
  await page.getByTestId('workspace-context-title').filter({ hasText: 'E3E3 的 GSB' }).waitFor()
  await choose('选择平台', 'E3E3 网站')
  await page.waitForURL('**/apis/main/e3e3')
  await choose('选择平台', 'GSB')
  await page.waitForURL('**/apis/main/gsb_e3e3')
  await page.screenshot({ path: `${out}/gsb-e3e3-desktop.png`, fullPage: true })
  for (const [key, title] of [['go2', 'GO2 网站 · GO2'], ['e3e3', 'E3E3 网站 · E3E3'], ['gsb', 'GO2 的 GSB'], ['gsb_e3e3', 'E3E3 的 GSB'], ['daifa_admin', '代发后台 · GO2'], ['daifa_admin_e3e3', '代发后台 · E3E3'], ['daifa_picker', '拿货端 · GO2'], ['daifa_picker_e3e3', '拿货端 · E3E3'], ['admin_go2', 'GO2 管理后台 · GO2'], ['admin_go2_e3e3', 'GO2 管理后台 · E3E3']]) {
    await page.goto(`${base}/apis/main/${key}`, { waitUntil: 'networkidle' })
    assert.equal(await page.getByTestId('workspace-context-title').textContent(), title)
    await page.getByTestId('asset-browser').waitFor()
    report.workspaces.push(key)
    await page.goto(`${base}/configuration/main/${key}?tab=environments`, { waitUntil: 'networkidle' })
    await page.getByTestId('environment-manager').waitFor()
    assert(await page.getByText('test', { exact: true }).count() > 0)
    await page.getByRole('tab', { name: '测试账号', exact: true }).click()
    await page.getByTestId('account-manager').waitFor()
    report.config.push(key)
  }
  await page.goto(`${base}/configuration/main/go2?tab=accounts`, { waitUntil: 'networkidle' })
  await page.getByText(/环境和账号与「GO2 的 GSB」共用/).waitFor()
  await page.getByText('gsb.b1.primary', { exact: true }).waitFor()
  await page.getByText('gsb.b2.primary', { exact: true }).waitFor()
  await page.screenshot({ path: `${out}/go2-accounts.png`, fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`${base}/apis/main/gsb_e3e3`, { waitUntil: 'networkidle' })
  assert(await page.getByTestId('feature-platform-select').isVisible())
  assert(await page.getByTestId('feature-project-select').isVisible())
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
  assert.equal(overflow, false)
  await page.screenshot({ path: `${out}/platform-mobile.png`, fullPage: true })
  assert.deepEqual(errors, [])
  report.platform_options = options
  report.mobile_no_overflow = true
  fs.writeFileSync(`${out}/report.json`, JSON.stringify(report, null, 2))
  console.log(JSON.stringify({ workspaces: report.workspaces.length, configuration_contexts: report.config.length, errors: errors.length, mobile_no_overflow: true }))
} finally {
  await context.close()
  await browser.close()
}
