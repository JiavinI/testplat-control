/**
 * 真实 Engine 浏览器矩阵（失败 / 422 / 5xx / legacy 不得走 route mock）。
 *
 * 前提：
 *   - 本地 target 在 127.0.0.1:18099（scripts/local_target_server.py）
 *   - Control：harness_real_matrix:app @ :8000（短超时 + PackageEngineAdapter）
 *   - 前端：pnpm dev @ :5173
 *   - 项目资产/配置指向 tests/fixtures/{assets,config}，且 config 取 E2E_CONFIG_ROOT（脚本生成的临时目录，local=target 端口）
 *
 * 串行执行；5xx 后按 asset_type=case + asset_id + status=failed 定位最近失败记录，
 * 不依赖并发下不可靠的假设。
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
const CONFIG_ROOT = process.env.E2E_CONFIG_ROOT || path.join(repoRoot, 'tests', 'fixtures', 'config')
const OUT = process.env.E2E_OUT_DIR
  ? path.resolve(process.env.E2E_OUT_DIR)
  : path.join(frontendRoot, 'screenshots', 'phase3-real-engine')

fs.mkdirSync(OUT, { recursive: true })

function isAllowedFailedRequest(entry) {
  const m = String(entry).match(/^(\d+)\s+(\S+)\s+(\S+)/)
  if (!m) return false
  const [, status, method, url] = m
  if (
    method === 'POST' &&
    /\/api\/projects\/[^/?]+\/cases\/[^/?]+\/run$/.test(url) &&
    ['422', '500', '502', '504'].includes(status)
  ) {
    return true
  }
  if (status === '409' && /\/api\/projects/.test(url)) return true
  return false
}

function isAllowedConsoleError(text) {
  if (
    text.includes('Failed to load resource') &&
    (text.includes('422') ||
      text.includes('409') ||
      text.includes('500') ||
      text.includes('502') ||
      text.includes('504'))
  ) {
    return true
  }
  if (text.includes('Download the React DevTools')) return true
  return false
}

async function shot(page, name) {
  const file = path.join(OUT, name)
  await page.screenshot({ path: file, fullPage: true })
  console.log('screenshot', file)
  return file
}

async function openAssetBrowser(page) {
  const filter = page.getByLabel('过滤资产')
  if (await filter.isVisible().catch(() => false)) return
  const button = page.getByRole('button', { name: '打开资产浏览' })
  if (await button.isVisible().catch(() => false)) {
    await button.click()
    await page.waitForTimeout(300)
  }
}

async function selectAsset(page, filterText, assetId, panelTestId) {
  await openAssetBrowser(page)
  const filter = page.getByLabel('过滤资产')
  await filter.waitFor({ timeout: 10000 })
  await filter.fill(filterText)
  await page.waitForTimeout(300)
  const node = page.locator(`[data-asset-id="${assetId}"]`)
  await node.waitFor({ timeout: 10000 })
  await node.click()
  await page.getByTestId(panelTestId).waitFor({ timeout: 10000 })
}

async function createProject(page, name) {
  const resp = await page.request.post(`${BASE}/api/projects`, {
    data: {
      name,
      env: 'test',
      assets_root: ASSETS_ROOT,
      config_root: CONFIG_ROOT,
    },
  })
  if (!resp.ok()) {
    throw new Error(`创建项目失败 HTTP ${resp.status()}: ${await resp.text()}`)
  }
  return resp.json()
}

async function runMatrix(page) {
  const consoleErrors = []
  const pageErrors = []
  const failedRequests = []
  const evidence = []

  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text())
  })
  page.on('pageerror', (err) => pageErrors.push(err.message || String(err)))
  page.on('response', (res) => {
    if (res.status() >= 400) {
      failedRequests.push(`${res.status()} ${res.request().method()} ${res.url()}`)
    }
  })

  const projectName = `real-engine-matrix-${Date.now()}`
  const project = await createProject(page, projectName)
  evidence.push({ step: 'create_project', id: project.id })

  await page.goto(`${BASE}/projects/${project.id}`, { waitUntil: 'networkidle' })
  await page.getByTestId('project-workspace').waitFor({ timeout: 15000 })

  // --- success：真实 Engine ---
  await selectAsset(
    page,
    'create_then_get',
    'case.demo.create_then_get',
    'case-execution-panel',
  )
  await page.getByRole('button', { name: '执行 Case' }).click()
  await page.getByTestId('case-result-view').waitFor({ timeout: 30000 })
  await page.getByText(/成功（success）/).first().waitFor({ timeout: 10000 })
  await shot(page, 'real-case-success.png')
  evidence.push({ step: 'success', ok: true })

  // --- 业务 failed：真实 Engine（无 mock）---
  await selectAsset(page, 'assert_failed', 'case.demo.assert_failed', 'case-execution-panel')
  await page.getByRole('button', { name: '执行 Case' }).click()
  await page.getByTestId('first-failed-marker').waitFor({ timeout: 30000 })
  await page.getByText(/已跳过（skipped）/).waitFor({ timeout: 10000 })
  await shot(page, 'real-case-failed.png')
  evidence.push({ step: 'assertion_failed', ok: true })

  // --- 422 preflight：undeclared alias（真实 Engine）---
  await selectAsset(
    page,
    'undeclared_alias',
    'case.demo.undeclared_alias',
    'case-execution-panel',
  )
  await page.getByRole('button', { name: '执行 Case' }).click()
  await page.getByText(/预检失败/).waitFor({ timeout: 15000 })
  await shot(page, 'real-case-preflight-422.png')
  evidence.push({ step: 'preflight_422', ok: true })

  // --- legacy 422：真实 Engine ---
  await selectAsset(page, 'legacy_v1', 'case.demo.legacy_v1', 'case-execution-panel')
  const legacyBtn = page.getByRole('button', { name: '执行 Case' })
  if (await legacyBtn.isDisabled()) {
    throw new Error('旧格式 Case 不应预先禁用运行按钮')
  }
  await legacyBtn.click()
  await page.getByText(/预检失败/).waitFor({ timeout: 15000 })
  await shot(page, 'real-case-legacy-422.png')
  evidence.push({ step: 'legacy_422', ok: true })

  // --- 5xx transport → 串行定位历史（无 mock、无并发干扰）---
  await selectAsset(page, 'transport', 'case.demo.transport', 'case-execution-panel')
  // 先清掉该 Case 的失败记录干扰：本项目是新建的，应为空。
  const beforeList = await page.request.get(
    `${BASE}/api/projects/${project.id}/execution-records?asset_type=case&asset_id=case.demo.transport&status=failed`,
  )
  const beforeItems = await beforeList.json()
  if (beforeItems.length !== 0) {
    throw new Error(`transport 失败列表在执行前应为空，实际 ${beforeItems.length}`)
  }
  await page.getByRole('button', { name: '执行 Case' }).click()
  await page.getByTestId('case-system-error-located').waitFor({ timeout: 45000 })
  await shot(page, 'real-case-system-error-transport.png')
  const afterList = await page.request.get(
    `${BASE}/api/projects/${project.id}/execution-records?asset_type=case&asset_id=case.demo.transport&status=failed&order_by=-start_time&limit=5`,
  )
  const afterItems = await afterList.json()
  if (afterItems.length !== 1) {
    throw new Error(`串行 transport 后失败记录应恰好 1 条，实际 ${afterItems.length}`)
  }
  const detail = await page.request.get(
    `${BASE}/api/projects/${project.id}/case-execution-records/${afterItems[0].id}`,
  )
  const detailBody = await detail.json()
  if (detailBody.result?.error?.kind !== 'transport') {
    throw new Error(`期望 transport，得到 ${JSON.stringify(detailBody.result?.error)}`)
  }
  evidence.push({
    step: 'transport_502_serial_locate',
    record_id: afterItems[0].id,
    ok: true,
  })

  // --- 5xx timeout → 串行定位（短超时 harness）---
  await selectAsset(page, 'timeout', 'case.demo.timeout', 'case-execution-panel')
  await page.getByRole('button', { name: '执行 Case' }).click()
  await page.getByTestId('case-system-error-located').waitFor({ timeout: 45000 })
  await shot(page, 'real-case-system-error-timeout.png')
  const timeoutList = await page.request.get(
    `${BASE}/api/projects/${project.id}/execution-records?asset_type=case&asset_id=case.demo.timeout&status=failed&order_by=-start_time&limit=5`,
  )
  const timeoutItems = await timeoutList.json()
  if (timeoutItems.length !== 1) {
    throw new Error(`串行 timeout 后失败记录应恰好 1 条，实际 ${timeoutItems.length}`)
  }
  const timeoutDetail = await (
    await page.request.get(
      `${BASE}/api/projects/${project.id}/case-execution-records/${timeoutItems[0].id}`,
    )
  ).json()
  if (timeoutDetail.result?.error?.kind !== 'timeout') {
    throw new Error(`期望 timeout，得到 ${JSON.stringify(timeoutDetail.result?.error)}`)
  }
  evidence.push({
    step: 'timeout_504_serial_locate',
    record_id: timeoutItems[0].id,
    ok: true,
  })

  // --- 历史详情：打开 success 记录 ---
  await selectAsset(
    page,
    'create_then_get',
    'case.demo.create_then_get',
    'case-execution-panel',
  )
  await page.getByTestId('filter-asset-type').click()
  await page.getByTitle('case', { exact: true }).click()
  await page.waitForTimeout(400)
  await page
    .getByTestId('execution-history')
    .getByRole('button', { name: /查看记录/ })
    .first()
    .click()
  await page.getByTestId('execution-detail').waitFor({ timeout: 10000 })
  await shot(page, 'real-history-case.png')
  await page.keyboard.press('Escape')
  evidence.push({ step: 'history_detail', ok: true })

  const unexpectedConsole = consoleErrors.filter((t) => !isAllowedConsoleError(t))
  const unexpectedFailed = failedRequests.filter((e) => !isAllowedFailedRequest(e))
  return { evidence, unexpectedConsole, unexpectedFailed, pageErrors, failedRequests }
}

const chromeCandidates = [
  process.env.PLAYWRIGHT_CHROME_PATH,
  path.join(
    process.env.HOME || '',
    'Library/Caches/ms-playwright/chromium-1187/chrome-mac/Chromium.app/Contents/MacOS/Chromium',
  ),
  path.join(
    process.env.HOME || '',
    'Library/Caches/ms-playwright/chromium-1228/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
  ),
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
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
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await context.newPage()

let gateFailed = false
let result
try {
  result = await runMatrix(page)
  if (
    result.unexpectedConsole.length ||
    result.unexpectedFailed.length ||
    result.pageErrors.length
  ) {
    gateFailed = true
  }
  console.log('EVIDENCE', JSON.stringify(result, null, 2))
} catch (err) {
  await shot(page, 'real-ERROR.png').catch(() => {})
  console.error('FAIL', err)
  result = { error: String(err) }
  gateFailed = true
}

await browser.close()
const reportPath = path.join(OUT, 'real-engine-matrix-report.json')
fs.writeFileSync(reportPath, JSON.stringify(result, null, 2))
console.log('DONE', reportPath)

if (gateFailed) {
  console.error('真实 Engine 浏览器矩阵失败')
  process.exit(1)
}
console.log('真实 Engine 浏览器矩阵通过')
