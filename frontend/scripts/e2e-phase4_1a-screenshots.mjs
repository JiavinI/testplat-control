/**
 * Phase 4.1a：390 / 1440 截图。
 * 登录、环境管理、账号管理、运行选环境、历史中的操作人与配置版本。
 * 凭据输入使用密码框；截图发生在编辑框关闭之后。
 */
import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'
import { captureLoggedOut, submitPlatformAuth } from './platform-session.mjs'

const BASE = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173'
const OUT = path.resolve(process.env.E2E_OUT_DIR || 'screenshots/phase4_1a')
const REPO = process.env.E2E_REPO || 'assets'
const PROJECT = process.env.E2E_PROJECT || 'gsb'
const USER = process.env.E2E_USERNAME || 'shotop'
const PASS = process.env.E2E_PASSWORD || 'shot-pass-1'
const ACCOUNT_PASS = process.env.E2E_ACCOUNT_PASSWORD || 'gsb-pass-shot'
fs.mkdirSync(OUT, { recursive: true })

async function launch() {
  return chromium.launch({ headless: true })
}

async function shot(page, name) {
  const html = await page.content()
  for (const secret of [PASS, ACCOUNT_PASS]) {
    if (secret && html.includes(secret)) {
      throw new Error(`截图页含凭据原文: ${name}`)
    }
  }
  const file = path.join(OUT, `${name}.png`)
  await page.screenshot({ path: file, fullPage: true })
  return file
}

async function openProject(page) {
  await page.goto(`${BASE}/projects/${REPO}/${PROJECT}`, { waitUntil: 'networkidle' })
  await page.getByTestId('project-workspace').waitFor({ timeout: 20000 })
}

async function openConfig(page) {
  const manager = page.getByTestId('environment-manager')
  if (!(await manager.isVisible().catch(() => false))) {
    await page.getByText('环境与账号', { exact: true }).click()
  }
  await manager.waitFor({ timeout: 20000 })
}

async function createEnvironments(page) {
  await openConfig(page)
  for (const name of ['test', 'pre']) {
    await page.getByTestId('env-create-open').click()
    await page.getByRole('textbox', { name: '环境名', exact: true }).fill(name)
    await page.getByRole('textbox', { name: '服务名 1', exact: true }).fill('gsb')
    await page.getByRole('textbox', { name: '地址 1', exact: true }).fill('http://127.0.0.1:9')
    await page.getByRole('button', { name: '添加服务地址', exact: true }).click()
    await page.getByRole('textbox', { name: '服务名 2', exact: true }).fill('unified_login')
    await page.getByRole('textbox', { name: '地址 2', exact: true }).fill('http://127.0.0.1:9')
    await page.getByRole('textbox', { name: '超时（秒）', exact: true }).fill('5')
    await page.getByTestId('env-save').click()
    await page.getByTestId('env-editor').waitFor({ state: 'hidden', timeout: 20000 })
    await page.getByTestId('environment-table').getByText(name, { exact: true }).waitFor()
  }
}

async function createAccount(page) {
  await page.getByRole('tab', { name: '测试账号' }).click()
  await page.getByTestId('account-manager').waitFor()
  await page.getByTestId('account-create-open').click()
  await page.getByRole('textbox', { name: '账号名', exact: true }).fill('gsb')
  await page.getByRole('textbox', { name: '展示名', exact: true }).fill('采购员')
  await page.getByRole('textbox', { name: '业务角色', exact: true }).fill('商家')
  await page.getByTestId('login-profile-select').click()
  await page.locator('.ant-select-item-option').filter({ hasText: 'gsb_login' }).click()
  await page.getByTestId('credential-username').waitFor()
  await page.getByTestId('credential-username').fill('gsb-user-shot')
  await page.getByTestId('credential-password').fill(ACCOUNT_PASS)
  await page.getByTestId('account-save').click()
  await page.getByTestId('account-editor').waitFor({ state: 'hidden', timeout: 20000 })
  await page.getByTestId('account-table').getByText('gsb', { exact: true }).waitFor()
}

