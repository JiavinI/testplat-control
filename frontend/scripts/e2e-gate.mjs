/**
 * Phase 2.4 浏览器门禁：联调截图 + 横向溢出 + console/page/failed request。
 *
 * 假设前端 http://127.0.0.1:5173 与后端 :8000 已启动（可用 FakeEngine）。
 *   pnpm exec node scripts/e2e-gate.mjs
 *
 * 允许（后端既有业务，不改契约）：
 *   - DELETE /api/projects/:id → 500（有执行记录不可删）
 *   - POST /api/projects → 500（项目名 UNIQUE）
 *   - 对应的 "Failed to load resource … 500" console
 * 其余 console error / pageerror / 失败请求 / 横向溢出 → 门禁失败。
 */

import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const frontendRoot = path.resolve(__dirname, '..')
const repoRoot = path.resolve(frontendRoot, '..')
const BASE = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173'
const ASSETS_ROOT = path.join(repoRoot, 'tests', 'fixtures', 'assets')
const CONFIG_ROOT = path.join(repoRoot, 'tests', 'fixtures', 'config')
const OUT = process.env.E2E_OUT_DIR
  ? path.resolve(process.env.E2E_OUT_DIR)
  : path.join(frontendRoot, 'screenshots', 'phase2-4')

fs.mkdirSync(OUT, { recursive: true })

function makeProjectName(suffix) {
  return `e2e-${Date.now()}-${suffix}`
}

function isAllowedFailedRequest(entry) {
  // "500 DELETE http://..."
  const m = String(entry).match(/^(\d+)\s+(\S+)\s+(\S+)/)
  if (!m) return false
  const [, status, method, url] = m
  if (status === '500' && method === 'DELETE' && /\/api\/projects\/[^/?]+$/.test(url)) {
    return true
  }
  if (status === '500' && method === 'POST' && /\/api\/projects\/?$/.test(url)) {
    return true
  }
  return false
}

function isAllowedConsoleError(text) {
  if (text.includes('Failed to load resource') && text.includes('500')) {
    return true
  }
  if (text.includes('Download the React DevTools')) {
    return true
  }
  return false
}

async function shot(page, name) {
  const file = path.join(OUT, name)
  await page.screenshot({ path: file, fullPage: true })
  console.log('screenshot', file)
  return file
}

async function fillByLabel(page, label, value) {
  const input = page.getByLabel(label)
  await input.click()
  await input.fill(value)
}

