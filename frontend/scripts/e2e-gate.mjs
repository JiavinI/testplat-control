/**
 * Phase 3 浏览器门禁：Case 元信息/运行/历史 + API 回归 + 横向溢出 + console/网络。
 * 截图写入 screenshots/phase3/；Phase 3.3a 身份相关截图写入 screenshots/phase3_3/
 * （设置 E2E_OUT_DIR 时两者都写入该目录）。
 *
 * Phase 3.3a 身份段：用 Agent 2 冻结的 docs/phase3_3/examples/ 作为 route mock 响应，
 * 覆盖“有身份 / 匿名 / header 覆盖 / 身份不可用 422 / 系统错误步骤显示 —”，
 * 并在每个截图点对整页 DOM 搜索测试假秘密，命中即门禁失败。
 *
 * 假设前端 http://127.0.0.1:5173 与后端 :8000 已启动（可用 FakeEngine）。
 *   pnpm exec node scripts/e2e-gate.mjs
 *
 * 允许：
 *   - POST .../assets/.../run → 422（门禁主动注入）
 *   - POST .../cases/.../run → 422 / 5xx（门禁主动注入：preflight / 系统错误）
 *   - POST/PUT /api/projects → 409
 *   - DELETE /api/projects/:id → 409
 *   - 对应 Failed to load resource console
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
  : path.join(frontendRoot, 'screenshots', 'phase3')

const AUTH_OUT = process.env.E2E_OUT_DIR
  ? OUT
  : path.join(frontendRoot, 'screenshots', 'phase3_3')
const EXAMPLES_DIR = path.join(repoRoot, 'docs', 'phase3_3', 'examples')
// 测试用假秘密：只作为 DOM 泄密搜索目标，绝不写进任何 mock 响应
const FAKE_SECRETS = ['tp-fake-secret-9f31c2a7', 'tp-fake-partner-4c8e11d0']

fs.mkdirSync(OUT, { recursive: true })
fs.mkdirSync(AUTH_OUT, { recursive: true })

function loadExample(name) {
  return JSON.parse(fs.readFileSync(path.join(EXAMPLES_DIR, name), 'utf8'))
}

/** 整页 DOM（含 Drawer 等 portal）搜索假秘密，返回命中的项。 */
async function findSecretsInDom(page) {
  const html = await page.content()
  const text = await page.evaluate(() => document.body.innerText)
  return FAKE_SECRETS.filter((secret) => html.includes(secret) || text.includes(secret))
}

async function authShot(page, name, secretHits) {
  const file = path.join(AUTH_OUT, name)
  await page.screenshot({ path: file, fullPage: true })
  console.log('screenshot', file)
  const hits = await findSecretsInDom(page)
  if (hits.length > 0) {
    secretHits.push({ screenshot: name, hits: hits.length })
  }
  return file
}

function makeProjectName(suffix) {
  return `e2e-${Date.now()}-${suffix}`
}

