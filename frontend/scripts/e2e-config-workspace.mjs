/** Isolated browser acceptance: all API traffic uses synthetic fixtures; no preview DB access. */
import { chromium } from 'playwright'
import fs from 'node:fs'
import assert from 'node:assert/strict'

const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173'
const out = process.env.E2E_OUT_DIR || '/tmp/testplat-config-workspace'
fs.mkdirSync(out, { recursive: true })
const longUrl = `https://api.example.invalid/${'long-path/'.repeat(15)}`
const project = {
  id: 'demo/gsb', repo: 'demo', project: 'gsb', name: 'GO2 的 GSB',
  envs: ['test', 'pre'], default_env: 'test', archived: false, commit_sha: 'abcdef0',
  created_at: '2026-10-18T00:00:00Z', updated_at: '2026-10-18T00:00:00Z',
  workspace: { platform: 'gsb', platform_name: 'GSB', project: 'go2', project_name: 'GO2', configuration_project_id: 'demo/gsb' },
}
const envs = [
  { env: 'test', enabled: true, api_hosts: { gsb: longUrl, unified_login: 'https://login.example.invalid', portal: 'https://web.example.invalid', gsb_web: 'https://gsb.example.invalid', custom: 'https://custom.example.invalid' }, timeout_seconds: 15, case_params: { keyword: 'demo' }, revision: 1, updated_by: 'demo-user' },
  { env: 'pre', enabled: false, api_hosts: { gsb: 'https://pre.example.invalid' }, timeout_seconds: 30, case_params: {}, revision: 1, updated_by: 'demo-user' },
]
const account = { account_name: 'gsb.b1.primary', login_username: '演示账号', display_name: null, business_role: null, login_profile: 'gsb_login', enabled: true, revision: 1, updated_by: 'demo-user' }
const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const errors = []
const unexpected = []
let saved = false
page.on('pageerror', (e) => errors.push(e.name))
await page.route((url) => url.pathname.startsWith('/api/') || url.pathname === '/projects' || url.pathname.startsWith('/auth/') || url.pathname.startsWith('/repos/'), async (route) => {
  const path = new URL(route.request().url()).pathname.replace(/^\/api/, '')
  const method = route.request().method()
  let data
  if (path === '/auth/me') data = { username: 'demo-user' }
  else if (path === '/projects') data = [project]
  else if (path.endsWith('/environments') && method === 'GET') data = envs
  else if (path.endsWith('/environments/test') && method === 'PUT') {
    const body = route.request().postDataJSON()
    assert.equal(body.revision, 1)
    assert.equal(body.api_hosts.custom, 'https://custom.example.invalid')
    assert.deepEqual(body.case_params, { keyword: 'demo' })
    Object.assign(envs[0], body, { revision: 2 })
    data = envs[0]
    saved = true
  } else if (path.endsWith('/accounts')) data = [account]
  else {
    unexpected.push(`${method} ${path}`)
    await route.fulfill({ status: 500, json: { detail: 'Unconfigured fixture' } })
    return
  }
  await route.fulfill({ json: data })
})
const chooseEnv = async (name) => {
  await page.getByTestId('environment-select').locator('.ant-select-selector').click()
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option').filter({ hasText: name }).click()
}
const noOverflow = async () => assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false)
const stableDialog = async () => page.waitForFunction(() => {
  const dialog = document.querySelector('.ant-modal')
  if (!dialog) return false
  const style = getComputedStyle(dialog)
  return style.opacity === '1' && style.transform === 'none' && dialog.getBoundingClientRect().width >= 350
})
try {
  await page.goto(`${base}/configuration/demo/gsb?tab=environments`)
  await page.getByText(longUrl, { exact: true }).waitFor()
  assert.equal(await page.getByTestId('env-editor').count(), 0)
  await noOverflow()
  await page.screenshot({ path: `${out}/environment-desktop.png`, fullPage: true, animations: 'disabled' })
  await chooseEnv('pre')
  await page.getByText('https://pre.example.invalid', { exact: true }).waitFor()
  assert.equal(await page.getByText(longUrl, { exact: true }).count(), 0)
  await chooseEnv('test')
  await page.getByTestId('env-edit-test').click()
  await page.getByLabel('地址 1', { exact: true }).waitFor()
  await stableDialog()
  assert.equal(await page.getByLabel('地址 1', { exact: true }).inputValue(), longUrl)
  assert.equal(await page.getByLabel('地址 1', { exact: true }).evaluate((el) => el.scrollWidth > el.clientWidth + 1), false)
  await page.screenshot({ path: `${out}/environment-editor-desktop.png`, fullPage: true })
  await page.getByTestId('env-save').click()
  await page.getByTestId('env-editor').waitFor({ state: 'hidden' })
  assert(saved)
  await page.setViewportSize({ width: 390, height: 844 })
  await noOverflow()
  await page.getByTestId('env-edit-test').click()
  await page.getByLabel('地址 1', { exact: true }).waitFor()
  await stableDialog()
  await noOverflow()
  assert.equal(await page.getByLabel('地址 1', { exact: true }).evaluate((el) => el.scrollWidth > el.clientWidth + 1), false)
  await page.screenshot({ path: `${out}/environment-editor-mobile.png` })
  await page.getByTestId('env-cancel').click()
  await page.getByRole('tab', { name: '测试账号', exact: true }).click()
  await page.getByText('演示账号', { exact: true }).waitFor()
  await noOverflow()
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.screenshot({ path: `${out}/accounts-desktop.png`, fullPage: true, animations: 'disabled' })
  assert.deepEqual(errors, [])
  assert.deepEqual(unexpected, [])
  const report = { api: 'synthetic fixtures only', environment_switch: true, full_url: true, save_preserves_other_hosts_and_params: saved, mobile_no_overflow: true, username_visible: true, page_errors: errors.length }
  fs.writeFileSync(`${out}/report.json`, JSON.stringify(report, null, 2))
  console.log(JSON.stringify(report))
} catch (error) {
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true })
  console.error(JSON.stringify({ unexpected, page_errors: errors, title: await page.title(), url: page.url() }))
  throw error
} finally {
  await context.close()
  await browser.close()
}
