/**
 * Phase 2.5 浏览器门禁：联调截图 + 横向溢出 + console/page/failed request。
 * 截图写入 screenshots/phase2-5/，不覆盖 phase2-4 基线。
 *
 * 假设前端 http://127.0.0.1:5173 与后端 :8000 已启动（可用 FakeEngine）。
 *   pnpm exec node scripts/e2e-gate.mjs
 *
 * 允许：
 *   - POST /api/projects/:id/assets/:asset/run → 422（门禁主动注入的错误展示用例）
 *   - POST/PUT /api/projects → 409（项目名冲突，前端表单已展示 detail）
 *   - DELETE /api/projects/:id → 409（有执行记录不可删，前端已 message 提示）
 *   - 对应的 "Failed to load resource … 422/409" console
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
  : path.join(frontendRoot, 'screenshots', 'phase2-5')

fs.mkdirSync(OUT, { recursive: true })

function makeProjectName(suffix) {
  return `e2e-${Date.now()}-${suffix}`
}

function isAllowedFailedRequest(entry) {
  // 失败请求统一记录为“状态码 方法 URL”。
  const m = String(entry).match(/^(\d+)\s+(\S+)\s+(\S+)/)
  if (!m) return false
  const [, status, method, url] = m
  if (
    status === '422' &&
    method === 'POST' &&
    /\/api\/projects\/[^/?]+\/assets\/[^/?]+\/run$/.test(url)
  ) {
    return true
  }
  // 后端 #33：重名与有执行记录删除均为 409；UI 已展示 detail，不视为门禁失败。
  if (status === '409' && method === 'POST' && /\/api\/projects\/?$/.test(url)) {
    return true
  }
  if (status === '409' && method === 'PUT' && /\/api\/projects\/[^/?]+$/.test(url)) {
    return true
  }
  if (status === '409' && method === 'DELETE' && /\/api\/projects\/[^/?]+$/.test(url)) {
    return true
  }
  return false
}

function isAllowedConsoleError(text) {
  if (
    text.includes('Failed to load resource') &&
    (text.includes('422') || text.includes('409'))
  ) {
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

async function openAssetBrowser(page) {
  const filter = page.getByLabel('过滤资产')
  if (await filter.isVisible().catch(() => false)) {
    return
  }
  const button = page.getByRole('button', { name: '打开资产浏览' })
  if (await button.isVisible().catch(() => false)) {
    await button.click()
    await page.waitForTimeout(300)
  }
}

async function selectAsset(page, filterText, assetId) {
  await openAssetBrowser(page)
  const filter = page.getByLabel('过滤资产')
  await filter.waitFor({ timeout: 10000 })
  await filter.fill(filterText)
  await page.waitForTimeout(300)
  const node = page.locator(`[data-asset-id="${assetId}"]`)
  await node.waitFor({ timeout: 10000 })
  await node.click()
  await page.getByTestId('api-execution-panel').waitFor({ timeout: 10000 })
}

async function expectExecutionStatus(page, status) {
  const result = page.getByTestId('execution-result')
  await result.waitFor({ timeout: 15000 })
  await result.getByText(status, { exact: true }).waitFor({ timeout: 10000 })
}

async function findProjectRow(page, projectName) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const row = page
      .locator('.ant-table-row, [data-testid="project-row"]')
      .filter({ hasText: projectName })
    if ((await row.count()) > 0) {
      return row.first()
    }

    const next = page.locator('.ant-pagination-next')
    const nextClass = (await next.getAttribute('class').catch(() => '')) || ''
    if ((await next.count()) === 0 || nextClass.includes('ant-pagination-disabled')) {
      break
    }
    await next.click()
    await page.waitForTimeout(300)
  }
  throw new Error(`项目列表中未找到 ${projectName}`)
}

async function ensureExecutionProject(page, viewportLabel) {
  const projectName = `e2e-execution-${viewportLabel}`
  const listResponse = await page.request.get(`${BASE}/api/projects?limit=10000`)
  if (!listResponse.ok()) {
    throw new Error(`读取门禁执行项目失败：HTTP ${listResponse.status()}`)
  }
  const projects = await listResponse.json()
  const existing = projects.find((project) => project.name === projectName)
  if (existing) {
    return existing
  }

  // 执行记录会阻止项目删除，因此每个视口复用固定项目，避免门禁反复污染联调库。
  const createResponse = await page.request.post(`${BASE}/api/projects`, {
    data: {
      name: projectName,
      env: 'test',
      assets_root: ASSETS_ROOT,
      config_root: CONFIG_ROOT,
    },
  })
  if (!createResponse.ok()) {
    throw new Error(`创建门禁执行项目失败：HTTP ${createResponse.status()}`)
  }
  return createResponse.json()
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

  const executionProject = await ensureExecutionProject(page, viewportLabel)

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

  await page.getByRole('button', { name: '返回项目列表' }).click()
  await page.waitForURL((url) => url.pathname === '/projects', { timeout: 10000 })
  // HMR/抽屉动画下路由内容可能短暂滞后；重新进入同一路由后再验列表交互。
  await page.goto(`${BASE}/projects`, { waitUntil: 'networkidle' })
  const row = await findProjectRow(page, projectName)
  await shot(page, `${viewportLabel}-07-list.png`)

  await row.getByRole('button', { name: /工作台/ }).waitFor()
  await row.getByRole('button', { name: /编辑/ }).waitFor()
  await row.getByRole('button', { name: /删除/ }).waitFor()
  await row.getByRole('button', { name: /编辑/ }).click()
  const editDialog = page.getByRole('dialog').filter({ hasText: '编辑项目' })
  await editDialog.waitFor()
  const editedName = `${projectName}-edited`
  await editDialog.getByLabel('项目名称').fill(editedName)
  await editDialog.getByRole('button', { name: /确\s*定|OK/i }).click()
  await page.getByText(editedName).waitFor({ timeout: 10000 })
  await shot(page, `${viewportLabel}-08-after-edit.png`)

  const deleteButton = page.getByRole('button', {
    name: new RegExp(`删除项目 ${editedName}`),
  })
  await deleteButton.click()
  const delDialog = page.getByRole('dialog')
  await delDialog.waitFor()
  await delDialog.getByRole('button', { name: /删\s*除/ }).click()
  await deleteButton.waitFor({ state: 'detached', timeout: 10000 })
  await shot(page, `${viewportLabel}-09-after-delete.png`)

  await page.goto(`${BASE}/projects/${executionProject.id}`, { waitUntil: 'networkidle' })
  await page.getByTestId('project-workspace').waitFor({ timeout: 15000 })

  await openAssetBrowser(page)
  const filter = page.getByLabel('过滤资产')
  await filter.waitFor({ timeout: 10000 })
  await filter.fill('login')
  await page.waitForTimeout(300)
  await shot(page, `${viewportLabel}-02-asset-search.png`)

  // 无参数 API 必须能直接执行，证明动态表单不会把空参数误判为异常。
  await selectAsset(page, 'get_status', 'api.common.get_status')
  await page.getByTestId('params-empty').waitFor({ timeout: 10000 })
  await page.getByRole('button', { name: '执行 API' }).click()
  await expectExecutionStatus(page, 'success')

  await selectAsset(page, 'login', 'api.user.login')
  await shot(page, `${viewportLabel}-03-api-selected.png`)

  await page.getByTestId('param-username').fill('alice')

  // 用一次性 422 响应验证前端错误态；随后恢复真实后端继续验证业务 failed/success。
  const runPattern = '**/api/projects/*/assets/api.user.login/run'
  await page.route(runPattern, async (route) => {
    await route.fulfill({
      status: 422,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'password 参数不合法' }),
    })
  }, { times: 1 })
  await page.getByTestId('param-password').fill('invalid-for-422')
  await page.getByRole('button', { name: '执行 API' }).click()
  await page.getByRole('alert').filter({ hasText: '执行失败' }).waitFor({ timeout: 10000 })
  await page.getByText('password 参数不合法').waitFor({ timeout: 10000 })
  await page.unroute(runPattern)

  await page.getByTestId('param-password').fill('wrong-password')
  await page.getByRole('button', { name: '执行 API' }).click()
  await expectExecutionStatus(page, 'failed')

  await page.getByTestId('param-password').fill('secret')
  await page.getByRole('button', { name: '执行 API' }).click()
  await expectExecutionStatus(page, 'success')
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