async function runBalance(page, narrow) {
  await page.waitForFunction(() => {
    const el = document.querySelector('[data-testid="workspace-env-select"]')
    return Boolean(el) && !el.className.includes('ant-select-disabled')
  })
  await page.getByTestId('workspace-env-select').click()
  const option = page.locator('.ant-select-item-option').filter({ hasText: /^test$/ })
  await option.waitFor()
  await page.screenshot({
    path: path.join(OUT, `${narrow ? 'mobile-390x844' : 'desktop-1440x900'}-run-env-select.png`),
    fullPage: false,
  })
  await option.click()
  if (narrow) {
    await page.getByRole('button', { name: '打开资产浏览' }).click()
  }
  const filter = page.getByLabel('过滤资产')
  await filter.fill('balance')
  const node = page.locator('[data-asset-id="api.gsb.account.balance"]')
  await node.first().waitFor({ timeout: 20000 })
  await node.first().click()
  if (narrow) {
    await page.keyboard.press('Escape')
  }
  await page.getByRole('button', { name: '执行 API' }).click()
  await page.getByTestId('run-result-operator').waitFor({ timeout: 20000 })
  const revision = page.getByTestId('run-result-config-revision')
  await revision.waitFor()
  if (!(await revision.innerText()).trim()) {
    throw new Error('运行结果缺少配置版本')
  }
}

async function showHistory(page) {
  const history = page.getByTestId('execution-history')
  await history.scrollIntoViewIfNeeded()
  const scroller = history.locator('.ant-table-content, .ant-table-body').first()
  if (await scroller.count()) {
    await scroller.evaluate((el) => {
      el.scrollLeft = el.scrollWidth
    })
  }
  await history.locator('[data-testid^="history-operator-"]').first().waitFor()
  await history.locator('[data-testid^="history-config-revision-"]').first().waitFor()
  await history.getByRole('button', { name: /查看记录/ }).first().click()
  await page.getByTestId('execution-detail').waitFor()
  await page.getByTestId('execution-detail').getByText('操作人', { exact: true }).waitFor()
  await page.getByTestId('execution-detail').getByText('配置版本', { exact: true }).waitFor()
}

async function runViewport(browser, vp, mode) {
  const context = await browser.newContext({ viewport: { width: vp.w, height: vp.h } })
  const page = await context.newPage()
  const prefix = vp.prefix
  const names = []

  await captureLoggedOut(page, BASE)
  names.push(await shot(page, `${prefix}-login`))
  await submitPlatformAuth(page, { username: USER, password: PASS, mode })

  await openProject(page)
  if (mode === 'register') {
    await createEnvironments(page)
    names.push(await shot(page, `${prefix}-environments`))
    await createAccount(page)
    names.push(await shot(page, `${prefix}-accounts`))
  } else {
    await openConfig(page)
    await page.getByTestId('environment-table').getByText('test', { exact: true }).waitFor()
    names.push(await shot(page, `${prefix}-environments`))
    await page.getByRole('tab', { name: '测试账号' }).click()
    await page.getByTestId('account-table').getByText('gsb', { exact: true }).waitFor()
    names.push(await shot(page, `${prefix}-accounts`))
  }

  await runBalance(page, vp.w < 768)
  names.push(path.join(OUT, `${prefix}-run-env-select.png`))
  names.push(await shot(page, `${prefix}-run-result`))
  await showHistory(page)
  names.push(await shot(page, `${prefix}-history`))

  await context.close()
  return names.map((file) => path.basename(file))
}

const browser = await launch()
try {
  const names = []
  const viewports = [
    { w: 1440, h: 900, prefix: 'desktop-1440x900', mode: 'register' },
    { w: 390, h: 844, prefix: 'mobile-390x844', mode: 'login' },
  ]
  for (const vp of viewports) {
    names.push(...(await runViewport(browser, vp, vp.mode)))
  }
  const manifest = { shots: names }
  fs.writeFileSync(path.join(OUT, 'phase4_1a-shots.json'), `${JSON.stringify(manifest, null, 2)}\n`)
  console.log(JSON.stringify(manifest))
} finally {
  await browser.close()
}
