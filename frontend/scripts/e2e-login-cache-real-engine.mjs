/**
 * Phase 3.3d 真实 Engine：缓存复用 / 401 重登重发截图（390 / 1440）。
 * 用 API 触发执行后打开执行详情，避免移动端资产浏览点击不稳定。
 * 输出：frontend/screenshots/phase3_3d-real-engine/
 */
import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'

const BASE = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173'
const OUT = path.resolve(process.env.E2E_OUT_DIR)
const ASSETS_ROOT = process.env.E2E_LOGIN_ASSETS_ROOT
const CONFIG_ROOT = process.env.E2E_LOGIN_CONFIG_ROOT
const TARGET = process.env.E2E_TARGET_URL || process.env.MATRIX_TARGET_URL || 'http://127.0.0.1:18099'
const ISSUED_PATH = process.env.E2E_ISSUED_SECRETS_PATH || ''

const FAKE_SECRETS = [
  'tp-fake-secret-9f31c2a7',
  'tp-fake-partner-4c8e11d0',
  'tp-fake-aws-7d2e9b10',
  'tp-fake-buyer-pass-71c2',
  'tp-fake-buyer-pass-ALT99',
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
  const escaped = secret.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const quoted = new RegExp(`['"]${escaped}['"]`, 'g')
  const kv = new RegExp(`[=:]\\s*${escaped}(?![0-9A-Za-z])`, 'g')
  return (blob.match(quoted) || []).length + (blob.match(kv) || []).length
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

async function targetConfig(page, payload) {
  const resp = await page.request.post(`${TARGET}/__inspect/config`, { data: payload })
  if (!resp.ok()) throw new Error(`target config HTTP ${resp.status()}`)
}

async function targetReset(page) {
  const resp = await page.request.post(`${TARGET}/__inspect/reset`)
  if (!resp.ok()) throw new Error(`target reset HTTP ${resp.status()}`)
}

async function runAsset(page, repo, project, assetId) {
  const resp = await page.request.post(
    `${BASE}/api/repos/${repo}/projects/${project}/assets/${assetId}/run`,
    {
      data: { params: {}, env: process.env.E2E_ENV || 'test' },
      timeout: 120000,
    },
  )
  if (!resp.ok()) throw new Error(`run ${assetId} HTTP ${resp.status()}`)
  return resp.json()
}

async function openLatestApiDetail(page, repo, project) {
  await page.goto(`${BASE}/projects/${repo}/${project}`, { waitUntil: 'networkidle' })
  await page.getByTestId('project-workspace').waitFor({ timeout: 20000 })
  const history = page.getByTestId('execution-history')
  await history.waitFor({ timeout: 20000 })
  // 确保筛到 API
  const typeFilter = page.getByTestId('filter-asset-type')
  if (await typeFilter.isVisible().catch(() => false)) {
    await typeFilter.click()
    await page.getByTitle('api', { exact: true }).click().catch(() => {})
    await page.waitForTimeout(400)
  }
  const histBtn = history.getByRole('button', { name: /查看记录/ }).first()
  await histBtn.waitFor({ timeout: 20000 })
  await histBtn.click()
  await page.getByTestId('execution-detail').waitFor({ timeout: 20000 })
}

async function runViewport(browser, vp, dynamicSecrets) {
  const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height } })
  const page = await context.newPage()
  const ctx = { label: vp.label, dom: [], scenes: [] }

  const REPO = process.env.E2E_REPO || 'matrix'
  const PROJECT = process.env.E2E_PROJECT || 'cache'

  // 1) 暖缓存
  await targetConfig(page, { always_401: false, force_login_fail: false, clear_revoked: true })
  await targetReset(page)
  await runAsset(page, REPO, PROJECT, 'api.login.buyer_cached_echo')

  // 2) 缓存命中
  await runAsset(page, REPO, PROJECT, 'api.login.buyer_cached_echo')
  await openLatestApiDetail(page, REPO, PROJECT)
  await page.getByText('复用登录（未重新登录）').first().waitFor({ timeout: 15000 })
  await shot(page, ctx, 'cache-reuse', dynamicSecrets)
  ctx.scenes.push('cache-reuse')

  // 3) 吊销 → 401 重登
  await targetConfig(page, { revoke_current_token: true })
  await targetReset(page)
  await runAsset(page, REPO, PROJECT, 'api.login.buyer_cached_echo')
  await openLatestApiDetail(page, REPO, PROJECT)
  await page.getByText('鉴权失效，已重新登录并重发').first().waitFor({ timeout: 15000 })
  await shot(page, ctx, 'reauth-resend', dynamicSecrets)
  ctx.scenes.push('reauth-resend')

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
fs.writeFileSync(path.join(OUT, 'login-cache-browser-report.json'), `${text}\n`)
fs.writeFileSync(path.join(OUT, 'dom-secret-search.json'), `${JSON.stringify(domEvidence, null, 2)}\n`)
console.log('DOM secret hits total', domEvidence.total_hits, 'dynamic_targets', dynamicSecrets.length)
if (failed) {
  console.error('真实 Engine cache 截图失败')
  process.exit(1)
}
console.log('真实 Engine cache 截图通过')
