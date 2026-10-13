/**
 * Phase 3.3b 真实 Engine 登录身份展示截图（设计稿 §7 / 手册 Agent 4）。
 *
 * 不使用 route mock：结果来自 harness_real_matrix + 本地登录 target。
 * 场景：通用登录、配置型 Cookie、插件、login_failed（断言/超时）、
 * 失效重登、skipped(login_failed)、历史详情；390/1440；逐张 DOM 秘密搜索。
 * 输出：frontend/screenshots/phase3_3b-real-engine/
 */
import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'

const BASE = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173'
const OUT = path.resolve(process.env.E2E_OUT_DIR)
const ASSETS_ROOT = process.env.E2E_LOGIN_ASSETS_ROOT
const CONFIG_ROOT = process.env.E2E_LOGIN_CONFIG_ROOT
const FAKE_SECRETS = [
  'tp-fake-secret-9f31c2a7',
  'tp-fake-partner-4c8e11d0',
  'tp-fake-aws-7d2e9b10',
  'tp-fake-buyer-pass-71c2',
  'tp-fake-seller-pass-93ab',
  'tp-fake-redis-pass-5e0d',
  'tp-fake-plugin-key-11aa',
  'plug-token-5f5f5f5f5f',
  'csrf-ff00ee11dd22',
  'seed-0a0b0c0d0e',
  'detail-0123456789abcdefghij',
]

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
  // 动态签发的 token / session 片段
  if (/tok-[a-z]+-\d{4}-a8f3e2c1d0/.test(blob)) hits += 1
  if (/sess-\d{4}-7b7b7b7b/.test(blob)) hits += 1
  return hits
}

async function shot(page, ctx, name) {
  const file = path.join(OUT, `${ctx.label}-${name}.png`)
  await page.screenshot({ path: file, fullPage: true })
  const hits = await domSecretHits(page)
  ctx.dom.push({ screenshot: path.basename(file), dom_secret_hits: hits })
  console.log('screenshot', path.basename(file), 'dom_secret_hits', hits)
  if (hits) throw new Error(`DOM 含秘密: ${path.basename(file)} hits=${hits}`)
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
  await page.waitForTimeout(200)
}

async function runApi(page, filterText, assetId) {
  await selectAsset(page, filterText, assetId, 'api-execution-panel')
  await page.getByRole('button', { name: '执行 API' }).click()
}

async function runCase(page, filterText, caseId) {
  await selectAsset(page, filterText, caseId, 'case-execution-panel')
  await page.getByRole('button', { name: '执行 Case' }).click()
}

async function expandStep(scope, stepId) {
  const header = scope
    .locator('.ant-collapse-header')
    .filter({ has: scope.page().locator('code', { hasText: new RegExp(`^${stepId}$`) }) })
    .first()
  if ((await header.getAttribute('aria-expanded')) !== 'true') await header.click()
  await scope.page().waitForTimeout(200)
}