function isAllowedFailedRequest(entry) {
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
  if (
    method === 'POST' &&
    /\/api\/projects\/[^/?]+\/cases\/[^/?]+\/run$/.test(url) &&
    ['422', '500', '502', '504'].includes(status)
  ) {
    return true
  }
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
    (text.includes('422') ||
      text.includes('409') ||
      text.includes('500') ||
      text.includes('502') ||
      text.includes('504'))
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

  // --- API 回归 ---
  await selectAsset(page, 'get_status', 'api.common.get_status', 'api-execution-panel')
  await page.getByTestId('params-empty').waitFor({ timeout: 10000 })
  await page.getByRole('button', { name: '执行 API' }).click()
  await expectExecutionStatus(page, 'success')

  await selectAsset(page, 'login', 'api.user.login', 'api-execution-panel')
  await shot(page, `${viewportLabel}-03-api-selected.png`)

  await page.getByTestId('param-username').fill('alice')
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
  const drawerScroll = await page.evaluate(() => document.documentElement.scrollWidth)
  const drawerClient = await page.evaluate(() => document.documentElement.clientWidth)
  const drawerOverflow = drawerScroll > drawerClient + 2
  await page.keyboard.press('Escape')

  const secretHits = []
  const authOverflow = await runAuthFlow(page, viewportLabel, executionProject, secretHits)

  // --- Case 体验 ---
  await selectAsset(
    page,
    'create_then_get',
    'case.demo.create_then_get',
    'case-execution-panel',
  )
  await page.getByTestId('case-meta-panel').waitFor({ timeout: 10000 })
  await page.getByText('case.demo.create_then_get').first().waitFor({ timeout: 5000 })
  // 无 tags / 步骤预览
  // 说明文案可提及 tags/步骤；禁止出现 YAML 键值预览或标签 chip 列表
  const metaRoot = page.getByTestId('case-meta-panel')
  if (await metaRoot.locator('.ant-tag').filter({ hasText: 'smoke' }).count()) {
    throw new Error('Case 元信息面板不应渲染资产 tags')
  }
  const metaText = await metaRoot.innerText()
  if (/^steps:\s*$/m.test(metaText) || metaText.includes('schema_version:')) {
    throw new Error('Case 元信息面板不应渲染 YAML 步骤预览')
  }
  await shot(page, `${viewportLabel}-case-meta.png`)

  // success（FakeEngine 默认成功）
  await page.getByRole('button', { name: '执行 Case' }).click()
  await page.getByTestId('case-result-view').waitFor({ timeout: 15000 })
  await page.getByText(/成功（success）/).first().waitFor({ timeout: 5000 })
  await shot(page, `${viewportLabel}-case-success.png`)

  // failed + skipped（注入 200 业务失败响应）
  const caseRunPattern = '**/api/projects/*/cases/case.demo.create_then_get/run'
  await page.route(caseRunPattern, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        record_id: 'e2e-case-failed',
        status: 'failed',
        duration: 0.01,
        result: {
          case_id: 'case.demo.create_then_get',
          status: 'failed',
          duration_seconds: 0.01,
          steps: [
            {
              step_id: 'bad_assert',
              name: null,
              type: 'api',
              status: 'failed',
              duration_seconds: 0.01,
              request: { method: 'GET', url: 'http://127.0.0.1/status' },
              response: { status_code: 200, body: { ok: true } },
              error: {
                kind: 'assertion',
                message: '断言失败: 响应不符合成功条件',
                stage: null,
                step_id: null,
                path: null,
              },
              output: null,
              skip_reason: null,
            },
            {
              step_id: 'after',
              name: null,
              type: 'api',
              status: 'skipped',
              duration_seconds: 0,
              request: null,
              response: null,
              error: null,
              output: null,
              skip_reason: 'fail_fast',
            },
          ],
          summary: { total: 2, success: 0, failed: 1, skipped: 1 },
          error: null,
        },
      }),
    })
  }, { times: 1 })
  await page.getByRole('button', { name: '执行 Case' }).click()
  await page.getByTestId('first-failed-marker').waitFor({ timeout: 10000 })
  await page.getByText(/已跳过（skipped）/).waitFor({ timeout: 5000 })
  await shot(page, `${viewportLabel}-case-failed.png`)
  await page.unroute(caseRunPattern)

  // 422 预检失败（route mock，仅 Fake UI 门禁）
  await page.route(caseRunPattern, async (route) => {
    await route.fulfill({
      status: 422,
      contentType: 'application/json',
      body: JSON.stringify({ detail: '步骤 only 引用未声明或尚未产生的 alias' }),
    })
  }, { times: 1 })
  await page.getByRole('button', { name: '执行 Case' }).click()
  await page.getByText(/预检失败/).waitFor({ timeout: 10000 })
  await shot(page, `${viewportLabel}-case-preflight-422.png`)
  await page.unroute(caseRunPattern)

  // 5xx + 定位历史
  await page.route(caseRunPattern, async (route) => {
    await route.fulfill({
      status: 504,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'API 请求超时' }),
    })
  }, { times: 1 })
  const listPattern = '**/api/projects/*/execution-records?**'
  await page.route(listPattern, async (route) => {
    const url = route.request().url()
    if (url.includes('asset_type=case') && url.includes('status=failed')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 'e2e-case-timeout',
            asset_id: 'case.demo.create_then_get',
            status: 'failed',
            start_time: '2026-10-12T11:30:00',
            duration: 0.2,
          },
        ]),
      })
      return
    }
    await route.continue()
  })
  await page.route('**/api/projects/*/case-execution-records/e2e-case-timeout', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'e2e-case-timeout',
        project_id: executionProject.id,
        asset_id: 'case.demo.create_then_get',
        asset_type: 'case',
        status: 'failed',
        start_time: '2026-10-12T11:30:00',
        end_time: '2026-10-12T11:30:00.200',
        duration: 0.2,
        display: {
          start_time: '2026-10-12 11:30:00',
          end_time: '2026-10-12 11:30:00',
          duration: '200ms',
        },
        result: {
          case_id: 'case.demo.create_then_get',
          status: 'failed',
          duration_seconds: 0.2,
          steps: [
            {
              step_id: 'slow',
              name: null,
              type: 'api',
              status: 'failed',
              duration_seconds: 0.2,
              request: null,
              response: null,
              error: {
                kind: 'timeout',
                message: 'API 请求超时',
                stage: 'execution',
                step_id: null,
                path: null,
              },
              output: null,
              skip_reason: null,
            },
          ],
          summary: { total: 1, success: 0, failed: 1, skipped: 0 },
          error: { kind: 'timeout', stage: 'execution', message: 'API 请求超时' },
        },
      }),
    })
  })
  await page.getByRole('button', { name: '执行 Case' }).click()
  await page.getByTestId('case-system-error-located').waitFor({ timeout: 15000 })
  await shot(page, `${viewportLabel}-case-system-error.png`)
  await page.unroute(caseRunPattern)
  await page.unroute(listPattern)
  await page.unroute('**/api/projects/*/case-execution-records/e2e-case-timeout')

  // 旧格式仍可点运行（不禁用）；用 legacy case 触发 422
  await selectAsset(page, 'legacy_v1', 'case.demo.legacy_v1', 'case-execution-panel')
  const legacyBtn = page.getByRole('button', { name: '执行 Case' })
  if (await legacyBtn.isDisabled()) {
    throw new Error('旧格式 Case 不应预先禁用运行按钮')
  }
  await page.route('**/api/projects/*/cases/case.demo.legacy_v1/run', async (route) => {
    await route.fulfill({
      status: 422,
      contentType: 'application/json',
      body: JSON.stringify({ detail: '旧格式/不受支持的 Case 资产' }),
    })
  }, { times: 1 })
  await legacyBtn.click()
  await page.getByText(/预检失败/).waitFor({ timeout: 10000 })
  await shot(page, `${viewportLabel}-case-legacy-422.png`)

  // Case 历史详情
  await selectAsset(
    page,
    'create_then_get',
    'case.demo.create_then_get',
    'case-execution-panel',
  )
  await page.getByTestId('filter-asset-type').click()
  await page.getByTitle('case', { exact: true }).click()
  await page.waitForTimeout(400)
  await page.getByTestId('filter-status').click()
  await page.getByTitle('全部状态').click().catch(() => {})
  // 打开任一 case 记录（若列表因 mock 清空，先跑一次真实 success）
  const caseHistory = page.getByTestId('execution-history')
  const detailButtons = caseHistory.getByRole('button', { name: /查看记录/ })
  if ((await detailButtons.count()) === 0) {
    await page.getByRole('button', { name: '执行 Case' }).click()
    await page.getByTestId('case-result-view').waitFor({ timeout: 15000 })
    await page.waitForTimeout(500)
  }
  await caseHistory.getByRole('button', { name: /查看记录/ }).first().click()
  await page.getByTestId('execution-detail').waitFor({ timeout: 10000 })
  await shot(page, `${viewportLabel}-history-case.png`)
  await page.keyboard.press('Escape')

  // 旧 API 详情回归
  await page.getByTestId('filter-asset-type').click()
  await page.getByTitle('api', { exact: true }).click()
  await page.waitForTimeout(400)
  await selectAsset(page, 'login', 'api.user.login', 'api-execution-panel')
  await page.getByTestId('execution-history').getByRole('button', { name: /查看记录/ }).first().click()
  await page.getByTestId('execution-detail').waitFor({ timeout: 10000 })
  await shot(page, `${viewportLabel}-history-api.png`)
  await page.keyboard.press('Escape')

  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
  const clientWidth = await page.evaluate(() => document.documentElement.clientWidth)
  const pageOverflow = scrollWidth > clientWidth + 2
  const overflow = pageOverflow || drawerOverflow || authOverflow

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
    authOverflow,
    secretHits,
    scrollWidth,
    clientWidth,
  }
}

