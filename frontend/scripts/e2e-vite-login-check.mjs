/**
 * 默认 Vite 入口上的注册、登录、保存环境和注销。
 * 状态码写入 E2E_OUT。页面或错误信息里不保留密码。
 */
import { chromium } from 'playwright'
import fs from 'node:fs'

const BASE = process.env.E2E_BASE_URL
const OUT = process.env.E2E_OUT
const USER = process.env.E2E_USERNAME
const PASS = process.env.E2E_PASSWORD
const REPO = process.env.E2E_REPO || 'main'
const PROJECT = process.env.E2E_PROJECT || 'demo'

const report = {
  browser_register: null,
  browser_login: null,
  browser_config_save: null,
  browser_logout: null,
}

function note(response) {
  const url = response.url()
  const method = response.request().method()
  if (method === 'POST' && url.endsWith('/api/auth/register')) {
    report.browser_register = response.status()
  } else if (method === 'POST' && url.endsWith('/api/auth/login')) {
    report.browser_login = response.status()
  } else if (method === 'POST' && url.endsWith('/api/auth/logout')) {
    report.browser_logout = response.status()
  } else if (method === 'POST' && url.includes('/environments')) {
    const path = new URL(url).pathname
    if (path.endsWith('/environments')) {
      report.browser_config_save = response.status()
    }
  }
}

function redact(text) {
  return String(text).split(PASS).join('[redacted]').slice(0, 300)
}

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
page.on('response', note)

try {
  await page.goto(`${BASE}/projects`, { waitUntil: 'networkidle' })
  await page.getByTestId('login-page').waitFor({ timeout: 20000 })
  await page.getByRole('tab', { name: '注册' }).click()
  await page.getByTestId('auth-username').fill(USER)
  await page.getByTestId('auth-password').fill(PASS)
  await page.getByTestId('auth-submit').click()
  await page.getByTestId('current-operator').waitFor({ timeout: 20000 })

  await page.getByTestId('logout-button').click()
  await page.getByTestId('login-page').waitFor({ timeout: 20000 })

  await page.getByTestId('auth-username').fill(USER)
  await page.getByTestId('auth-password').fill(PASS)
  await page.getByTestId('auth-submit').click()
  await page.getByTestId('current-operator').waitFor({ timeout: 20000 })

  const sync = await page.request.post(`${BASE}/api/repos/${REPO}/sync`)
  if (!sync.ok()) {
    throw new Error(`sync_http_${sync.status()}`)
  }

  await page.goto(`${BASE}/projects/${REPO}/${PROJECT}`, { waitUntil: 'networkidle' })
  await page.getByTestId('project-workspace').waitFor({ timeout: 20000 })
  const manager = page.getByTestId('environment-manager')
  if (!(await manager.isVisible().catch(() => false))) {
    await page.getByText('环境与账号', { exact: true }).click()
  }
  await manager.waitFor({ timeout: 20000 })
  await page.getByTestId('env-create-open').click()
  await page.getByRole('textbox', { name: '环境名', exact: true }).fill('lab')
  await page.getByRole('textbox', { name: '服务名 1', exact: true }).fill('local')
  await page.getByRole('textbox', { name: '地址 1', exact: true }).fill('http://127.0.0.1:9')
  await page.getByTestId('env-save').click()
  await page.getByTestId('env-editor').waitFor({ state: 'hidden', timeout: 20000 })
  await page.getByTestId('environment-table').getByText('lab', { exact: true }).waitFor()

  await page.getByTestId('logout-button').click()
  await page.getByTestId('login-page').waitFor({ timeout: 20000 })
  const visible = page.getByTestId('login-error')
  if (await visible.isVisible().catch(() => false)) {
    throw new Error(`visible_error:${await visible.innerText()}`)
  }
  fs.writeFileSync(OUT, `${JSON.stringify(report, null, 2)}\n`)
} catch (error) {
  report.error = redact(error && error.message ? error.message : error)
  fs.writeFileSync(OUT, `${JSON.stringify(report, null, 2)}\n`)
  process.exitCode = 1
} finally {
  await browser.close()
}
