/**
 * Phase 3.3a 真实 Engine 身份展示截图（手册 §7-4.3/4.4，设计稿 B8：替代前端门禁中的 route mock）。
 *
 * 不使用任何 route mock：所有结果都来自 harness_real_matrix（真实 Engine）+ 本地回显 target，
 * Control 进程的环境变量里是假秘密，项目 config root 是脚本写在临时目录的 auth/test.yaml。
 *
 * 每张截图后对整页 DOM（HTML + innerText + 表单值）搜索假秘密，逐张写入 dom-secret-search.json；
 * 任一命中即失败。证据文件只记录命中次数，不记录任何秘密值。
 *
 * 环境变量：E2E_BASE_URL、E2E_OUT_DIR、E2E_AUTH_ASSETS_ROOT、E2E_AUTH_CONFIG_ROOT。
 */

import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'

const BASE = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173'
const OUT = path.resolve(process.env.E2E_OUT_DIR)
const ASSETS_ROOT = process.env.E2E_AUTH_ASSETS_ROOT
const CONFIG_ROOT = process.env.E2E_AUTH_CONFIG_ROOT
// 搜索目标：手册 §0.3-3 的假秘密 + 白名单外变量的假值；只用于 includes 判断，绝不输出
const FAKE_SECRETS = ['tp-fake-secret-9f31c2a7', 'tp-fake-partner-4c8e11d0', 'tp-fake-aws-7d2e9b10']

fs.mkdirSync(OUT, { recursive: true })

const VIEWPORTS = [
  { label: 'desktop-1440x900', width: 1440, height: 900 },
  { label: 'mobile-390x844', width: 390, height: 844 },
]

async function domSecretHits(page) {
  const html = await page.content()
  const text = await page.evaluate(() => document.body.innerText)
  const values = await page.evaluate(() =>
    Array.from(document.querySelectorAll('input, textarea')).map((el) => el.value).join('\n'),
  )
  const blob = `${html}\n${text}\n${values}`
  let hits = 0
  for (const secret of FAKE_SECRETS) hits += blob.split(secret).length - 1
  return hits
}

/** 截图 + DOM 搜索；fullPage=false 时只拍当前视口（用于“该元素必须在可视区域内”的场景）。 */
async function shot(page, ctx, name, { fullPage = true } = {}) {
  const file = path.join(OUT, `${ctx.label}-${name}.png`)
  await page.screenshot({ path: file, fullPage })
  const hits = await domSecretHits(page)
  ctx.dom.push({ screenshot: path.basename(file), dom_secret_hits: hits })
  console.log('screenshot', path.basename(file), 'dom_secret_hits', hits)
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
  await page.locator(`[data-asset-id="${assetId}"]`).click()
  await page.getByTestId(panelTestId).waitFor({ timeout: 10000 })
  await page.getByLabel('过滤资产').waitFor({ state: 'hidden', timeout: 3000 }).catch(() => {})
  await page.waitForTimeout(300)
}

async function runApi(page, filterText, assetId) {
  await selectAsset(page, filterText, assetId, 'api-execution-panel')
  await page.getByRole('button', { name: '执行 API' }).click()
}

async function expectMode(locator, mode) {
  await locator.waitFor({ timeout: 30000 })
  const got = await locator.getAttribute('data-auth-mode')
  if (got !== mode) throw new Error(`期望 data-auth-mode=${mode}，实际 ${got}`)
}

/** 展开 Case 步骤：折叠头里 step_id 以 code 呈现，按精确文本匹配（admin 与 admin_again 不混淆）。 */
async function expandStep(scope, stepId) {
  const header = scope
    .locator('.ant-collapse-header')
    .filter({ has: scope.page().locator('code', { hasText: new RegExp(`^${stepId}$`) }) })
    .first()
  if ((await header.getAttribute('aria-expanded')) !== 'true') await header.click()
  await scope.getByTestId(`step-auth-${stepId}`).first().waitFor({ timeout: 5000 })
}

async function inViewport(page, locator) {
  const box = await locator.boundingBox()
  const vp = page.viewportSize()
  return Boolean(box) && box.y >= 0 && box.y + box.height <= vp.height && box.x >= 0
}