async function runFlow(page, viewportLabel, projectName) {
  console.log('--- viewport', viewportLabel, page.viewportSize())
  const consoleErrors = []
  const pageErrors = []
  const failedRequests = []

  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text())
  })
  page.on('pageerror', (err) => {
    pageErrors.push(err.message || String(err))
  })
  page.on('response', (res) => {
    if (res.status() >= 400) {
      failedRequests.push(`${res.status()} ${res.request().method()} ${res.url()}`)
    }
  })

  await page.goto(`${BASE}/projects`, { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: /新建项目/ }).first().click()
  const dialog = page.getByRole('dialog')
  await dialog.waitFor()
  await fillByLabel(page, /项目名称/, projectName)
  await fillByLabel(page, /资产目录/, ASSETS_ROOT)
  await fillByLabel(page, /配置目录/, CONFIG_ROOT)
  await dialog.getByRole('button', { name: /确\s*定|OK/i }).click()

  await page.getByTestId('project-workspace').waitFor({ timeout: 15000 })
  await shot(page, `${viewportLabel}-01-workspace-after-create.png`)

  const assetsBtn = page.getByRole('button', { name: '打开资产浏览' })
  if (await assetsBtn.isVisible().catch(() => false)) {
    await assetsBtn.click()
    await page.waitForTimeout(400)
  }

  const filter = page.getByLabel('过滤资产')
  await filter.waitFor({ timeout: 10000 })
  await filter.fill('login')
  await page.waitForTimeout(300)
  await shot(page, `${viewportLabel}-02-asset-search.png`)

  const loginNode = page.locator('[data-asset-id="api.user.login"]')
  await loginNode.waitFor({ timeout: 10000 })
  await loginNode.click()
  await page.getByTestId('api-execution-panel').waitFor({ timeout: 10000 })
  await shot(page, `${viewportLabel}-03-api-selected.png`)

  await page.getByTestId('param-username').fill('alice')
  await page.getByTestId('param-password').fill('secret')
  await page.getByRole('button', { name: '执行 API' }).click()
  await page.getByTestId('execution-result').waitFor({ timeout: 15000 })
  await shot(page, `${viewportLabel}-04-run-result.png`)

  const history = page.getByTestId('execution-history')
  await history.getByText('api.user.login').first().waitFor({ timeout: 10000 })
  await page.getByTestId('filter-status').click()
  await page.getByTitle('success').click()
  await page.waitForTimeout(400)
  await shot(page, `${viewportLabel}-05-history-filtered.png`)

  await history.getByRole('button', { name: /查看记录/ }).first().click()
  await page.getByTestId('execution-detail').waitFor({ timeout: 10000 })
  await shot(page, `${viewportLabel}-06-execution-detail.png`)
  // 详情抽屉打开时检查横向溢出（390 视口关键点）
  const drawerScroll = await page.evaluate(() => document.documentElement.scrollWidth)
  const drawerClient = await page.evaluate(() => document.documentElement.clientWidth)
  const drawerOverflow = drawerScroll > drawerClient + 2
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: '返回项目列表' }).click()
  await page.getByText(projectName).waitFor({ timeout: 10000 })
  await shot(page, `${viewportLabel}-07-list.png`)

  const row = page.locator('.ant-table-row').filter({ hasText: projectName })
  await row.getByRole('button', { name: '编辑' }).click()
  const editDialog = page.getByRole('dialog').filter({ hasText: '编辑项目' })
  await editDialog.waitFor()
  await editDialog.getByLabel('项目名称').fill(`${projectName}-edited`)
  await editDialog.getByRole('button', { name: /确\s*定|OK/i }).click()
  await page.getByText(`${projectName}-edited`).waitFor({ timeout: 10000 })
  await shot(page, `${viewportLabel}-08-after-edit.png`)

  await page
    .getByRole('button', { name: new RegExp(`删除项目 ${projectName}-edited`) })
    .click()
  const delDialog = page.getByRole('dialog')
  await delDialog.waitFor()
  await delDialog.getByRole('button', { name: /删\s*除/ }).click()
  await page.waitForTimeout(1000)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(300)
  const okBtn = page.getByRole('button', { name: /确\s*定|OK/i })
  if (await okBtn.isVisible().catch(() => false)) {
    await okBtn.click().catch(() => {})
  }
  await page.keyboard.press('Escape')
  await shot(page, `${viewportLabel}-09-after-delete.png`)

  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
  const clientWidth = await page.evaluate(() => document.documentElement.clientWidth)
  const pageOverflow = scrollWidth > clientWidth + 2
  const overflow = pageOverflow || drawerOverflow

  const unexpectedConsole = consoleErrors.filter((t) => !isAllowedConsoleError(t))
  const unexpectedFailed = failedRequests.filter((e) => !isAllowedFailedRequest(e))

  return {
    viewportLabel,
    consoleErrors,
    pageErrors,
    failedRequests,
    unexpectedConsole,
    unexpectedPageErrors: pageErrors,
    unexpectedFailed,
    overflow,
    drawerOverflow,
    scrollWidth,
    clientWidth,
  }
}

const chromeCandidates = [
  process.env.PLAYWRIGHT_CHROME_PATH,
  path.join(
    process.env.HOME || '',
    'Library/Caches/ms-playwright/chromium-1228/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
  ),
].filter(Boolean)

let executablePath
for (const candidate of chromeCandidates) {
  if (candidate && fs.existsSync(candidate)) {
    executablePath = candidate
    break
  }
}

const browser = await chromium.launch({
  headless: true,
  ...(executablePath ? { executablePath } : {}),
})

const results = []
let gateFailed = false

for (const vp of [
  { label: 'desktop-1440x900', width: 1440, height: 900 },
  { label: 'mobile-390x844', width: 390, height: 844 },
]) {
  const context = await browser.newContext({
    viewport: { width: vp.width, height: vp.height },
  })
  const page = await context.newPage()
  try {
    const r = await runFlow(page, vp.label, makeProjectName(vp.label))
    results.push(r)
    const bad =
      r.overflow ||
      r.unexpectedConsole.length > 0 ||
      r.unexpectedPageErrors.length > 0 ||
      r.unexpectedFailed.length > 0
    if (bad) gateFailed = true
    console.log('RESULT', vp.label, JSON.stringify(r, null, 2))
  } catch (err) {
    await shot(page, `${vp.label}-ERROR.png`).catch(() => {})
    console.error('FAIL', vp.label, err)
    results.push({ viewportLabel: vp.label, error: String(err) })
    gateFailed = true
  }
  await context.close()
}

await browser.close()
const reportPath = path.join(OUT, 'e2e-report.json')
fs.writeFileSync(reportPath, JSON.stringify(results, null, 2))
console.log('DONE', reportPath)

if (gateFailed) {
  console.error('浏览器门禁失败：存在未允许的 console/page/failed request、横向溢出或流程异常')
  process.exit(1)
}
console.log('浏览器门禁通过')