async function hasHorizontalOverflow(page) {
  return page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
  )
}

/**
 * Phase 3.3a 身份展示门禁。前置：已选中 api.user.login（执行面板可见）；结束时回到 api.user.login。
 * 只用冻结示例与后端返回的 detail 文案，不在脚本里另造错误文案。
 */
async function runAuthFlow(page, viewportLabel, executionProject, secretHits) {
  let overflow = false
  const authErrors = loadExample('auth-error-responses.json')

  // 1) 匿名：FakeEngine 在无 auth 配置的项目下真实执行，auth 为 null
  await page.getByTestId('param-password').fill('secret')
  await page.getByRole('button', { name: '执行 API' }).click()
  await expectExecutionStatus(page, 'success')
  const anon = page.getByTestId('execution-result').getByTestId('auth-summary')
  await anon.waitFor({ timeout: 10000 })
  if ((await anon.getAttribute('data-auth-mode')) !== 'anonymous') {
    throw new Error('无 auth 配置的单 API 结果应显示“匿名”')
  }
  await authShot(page, `${viewportLabel}-auth-api-anonymous.png`, secretHits)

  // 2) 有身份 + header 覆盖：冻结示例 api-run-with-auth.json（admin，覆盖 authorization）
  const runPattern = '**/api/projects/*/assets/api.user.login/run'
  await page.route(runPattern, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(loadExample('api-run-with-auth.json')),
    })
  }, { times: 1 })
  await page.getByRole('button', { name: '执行 API' }).click()
  const identity = page.getByTestId('execution-result').getByTestId('auth-summary')
  await identity.getByText('身份：admin').waitFor({ timeout: 10000 })
  await authShot(page, `${viewportLabel}-auth-api-identity.png`, secretHits)
  await identity.getByText('查看 header 名').click()
  await page.getByTestId('auth-summary-overridden-headers').getByText('authorization').waitFor({ timeout: 5000 })
  await page.getByTestId('auth-summary-header-names').getByText('Authorization').waitFor({ timeout: 5000 })
  overflow = overflow || (await hasHorizontalOverflow(page))
  await authShot(page, `${viewportLabel}-auth-api-header-override.png`, secretHits)
  await page.unroute(runPattern)

  // 3) 身份不可用 422：detail 取自冻结示例，前端须原样展示
  const unavailable = authErrors.identity_unavailable
  await page.route(runPattern, async (route) => {
    await route.fulfill({
      status: unavailable.status,
      contentType: 'application/json',
      body: JSON.stringify(unavailable.body),
    })
  }, { times: 1 })
  await page.getByRole('button', { name: '执行 API' }).click()
  await page.getByRole('alert').filter({ hasText: '执行失败' }).waitFor({ timeout: 10000 })
  await page.getByText(unavailable.body.detail).waitFor({ timeout: 10000 })
  await authShot(page, `${viewportLabel}-auth-api-identity-unavailable-422.png`, secretHits)
  await page.unroute(runPattern)

  // 4) API 历史详情：冻结示例 api-history-detail-with-auth.json
  const apiDetail = loadExample('api-history-detail-with-auth.json')
  apiDetail.project_id = executionProject.id
  const apiListPattern = '**/api/projects/*/execution-records?**'
  await page.route(apiListPattern, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: apiDetail.id,
          asset_id: apiDetail.asset_id,
          status: apiDetail.status,
          start_time: apiDetail.start_time,
          duration: apiDetail.duration,
        },
      ]),
    })
  })
  const apiDetailPattern = `**/api/projects/*/execution-records/${apiDetail.id}`
  await page.route(apiDetailPattern, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(apiDetail) })
  })
  // 切换筛选触发列表重新请求，命中上面的 mock
  await page.getByTestId('filter-status').click()
  await page.getByTitle('全部状态').click()
  await page.waitForTimeout(400)
  await page.getByTestId('execution-history').getByRole('button', { name: /查看记录/ }).first().click()
  const detail = page.getByTestId('execution-detail')
  await detail.getByText('身份：admin').waitFor({ timeout: 10000 })
  await detail.getByText('查看 header 名').click()
  overflow = overflow || (await hasHorizontalOverflow(page))
  await authShot(page, `${viewportLabel}-auth-history-api-identity.png`, secretHits)
  await page.keyboard.press('Escape')
  await page.unroute(apiListPattern)
  await page.unroute(apiDetailPattern)

  // 5) Case：冻结示例 case-run-with-auth.json（每步 partner）
  await selectAsset(page, 'create_then_get', 'case.demo.create_then_get', 'case-execution-panel')
  const caseRunPattern = '**/api/projects/*/cases/case.demo.create_then_get/run'
  await page.route(caseRunPattern, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(loadExample('case-run-with-auth.json')),
    })
  }, { times: 1 })
  await page.getByRole('button', { name: '执行 Case' }).click()
  await page.getByTestId('case-result-view').waitFor({ timeout: 15000 })
  await page.getByText('步骤 create').first().click()
  await page.getByTestId('step-auth-create').getByText('身份：partner').waitFor({ timeout: 5000 })
  await authShot(page, `${viewportLabel}-auth-case-identity.png`, secretHits)
  await page.unroute(caseRunPattern)

  // 6) Case 身份不可用 422（身份不存在示例）
  const notFound = authErrors.identity_not_found
  await page.route(caseRunPattern, async (route) => {
    await route.fulfill({
      status: notFound.status,
      contentType: 'application/json',
      body: JSON.stringify(notFound.body),
    })
  }, { times: 1 })
  await page.getByRole('button', { name: '执行 Case' }).click()
  await page.getByText(/预检失败/).waitFor({ timeout: 10000 })
  await page.getByText(notFound.body.detail).waitFor({ timeout: 10000 })
  await authShot(page, `${viewportLabel}-auth-case-identity-not-found-422.png`, secretHits)
  await page.unroute(caseRunPattern)

  // 7) Case 系统错误步骤：auth 为 null 必须显示“—”而不是“匿名”（设计稿 A4）
  const base = loadExample('case-history-detail-with-auth.json')
  const sysDetail = {
    ...base,
    id: 'e2e-auth-case-timeout',
    project_id: executionProject.id,
    status: 'failed',
    result: {
      ...base.result,
      status: 'failed',
      steps: [
        base.result.steps[0],
        {
          ...base.result.steps[1],
          status: 'failed',
          request: null,
          response: null,
          output: null,
          auth: null,
          error: { kind: 'timeout', stage: 'execution', message: 'API 请求超时', step_id: null, path: null },
        },
      ],
      summary: { total: 2, success: 1, failed: 1, skipped: 0 },
      error: { kind: 'timeout', stage: 'execution', message: 'API 请求超时' },
    },
  }
  const caseListPattern = '**/api/projects/*/execution-records?**'
  await page.route(caseListPattern, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: sysDetail.id,
          asset_id: sysDetail.asset_id,
          status: 'failed',
          start_time: sysDetail.start_time,
          duration: sysDetail.duration,
        },
      ]),
    })
  })
  const caseDetailPattern = `**/api/projects/*/case-execution-records/${sysDetail.id}`
  await page.route(caseDetailPattern, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(sysDetail) })
  })
  await page.getByTestId('filter-status').click()
  await page.getByTitle('failed', { exact: true }).click()
  await page.waitForTimeout(400)
  await page.getByTestId('execution-history').getByRole('button', { name: /查看记录/ }).first().click()
  const caseDetail = page.getByTestId('execution-detail')
  const dash = caseDetail.getByTestId('step-auth-get')
  await dash.waitFor({ timeout: 10000 })
  if ((await dash.getAttribute('data-auth-mode')) !== 'not_applicable' || (await dash.innerText()).includes('匿名')) {
    throw new Error('系统错误步骤的身份应显示“—”，不得显示“匿名”')
  }
  await caseDetail.getByText('步骤 create').click()
  await caseDetail.getByTestId('step-auth-create').getByText('身份：partner').waitFor({ timeout: 5000 })
  overflow = overflow || (await hasHorizontalOverflow(page))
  await authShot(page, `${viewportLabel}-auth-case-system-error-dash.png`, secretHits)
  await page.keyboard.press('Escape')
  await page.unroute(caseListPattern)
  await page.unroute(caseDetailPattern)
  await page.getByTestId('filter-status').click()
  await page.getByTitle('全部状态').click().catch(() => {})
  await page.waitForTimeout(300)

  // 回到 api.user.login，恢复既有 Case 段的前置状态（移动端重复点同一资产不会关闭抽屉）；
  // 等资产抽屉关闭动画结束，避免下一次 openAssetBrowser 误判抽屉仍打开
  await selectAsset(page, 'login', 'api.user.login', 'api-execution-panel')
  await page.getByLabel('过滤资产').waitFor({ state: 'hidden', timeout: 5000 }).catch(() => {})
  await page.waitForTimeout(600)
  return overflow
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
      (r.secretHits && r.secretHits.length > 0) ||
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