async function runViewport(browser, vp) {
  const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height } })
  const page = await context.newPage()
  const ctx = { label: vp.label, dom: [], scenes: [] }
  const consoleErrors = []
  const failedRequests = []
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text())
  })
  page.on('response', (res) => {
    if (res.status() >= 400) failedRequests.push(`${res.status()} ${res.request().method()} ${res.url()}`)
  })

  const resp = await page.request.post(`${BASE}/api/projects`, {
    data: { name: `auth-real-${vp.label}-${Date.now()}`, env: 'test', assets_root: ASSETS_ROOT, config_root: CONFIG_ROOT },
  })
  if (!resp.ok()) throw new Error(`创建项目失败 HTTP ${resp.status()}`)
  const project = await resp.json()
  await page.goto(`${BASE}/projects/${project.id}`, { waitUntil: 'networkidle' })
  await page.getByTestId('project-workspace').waitFor({ timeout: 15000 })
  const result = () => page.getByTestId('execution-result').getByTestId('auth-summary')

  // 1) 单 API 有身份（admin，回显到非敏感键的凭证已被按值替换）
  await runApi(page, 'echo_admin', 'api.authm.echo_admin')
  await expectMode(result(), 'identity')
  await result().getByText('身份：admin').waitFor({ timeout: 10000 })
  await shot(page, ctx, 'auth-api-identity')
  ctx.scenes.push('api-identity')

  // 2) 匿名（auth: none，即使配置了 default_identity）
  await runApi(page, 'echo_none', 'api.authm.echo_none')
  await page.getByTestId('execution-result').getByTestId('auth-summary').getByText('匿名').waitFor({ timeout: 30000 })
  await expectMode(result(), 'anonymous')
  await shot(page, ctx, 'auth-api-anonymous')
  ctx.scenes.push('api-anonymous')

  // 3) header 覆盖：展开后可见被覆盖的资产头原始写法（小写 authorization）
  await runApi(page, 'echo_override', 'api.authm.echo_override')
  await result().getByTestId('auth-summary-overridden-flag').waitFor({ timeout: 30000 })
  await result().getByText('查看 header / Cookie 名').click()
  await page.getByTestId('auth-summary-overridden-headers').getByText('authorization').waitFor({ timeout: 5000 })
  await shot(page, ctx, 'auth-api-header-override')
  ctx.scenes.push('api-header-override')

  // 4) 身份不可用 422：文案原样来自真实 Engine 的 public_message
  await runApi(page, 'echo_missing', 'api.authm.echo_missing')
  await page.getByRole('alert').filter({ hasText: '执行失败' }).waitFor({ timeout: 10000 })
  await page.getByText(/TESTPLAT_MISSING_TOKEN/).first().waitFor({ timeout: 10000 })
  await shot(page, ctx, 'auth-api-identity-unavailable-422')
  ctx.scenes.push('api-identity-unavailable-422')

  // 5) Case 混合身份：admin / partner / 匿名 / 默认 / combo / admin / alias(匿名)
  await selectAsset(page, 'mixed', 'case.authm.mixed', 'case-execution-panel')
  await page.getByRole('button', { name: '执行 Case' }).click()
  await page.getByTestId('case-result-view').waitFor({ timeout: 30000 })
  const caseView = page.getByTestId('case-result-view')
  for (const stepId of ['admin', 'partner', 'anonymous']) {
    await expandStep(caseView, stepId)
  }
  await expectMode(page.getByTestId('step-auth-admin').first(), 'identity')
  await page.getByTestId('step-auth-partner').getByText('身份：partner').waitFor({ timeout: 5000 })
  await expectMode(page.getByTestId('step-auth-anonymous'), 'anonymous')
  await shot(page, ctx, 'auth-case-mixed-identities')
  ctx.scenes.push('case-mixed-identities')

  // 6) Case 系统错误步骤：auth 为 null 显示“—”，且必须在截图视口内（只拍视口，不拍整页）
  await selectAsset(page, 'syserror', 'case.authm.syserror', 'case-execution-panel')
  await page.getByRole('button', { name: '执行 Case' }).click()
  const located = page.getByTestId('case-system-error-located')
  await located.waitFor({ timeout: 45000 })
  const dash = located.getByTestId('step-auth-dead')
  if (!(await dash.isVisible().catch(() => false))) await expandStep(located, 'dead')
  await expectMode(dash, 'not_applicable')
  if ((await dash.innerText()).trim() !== '—') throw new Error('系统错误步骤应显示“—”')
  await dash.scrollIntoViewIfNeeded()
  // 往上留一点余量，让步骤标题与“身份 —”同屏
  await page.evaluate(() => window.scrollBy(0, -Math.round(window.innerHeight / 3)))
  await page.waitForTimeout(300)
  if (!(await inViewport(page, dash))) {
    await dash.scrollIntoViewIfNeeded()
    await page.waitForTimeout(200)
  }
  if (!(await inViewport(page, dash))) throw new Error('“—”步骤不在视口内')
  await shot(page, ctx, 'auth-case-system-error-dash', { fullPage: false })
  ctx.scenes.push('case-system-error-dash(in-viewport)')

  // 7) 历史详情：API（admin + 覆盖）与 Case（混合身份）
  await selectAsset(page, 'echo_override', 'api.authm.echo_override', 'api-execution-panel')
  await page.getByTestId('filter-asset-type').click()
  await page.getByTitle('api', { exact: true }).click()
  await page.waitForTimeout(500)
  // 最新的 API 记录是 echo_override（422 不保存记录）
  await page.getByTestId('execution-history').getByRole('button', { name: /查看记录/ }).first().click()
  const detail = page.getByTestId('execution-detail')
  await detail.getByText('身份：admin').waitFor({ timeout: 10000 })
  await detail.getByText('查看 header / Cookie 名').click()
  await detail.getByTestId('auth-summary-overridden-headers').getByText('authorization').waitFor({ timeout: 5000 })
  await shot(page, ctx, 'auth-history-api-detail')
  await page.keyboard.press('Escape')
  ctx.scenes.push('history-api-detail')

  // 历史列表按当前选中资产过滤：先选回 mixed Case，再切到 case 类型
  await selectAsset(page, 'mixed', 'case.authm.mixed', 'case-execution-panel')
  await page.getByTestId('filter-asset-type').click()
  await page.getByTitle('case', { exact: true }).click()
  await page.waitForTimeout(500)
  await page.getByTestId('execution-history').getByRole('button', { name: /查看记录/ }).first().click()
  const caseDetail = page.getByTestId('execution-detail')
  await expandStep(caseDetail, 'partner')
  await caseDetail.getByTestId('step-auth-partner').getByText('身份：partner').waitFor({ timeout: 10000 })
  await shot(page, ctx, 'auth-history-case-detail')
  await page.keyboard.press('Escape')
  ctx.scenes.push('history-case-detail')

  const allowedFailed = failedRequests.filter(
    (e) => !/^(422|502) POST .*\/(assets|cases)\/[^/]+\/run$/.test(e),
  )
  const allowedConsole = consoleErrors.filter(
    (t) => !(t.includes('Failed to load resource') && /422|502/.test(t)) && !t.includes('React DevTools'),
  )
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
  )
  await context.close()
  return { ...ctx, project_id: project.id, unexpectedFailed: allowedFailed, unexpectedConsole: allowedConsole, overflow }
}