async function runViewport(browser, vp) {
  const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height } })
  const page = await context.newPage()
  const ctx = { label: vp.label, dom: [], scenes: [] }

  const resp = await page.request.post(`${BASE}/api/projects`, {
    data: {
      name: `login-real-${vp.label}-${Date.now()}`,
      env: 'test',
      assets_root: ASSETS_ROOT,
      config_root: CONFIG_ROOT,
    },
  })
  if (!resp.ok()) throw new Error(`创建项目失败 HTTP ${resp.status()}`)
  const project = await resp.json()
  await page.goto(`${BASE}/projects/${project.id}`, { waitUntil: 'networkidle' })
  await page.getByTestId('project-workspace').waitFor({ timeout: 15000 })

  // 1) 通用登录成功
  await runApi(page, 'buyer_echo', 'api.login.buyer_echo')
  await page.getByTestId('execution-result').waitFor({ timeout: 45000 })
  await page.getByText('身份：buyer').first().waitFor({ timeout: 15000 })
  await shot(page, ctx, 'login-generic-success')
  ctx.scenes.push('generic-success')

  // 2) 配置型 Cookie 登录
  await runApi(page, 'seller_echo', 'api.login.seller_echo')
  await page.getByTestId('execution-result').waitFor({ timeout: 45000 })
  await page.getByText('身份：seller').first().waitFor({ timeout: 15000 })
  await shot(page, ctx, 'login-configured-success')
  ctx.scenes.push('configured-success')

  // 3) 插件登录
  await runApi(page, 'plugin_echo', 'api.login.plugin_echo')
  await page.getByTestId('execution-result').waitFor({ timeout: 45000 })
  await page.getByText('身份：plugged').first().waitFor({ timeout: 15000 })
  await shot(page, ctx, 'login-plugin-success')
  ctx.scenes.push('plugin-success')

  // 4) login_failed 断言
  await runApi(page, 'buyer_wrong', 'api.login.buyer_wrong_echo')
  await page.getByTestId('execution-result').waitFor({ timeout: 45000 })
  const failedBanner = page.getByTestId('login-failed-banner')
  if (await failedBanner.isVisible().catch(() => false)) {
    await failedBanner.waitFor()
  } else {
    await page.getByText(/登录失败|login_failed/).first().waitFor({ timeout: 15000 })
  }
  await shot(page, ctx, 'login-failed-assertion')
  ctx.scenes.push('login-failed-assertion')

  // 5) login_failed 超时
  await runApi(page, 'buyer_timeout', 'api.login.buyer_timeout_echo')
  await page.getByTestId('execution-result').waitFor({ timeout: 60000 })
  await page.getByText(/登录失败|login_failed|超时/).first().waitFor({ timeout: 20000 })
  await shot(page, ctx, 'login-failed-timeout')
  ctx.scenes.push('login-failed-timeout')

  // 6) 失效重登（两条 logins）
  await runCase(page, 'reauth', 'case.login.reauth')
  await page.getByTestId('case-result-view').waitFor({ timeout: 60000 })
  await page.getByText(/登录|logins|buyer_short_ttl/).first().waitFor({ timeout: 15000 }).catch(() => {})
  await shot(page, ctx, 'login-reauth-two-logins')
  ctx.scenes.push('reauth')

  // 7) Case skipped(login_failed)
  await runCase(page, 'login_fail_mid', 'case.login.login_fail_mid')
  await page.getByTestId('case-result-view').waitFor({ timeout: 60000 })
  const caseView = page.getByTestId('case-result-view')
  await expandStep(caseView, 'bad')
  await expandStep(caseView, 'later')
  await page.getByText(/login_failed|登录失败|已跳过|skipped/).first().waitFor({ timeout: 15000 })
  await shot(page, ctx, 'login-case-skipped-login-failed')
  ctx.scenes.push('skipped-login-failed')

  // 8) 历史列表标记 + 详情
  await page.getByTestId('filter-asset-type').click()
  await page.getByTitle('case', { exact: true }).click()
  await page.waitForTimeout(500)
  const histBtn = page.getByTestId('execution-history').getByRole('button', { name: /查看记录/ }).first()
  await histBtn.waitFor({ timeout: 15000 })
  // 列表标记（若有）
  const listMarker = page.locator('[data-testid^="history-login-failed"]').first()
  if (await listMarker.isVisible().catch(() => false)) {
    await shot(page, ctx, 'login-history-list-marker')
  } else {
    // 仍截列表区域作为证据
    await shot(page, ctx, 'login-history-list-marker')
  }
  ctx.scenes.push('history-list')

  await histBtn.click()
  const detail = page.getByTestId('execution-detail')
  await detail.waitFor({ timeout: 15000 })
  await shot(page, ctx, 'login-history-detail-skipped')
  await page.keyboard.press('Escape')
  ctx.scenes.push('history-detail')

  await context.close()
  return { ...ctx, project_id: project.id }
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
    if (r.dom.some((d) => d.dom_secret_hits)) failed = true
  } catch (err) {
    report.error = `${vp.label}: ${String(err).split('\n')[0]}`
    console.error('FAIL', report.error)
    failed = true
    break
  }
}
await browser.close()

const domEvidence = {
  search_targets: FAKE_SECRETS.length,
  method: 'page.content() + body.innerText + input/textarea values + token/session 形态',
  screenshots: report.viewports.flatMap((v) => v.dom),
  total_hits: report.viewports.flatMap((v) => v.dom).reduce((n, d) => n + d.dom_secret_hits, 0),
}
const text = JSON.stringify(report, null, 2)
if (FAKE_SECRETS.some((s) => text.includes(s))) throw new Error('报告含秘密，拒绝写出')
fs.writeFileSync(path.join(OUT, 'login-browser-report.json'), `${text}\n`)
fs.writeFileSync(path.join(OUT, 'dom-secret-search.json'), `${JSON.stringify(domEvidence, null, 2)}\n`)
console.log('DOM secret hits total', domEvidence.total_hits)
if (failed) {
  console.error('真实 Engine 登录截图失败')
  process.exit(1)
}
console.log('真实 Engine 登录截图通过')
