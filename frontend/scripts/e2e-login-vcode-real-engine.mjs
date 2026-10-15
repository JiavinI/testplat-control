/**
 * Phase 3.3c 真实 Engine：vcode_redis 登录成功 / Redis 不可达失败截图（390 / 1440）。
 * 输出：frontend/screenshots/phase3_3c-real-engine/
 * DOM 秘密搜索包含静态假秘密 + issued-secrets 动态目标。
 */
import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'

const BASE = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173'
const OUT = path.resolve(process.env.E2E_OUT_DIR)
const ASSETS_ROOT = process.env.E2E_LOGIN_ASSETS_ROOT
const CONFIG_ROOT = process.env.E2E_LOGIN_CONFIG_ROOT
const ISSUED_PATH = process.env.E2E_ISSUED_SECRETS_PATH || ''

const FAKE_SECRETS = [
  'tp-fake-secret-9f31c2a7',
  'tp-fake-partner-4c8e11d0',
  'tp-fake-aws-7d2e9b10',
  'tp-fake-buyer-pass-71c2',
  'tp-fake-seller-pass-93ab',
  'tp-fake-redis-pass-5e0d',
  'tp-fake-df-admin-pass-9f3a',
  'tp-fake-plugin-key-11aa',
  'plug-token-5f5f5f5f5f',
  'csrf-ff00ee11dd22',
  'seed-0a0b0c0d0e',
  'detail-0123456789abcdefghij',
]

function loadDynamicSecrets() {
  if (!ISSUED_PATH || !fs.existsSync(ISSUED_PATH)) return []
  const seen = new Set()
  const out = []
  for (const line of fs.readFileSync(ISSUED_PATH, 'utf8').split(/\r?\n/)) {
    const v = line.trim()
    if (!v || seen.has(v)) continue
    seen.add(v)
    out.push(v)
  }
  return out
}

fs.mkdirSync(OUT, { recursive: true })

const VIEWPORTS = [
  { label: 'desktop-1440x900', width: 1440, height: 900 },
  { label: 'mobile-390x844', width: 390, height: 844 },
]

function countSecretInBlob(blob, secret) {
  if (!secret) return 0
  if (secret.length >= 8) return blob.split(secret).length - 1
  // 短验证码：词边界，避免时间戳/端口/尺寸数字误报
  const escaped = secret.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const re = new RegExp(`(?<![0-9A-Za-z])${escaped}(?![0-9A-Za-z])`, 'g')
  return (blob.match(re) || []).length
}

async function domSecretHits(page, dynamicSecrets) {
  const html = await page.content()
  const text = await page.evaluate(() => document.body.innerText)
  const values = await page.evaluate(() =>
    Array.from(document.querySelectorAll('input, textarea')).map((el) => el.value).join('\n'),
  )
  const blob = `${html}\n${text}\n${values}`
  let hits = 0
  for (const secret of FAKE_SECRETS) hits += countSecretInBlob(blob, secret)
  for (const secret of dynamicSecrets) {
    if (secret.length < 4) continue
    hits += countSecretInBlob(blob, secret)
  }
  if (/tok-[a-z0-9]+-\d{4}-a8f3e2c1d0/.test(blob)) hits += 1
  if (/sess-\d{4}-7b7b7b7b/.test(blob)) hits += 1
  return hits
}

async function shot(page, ctx, name, dynamicSecrets) {
  const file = path.join(OUT, `${ctx.label}-${name}.png`)
  await page.screenshot({ path: file, fullPage: true })
  const hits = await domSecretHits(page, dynamicSecrets)
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

async function runViewport(browser, vp, dynamicSecrets) {
  const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height } })
  const page = await context.newPage()
  const ctx = { label: vp.label, dom: [], scenes: [] }

  const REPO = process.env.E2E_REPO || 'matrix'
  const PROJECT = process.env.E2E_PROJECT || 'vcode'
  await page.goto(`${BASE}/projects/${REPO}/${PROJECT}`, { waitUntil: 'networkidle' })
  await page.getByTestId('project-workspace').waitFor({ timeout: 15000 })

  // 1) vcode_redis 登录成功
  await runApi(page, 'df_admin_echo', 'api.login.df_admin_echo')
  await page.getByTestId('execution-result').waitFor({ timeout: 45000 })
  await page.getByText(/身份：df_admin|df_admin/).first().waitFor({ timeout: 15000 })
  await shot(page, ctx, 'vcode-redis-success', dynamicSecrets)
  ctx.scenes.push('vcode-success')

  // 2) Redis 不可达 → 登录失败
  await runApi(page, 'df_admin_dead_redis', 'api.login.df_admin_dead_redis_echo')
  await page.getByTestId('execution-result').waitFor({ timeout: 45000 })
  const failedBanner = page.getByTestId('login-failed-banner')
  if (await failedBanner.isVisible().catch(() => false)) {
    await failedBanner.waitFor()
  } else {
    await page.getByText(/登录失败|login_failed|transport/).first().waitFor({ timeout: 15000 })
  }
  await shot(page, ctx, 'vcode-redis-unreachable', dynamicSecrets)
  ctx.scenes.push('vcode-unreachable')

  await context.close()
  return { ...ctx, project_id: `${REPO}/${PROJECT}`, dynamic_secret_targets: dynamicSecrets.length }
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

const dynamicSecrets = loadDynamicSecrets()
const report = { viewports: [], error: null, dynamic_secret_targets: dynamicSecrets.length }
let failed = false
for (const vp of VIEWPORTS) {
  try {
    const r = await runViewport(browser, vp, dynamicSecrets)
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
  dynamic_search_targets: dynamicSecrets.length,
  method: 'page.content() + body.innerText + input/textarea values + token/session 形态 + issued-secrets',
  screenshots: report.viewports.flatMap((v) => v.dom),
  total_hits: report.viewports.flatMap((v) => v.dom).reduce((n, d) => n + d.dom_secret_hits, 0),
}
const text = JSON.stringify(report, null, 2)
if (FAKE_SECRETS.some((s) => text.includes(s))) throw new Error('报告含秘密，拒绝写出')
if (dynamicSecrets.some((s) => s.length >= 8 && text.includes(s))) throw new Error('报告含动态秘密，拒绝写出')
fs.writeFileSync(path.join(OUT, 'vcode-browser-report.json'), `${text}\n`)
fs.writeFileSync(path.join(OUT, 'dom-secret-search.json'), `${JSON.stringify(domEvidence, null, 2)}\n`)
console.log('DOM secret hits total', domEvidence.total_hits, 'dynamic_targets', dynamicSecrets.length)
if (failed) {
  console.error('真实 Engine vcode 截图失败')
  process.exit(1)
}
console.log('真实 Engine vcode 截图通过')