const chromeCandidates = [
  process.env.PLAYWRIGHT_CHROME_PATH,
  path.join(process.env.HOME || '', 'Library/Caches/ms-playwright/chromium-1187/chrome-mac/Chromium.app/Contents/MacOS/Chromium'),
  path.join(
    process.env.HOME || '',
    'Library/Caches/ms-playwright/chromium-1228/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
  ),
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
].filter(Boolean)
const executablePath = chromeCandidates.find((c) => fs.existsSync(c))
const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) })

const report = { viewports: [], error: null }
let failed = false
for (const vp of VIEWPORTS) {
  try {
    const r = await runViewport(browser, vp)
    report.viewports.push(r)
    if (r.unexpectedFailed.length || r.unexpectedConsole.length || r.dom.some((d) => d.dom_secret_hits)) failed = true
  } catch (err) {
    // 只记录错误类型与 Playwright 的定位描述；页面里本就不应有秘密，且下面整体再自检一次
    report.error = `${vp.label}: ${String(err).split('\n')[0]}`
    console.error('FAIL', report.error)
    failed = true
    break
  }
}
await browser.close()

const domEvidence = {
  search_targets: FAKE_SECRETS.length,
  method: 'page.content() + body.innerText + input/textarea values，逐张截图搜索',
  screenshots: report.viewports.flatMap((v) => v.dom),
  total_hits: report.viewports.flatMap((v) => v.dom).reduce((n, d) => n + d.dom_secret_hits, 0),
}
const text = JSON.stringify(report, null, 2)
if (FAKE_SECRETS.some((s) => text.includes(s))) throw new Error('报告含秘密，拒绝写出')
fs.writeFileSync(path.join(OUT, 'auth-browser-report.json'), `${text}\n`)
fs.writeFileSync(path.join(OUT, 'dom-secret-search.json'), `${JSON.stringify(domEvidence, null, 2)}\n`)
console.log('DOM secret hits total', domEvidence.total_hits)
if (failed) {
  console.error('真实 Engine 身份截图失败')
  process.exit(1)
}
console.log('真实 Engine 身份截图通过')
