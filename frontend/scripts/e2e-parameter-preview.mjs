/** Synthetic API fixtures only: no preview DB, credentials, or real target requests. */
import { chromium } from 'playwright'
import fs from 'node:fs'
import assert from 'node:assert/strict'

const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173'
const out = process.env.E2E_OUT_DIR || '/tmp/testplat-parameter-preview'
fs.mkdirSync(out, { recursive: true })
const project = {
  id: 'demo/gsb', repo: 'demo', project: 'gsb', name: 'GO2 的 GSB', envs: ['test', 'pre'], default_env: 'test', archived: false, commit_sha: 'abcdef0',
  created_at: '2026-10-18T00:00:00Z', updated_at: '2026-10-18T00:00:00Z',
  workspace: { platform: 'gsb', platform_name: 'GSB', project: 'go2', project_name: 'GO2', configuration_project_id: 'demo/gsb' },
}
const defaults = { keyword: '资产示例值', count: 0, active: false }
const params = [
  { name: 'keyword', type: 'string', required: true, description: '商品关键字' },
  { name: 'count', type: 'number', required: true, description: '数量' },
  { name: 'active', type: 'boolean', required: false, description: '是否启用' },
]
const envs = ['test', 'pre'].map((env) => ({ env, enabled: true, api_hosts: { local: 'https://example.invalid' }, timeout_seconds: 15, case_params: { keyword: `${env} 环境值` }, revision: 1, updated_by: 'demo-user' }))
const api = { id: 'api.demo.preview', name: 'preview.yaml', type: 'file', path: 'api/demo/preview.yaml', metadata: { name: '参数预览演示', method: 'POST', host: 'local', url: '/echo', auth: 'none', request: { type: 'json', body: { keyword: '${keyword}', count: '${count}', active: '${active}' } } } }
const scenario = { id: 'case.demo.preview', name: 'preview.case.yaml', type: 'file', path: 'scenarios/demo/preview.case.yaml', metadata: { params: { keyword: '场景示例值', filter: { a: 1, b: 2 }, active: true } } }
const tree = { id: 'assets', name: 'assets', type: 'directory', path: '.', children: [
  { id: 'api', name: 'api', type: 'directory', path: 'api', children: [api] },
  { id: 'scenarios', name: 'scenarios', type: 'directory', path: 'scenarios', children: [scenario] },
] }
const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const errors = []
const unexpected = []
const submitted = []
const parameterSets = new Map()
const parameterKey = (kind, id, scope, env) => `${kind}:${id}:${scope}:${scope === 'asset_default' ? '' : env}`
const stateFor = (kind, id, scope, env) => parameterSets.get(parameterKey(kind, id, scope, env)) ?? { values: {}, revision: 0 }
let forceConflict = false
page.on('pageerror', (error) => errors.push(error.name))
await page.route((url) => url.pathname.startsWith('/api/') || url.pathname === '/projects' || url.pathname.startsWith('/auth/') || url.pathname.startsWith('/repos/'), async (route) => {
  const url = new URL(route.request().url())
  const path = url.pathname.replace(/^\/api/, '')
  const method = route.request().method()
  let data
  if (path === '/auth/me') data = { username: 'demo-user' }
  else if (path === '/projects') data = [project]
  else if (path === '/repos/demo/projects/gsb') data = project
  else if (path.endsWith('/environments')) data = envs
  else if (path.endsWith('/execution-records')) data = []
  else if (path.endsWith('/assets')) data = tree
  else if (path.endsWith('/assets/api.demo.preview')) data = api
  else if (path.endsWith('/assets/api.demo.preview/params')) data = { asset_id: api.id, params, asset_defaults: defaults }
  else if (path.includes('/parameter-sets/')) {
    const [kind, id, scope] = path.split('/parameter-sets/')[1].split('/')
    const env = url.searchParams.get('env') ?? ''
    if (method === 'PUT') {
      const body = route.request().postDataJSON()
      const current = stateFor(kind, id, scope, env)
      if (forceConflict) {
        forceConflict = false
        parameterSets.set(parameterKey(kind, id, scope, env), { values: { count: 7 }, revision: current.revision + 1 })
      }
      if (body.revision !== stateFor(kind, id, scope, env).revision) {
        await route.fulfill({ status: 409, json: { detail: '参数集版本冲突，请刷新后再保存' } })
        return
      }
      data = { values: body.values, revision: current.revision + 1 }
      parameterSets.set(parameterKey(kind, id, scope, env), data)
    } else {
      const git = kind === 'api' ? defaults : scenario.metadata.params
      const assetDefault = stateFor(kind, id, 'asset_default', env)
      const override = stateFor(kind, id, 'environment_override', env)
      const shared = envs.find((item) => item.env === env).case_params
      data = { project_id: project.id, asset_type: kind, asset_id: id, env, commit_sha: project.commit_sha, environment_revision: 1,
        git_defaults: git, shared_environment: shared, asset_default: assetDefault, environment_override: override,
        effective: { ...git, ...assetDefault.values, ...shared, ...override.values }, sources: {} }
    }
  }
  else if (path.endsWith('/cases/case.demo.preview')) data = { case_id: scenario.id, path: scenario.path, file_name: scenario.name, size_bytes: 120, modified_at: '2026-10-18T00:00:00Z' }
  else if (path.endsWith('/run') && method === 'POST') {
    const body = route.request().postDataJSON()
    submitted.push({ path, body })
    data = { record_id: `fixture-${submitted.length}`, status: 'success', duration: 0.01, result: path.includes('/cases/') ? {
      case_id: scenario.id, status: 'success', duration_seconds: 0.01, steps: [], summary: { total: 0, success: 0, failed: 0, skipped: 0 }, error: null, logins: [],
    } : { request: { body: body.params }, response: { status_code: 200, body: { ok: true } } } }
  } else {
    unexpected.push(`${method} ${path}`)
    await route.fulfill({ status: 500, json: { detail: 'Unconfigured fixture' } })
    return
  }
  await route.fulfill({ json: data })
})
const chooseEnv = async (env) => {
  await page.getByTestId('workspace-env-select').locator('.ant-select-selector').click()
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option').filter({ hasText: new RegExp(`^${env}$`) }).click()
}
const selectAsset = async (directory, id) => {
  const file = page.locator(`[data-asset-id="${id}"]`)
  if (!await file.isVisible()) await page.locator(`[data-asset-id="${directory}"]`).click()
  await file.click()
}
const noOverflow = async () => assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false)
try {
  await page.goto(`${base}/apis/demo/gsb`)
  await page.getByTestId('asset-tree').waitFor()
  await selectAsset('api', api.id)
  await page.getByTestId('parameter-effective-keyword').filter({ hasText: 'test 环境值' }).waitFor()
  await page.getByRole('button', { name: '维护默认值', exact: true }).click()
  await page.getByLabel('持久化参数 JSON').fill('{"count":4}')
  await page.getByRole('button', { name: '保存参数', exact: true }).click()
  await page.getByTestId('parameter-effective-count').filter({ hasText: '页面保存的默认值' }).waitFor()
  await page.getByRole('button', { name: '维护 test 覆盖', exact: true }).click()
  await page.getByLabel('持久化参数 JSON').fill('{"count":0,"active":false}')
  await page.getByRole('button', { name: '保存参数', exact: true }).click()
  await page.getByTestId('parameter-effective-count').filter({ hasText: '当前资产环境覆盖' }).waitFor()
  await page.reload()
  await page.getByTestId('asset-tree').waitFor()
  await selectAsset('api', api.id)
  await page.getByTestId('parameter-effective-count').filter({ hasText: '当前资产环境覆盖' }).waitFor()
  await page.getByRole('button', { name: '维护默认值', exact: true }).click()
  await page.getByLabel('持久化参数 JSON').fill('{"count":9}')
  forceConflict = true
  await page.getByRole('button', { name: '保存参数', exact: true }).click()
  await page.getByText('参数集版本冲突，请刷新后再保存', { exact: true }).waitFor()
  assert.equal(await page.getByLabel('持久化参数 JSON').inputValue(), '{"count":9}')
  await page.getByRole('button', { name: /取\s*消/ }).click()
  await page.getByRole('button', { name: '刷新参数', exact: true }).click()
  await page.getByTestId('parameter-preview').getByText('7', { exact: true }).waitFor()
  await page.getByRole('button', { name: '维护默认值', exact: true }).click()
  await page.getByLabel('持久化参数 JSON').fill('{}')
  // 刷新后的编辑会读取新 revision；清空本层恢复 Git 默认值。
  await page.getByRole('button', { name: '保存参数', exact: true }).click()
  await page.getByRole('dialog').waitFor({ state: 'hidden' })
  await page.getByLabel('keyword', { exact: true }).fill('本次关键字')
  await page.getByTestId('parameter-effective-keyword').filter({ hasText: '本次输入' }).waitFor()
  await page.getByRole('button', { name: '执行 API', exact: true }).click()
  await page.getByTestId('api-run-response').waitFor()
  assert.deepEqual(submitted[0].body, { env: 'test', params: { keyword: '本次关键字' } })
  await noOverflow()
  await page.screenshot({ path: `${out}/api-parameters-desktop.png`, fullPage: true, animations: 'disabled' })
  await chooseEnv('pre')
  await page.getByTestId('parameter-effective-keyword').filter({ hasText: 'pre 环境值' }).waitFor()
  assert.equal(await page.getByLabel('keyword', { exact: true }).inputValue(), '')
  await page.getByText('编辑完整请求内容', { exact: true }).click()
  assert.equal(await page.getByTestId('parameter-preview').isVisible(), false)
  await page.getByText('使用 YAML 模板', { exact: true }).click()

  await page.goto(`${base}/scenarios/demo/gsb`)
  await page.getByTestId('asset-tree').waitFor()
  await selectAsset('scenarios', scenario.id)
  const temporary = { filter: { a: 0 }, active: false, nullable: null }
  await page.getByLabel('本次场景参数', { exact: true }).fill(JSON.stringify(temporary))
  await page.getByTestId('parameter-effective-filter').filter({ hasText: '{"a":0}' }).waitFor()
  await page.getByRole('button', { name: '执行 Case', exact: true }).click()
  await page.getByTestId('case-run-result-wrap').waitFor()
  assert.deepEqual(submitted[1].body.params, temporary)
  await page.screenshot({ path: `${out}/case-parameters-desktop.png`, fullPage: true, animations: 'disabled' })
  await page.getByLabel('本次场景参数', { exact: true }).fill('[]')
  assert(await page.getByRole('button', { name: '执行 Case', exact: true }).isDisabled())
  await page.getByRole('button', { name: '清除本次场景输入', exact: true }).click()
  assert.equal(await page.getByLabel('本次场景参数', { exact: true }).inputValue(), '')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByTestId('parameter-preview').waitFor()
  await noOverflow()
  await page.screenshot({ path: `${out}/case-parameters-mobile.png`, fullPage: true, animations: 'disabled' })
  assert.deepEqual(errors, [])
  assert.deepEqual(unexpected, [])
  const report = { fixture_api_only: true, saved_parameters_survive_reload: true, conflict_preserves_draft: true, sources_visible: true, api_sends_only_temporary: true, case_sends_json_overlay: true, invalid_json_blocked: true, environment_clears_input: true, full_body_hides_template_preview: true, mobile_no_overflow: true, page_errors: errors.length }
  fs.writeFileSync(`${out}/report.json`, JSON.stringify(report, null, 2))
  console.log(JSON.stringify(report))
} catch (error) {
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true })
  console.error(JSON.stringify({ unexpected, page_errors: errors, url: page.url() }))
  throw error
} finally {
  await context.close()
  await browser.close()
}
