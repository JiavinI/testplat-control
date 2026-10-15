/**
 * Phase 4.0 §7-10：390 / 1440 截图 — 项目列表（同步）、环境选择、历史 env+SHA
 */
import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'

const BASE = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173'
const OUT = path.resolve(process.env.E2E_OUT_DIR || 'screenshots/phase4_0')
const REPO = process.env.E2E_REPO || 'main'
const PROJECT = process.env.E2E_PROJECT || 'demo'
const BACKEND = process.env.E2E_BACKEND || 'http://127.0.0.1:8000'
fs.mkdirSync(OUT, { recursive: true })

const CHROME_CANDIDATES = [
  process.env.PLAYWRIGHT_CHROME_PATH,
  path.join(process.env.HOME || '', 'Library/Caches/ms-playwright/chromium-1187/chrome-mac/Chromium.app/Contents/MacOS/Chromium'),
  path.join(process.env.HOME || '', 'Library/Caches/ms-playwright/chromium-1091/chrome-mac/Chromium.app/Contents/MacOS/Chromium'),
].filter(Boolean)

async function launch() {
  for (const exe of CHROME_CANDIDATES) {
    if (exe && fs.existsSync(exe)) {
      return chromium.launch({ headless: true, executablePath: exe })
    }
  }
  return chromium.launch({ headless: true })
}

async function shot(page, name) {
  const file = path.join(OUT, `${name}.png`)
  await page.screenshot({ path: file, fullPage: true })
  return file
}

async function ensureHistory(page) {
  // 选 env=test，跑一次 api 以便历史有 env+SHA
  await page.goto(`${BASE}/projects/${REPO}/${PROJECT}`, { waitUntil: 'networkidle' })
  await page.getByTestId('project-workspace').waitFor({ timeout: 20000 })
  const envSelect = page.getByTestId('workspace-env-select')
  if (await envSelect.isVisible().catch(() => false)) {
    await envSelect.click()
    await page.getByTitle('test', { exact: true }).click().catch(async () => {
      await page.locator('.ant-select-item-option').filter({ hasText: /^test$/ }).click()
    })
  }
  // 点开一个 api 并运行
  const filter = page.getByLabel('过滤资产')
  if (await filter.isVisible().catch(() => false)) {
    await filter.fill('health')
    await page.waitForTimeout(300)
  }
  const node = page.locator('[data-asset-id="api.common.health_check"]')
  if (await node.count()) {
    await node.first().click()
    const runBtn = page.getByRole('button', { name: /运行|执行/ }).first()
    if (await runBtn.isVisible().catch(() => false)) {
      await runBtn.click()
      await page.waitForTimeout(1500)
    }
  } else {
    // API 兜底：直接打运行接口
    await page.request.post(
      `${BASE}/api/repos/${REPO}/projects/${PROJECT}/assets/api.common.health_check/run`,
      { data: { env: 'test', params: {} }, timeout: 60000 },
    )
    await page.reload({ waitUntil: 'networkidle' })
  }
}

async function runViewport(browser, vp) {
  const context = await browser.newContext({ viewport: { width: vp.w, height: vp.h } })
  const page = await context.newPage()
  const prefix = vp.prefix

  // 1) 项目列表含同步
  await page.goto(`${BASE}/projects`, { waitUntil: 'networkidle' })
  await page.getByTestId('project-list-grouped').waitFor({ timeout: 20000 }).catch(() => {})
  // 同步按钮
  const syncBtn = page.getByTestId(`sync-repo-${REPO}`)
  if (await syncBtn.isVisible().catch(() => false)) {
    await syncBtn.click()
    await page.waitForTimeout(1200)
  } else {
    const fallback = page.getByRole('button', { name: /同步/ }).first()
    if (await fallback.isVisible().catch(() => false)) {
      await fallback.click()
      await page.waitForTimeout(1200)
    }
  }
  await shot(page, `${prefix}-project-list-sync`)

  // 2) 环境选择
  await page.goto(`${BASE}/projects/${REPO}/${PROJECT}`, { waitUntil: 'networkidle' })
  await page.getByTestId('project-workspace').waitFor({ timeout: 20000 })
  const envSelect = page.getByTestId('workspace-env-select')
  if (await envSelect.isVisible().catch(() => false)) {
    await envSelect.click()
    await page.waitForTimeout(400)
  }
  await shot(page, `${prefix}-env-select`)
  // 收起下拉
  await page.keyboard.press('Escape').catch(() => {})

  // 3) 历史 env + SHA
  await ensureHistory(page)
  const history = page.getByTestId('execution-history')
  await history.waitFor({ timeout: 20000 }).catch(() => {})
  await shot(page, `${prefix}-history-env-sha`)

  await context.close()
  return [`${prefix}-project-list-sync`, `${prefix}-env-select`, `${prefix}-history-env-sha`]
}

const browser = await launch()
try {
  const names = []
  for (const vp of [
    { w: 390, h: 844, prefix: 'mobile-390x844' },
    { w: 1440, h: 900, prefix: 'desktop-1440x900' },
  ]) {
    names.push(...(await runViewport(browser, vp)))
  }
  fs.writeFileSync(
    path.join(OUT, 'screenshot-manifest.json'),
    JSON.stringify({ ok: true, files: names.map((n) => `${n}.png`) }, null, 2) + '\n',
  )
  console.log(JSON.stringify({ ok: true, files: names }))
} finally {
  await browser.close()
}
