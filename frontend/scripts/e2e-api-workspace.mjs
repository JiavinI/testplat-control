/** UI 隔离验收：全部 /api 请求在浏览器中拦截，不触碰预览数据库或真实业务。 */
import { chromium } from 'playwright'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173'
const out = process.env.E2E_OUT_DIR || '/tmp/testplat-api-workspace'
fs.mkdirSync(out, { recursive: true })
const project = { id: 'main/gsb', repo: 'main', project: 'gsb', name: '接口工作区 · 隔离验收', envs: ['test', 'staging'], default_env: 'test', archived: false, commit_sha: 'fd93f865e8bc84ce17dcd8e12b83e5717f60ab51', created_at: '', updated_at: '' }
const makeApi = (id, name, method, url, request) => ({ id, name: `${id.split('.').at(-1)}.yaml`, type: 'file', path: `api/gsb/${id.split('.').slice(2).join('/')}.yaml`, metadata: { name, host: 'gsb', method, url, auth: 'gsb.b2.primary', request, success: { path: '$.errorCode', value: '0' } } })
const balance = makeApi('api.gsb.account.balance', '查询账户余额', 'POST', '/api/account/balance', { type: 'json', body: {} })
const search = makeApi('api.gsb.order.search_product', '搜索商品', 'GET', '/api/b2/orders/search/product', { type: 'query', inputs: { product_keyword: 'str' }, body: { keywords: '${product_keyword}' } })
const tree = { id: 'assets', name: 'assets', path: '.', type: 'directory', children: [
  { id: 'api', name: 'api', path: 'api', type: 'directory', children: [balance, search] },
  { id: 'scenarios', name: 'scenarios', path: 'scenarios', type: 'directory', children: [] },
  { id: 'config', name: 'config', path: 'config', type: 'directory', children: [] },
] }
const requests = []
const unexpected = []
const errors = []
const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, serviceWorkers: 'block' })
const page = await context.newPage()
page.on('pageerror', (error) => errors.push(error.name))
// 禁止接口穿透到真实后端；未声明的接口直接失败并记入报告。
await context.route((url) => url.pathname.startsWith('/api/'), async (route) => {
  const request = route.request()
  const endpoint = new URL(request.url()).pathname.replace(/^\/api/, '')
  const root = '/repos/main/projects/gsb'
  let data
  if (endpoint === '/auth/me') data = { username: 'isolated-ui-check' }
  else if (endpoint === '/projects') data = [project, { ...project, id: 'other/demo', repo: 'other', project: 'demo', name: '另一个项目' }]
  else if (endpoint === root || endpoint === '/repos/other/projects/demo') data = { ...project, ...(endpoint === root ? {} : { id: 'other/demo', repo: 'other', project: 'demo' }) }
  else if (endpoint.endsWith('/assets')) data = tree
  else if (endpoint.endsWith('/environments')) data = ['test', 'staging', 'missing'].map((env) => ({ env, enabled: true, api_hosts: env === 'missing' ? {} : { gsb: `https://${env}.example/` }, case_params: {}, timeout_seconds: null, revision: 1, updated_by: 'fixture' }))
  else if (endpoint.endsWith('/execution-records')) data = []
  else {
    const asset = endpoint.includes(search.id) ? search : balance
    if (endpoint.endsWith(`/assets/${asset.id}`)) data = asset
    else if (endpoint.endsWith('/params')) data = { asset_id: asset.id, params: asset === search ? [{ name: 'product_keyword', type: 'string', required: true, description: null }] : [] }
    else if (endpoint.endsWith('/run') && request.method() === 'POST') {
      const body = request.postDataJSON()
      requests.push({ asset: asset.id, ...body })
      data = { record_id: `fixture-${requests.length}`, status: 'success', duration: 0.032, commit_sha: project.commit_sha, result: {
        request: { method: asset.metadata.method, url: `https://${body.env}.example${asset.metadata.url}`, body: body.request_override?.body ?? {}, body_type: asset.metadata.request.type },
        response: { status_code: 200, headers: { 'content-type': 'application/json' }, body: { errorCode: '0', message: '隔离模拟响应', data: {} } }, error: null,
      } }
    }
  }
  if (data === undefined) { unexpected.push(endpoint); return route.abort() }
  await route.fulfill({ json: data })
})
const choose = async (asset) => {
  const filter = page.getByLabel('过滤资产')
  await filter.fill(asset.id)
  await page.locator(`[data-asset-id="${asset.id}"]`).click()
  await page.getByTestId('api-execution-panel').waitFor()
}
const changeEnv = async (env) => {
  await page.getByTestId('workspace-env-select').locator('.ant-select-selector').click()
  await page.getByTitle(env, { exact: true }).click()
}
try {
  await page.goto(`${base}/apis/main/gsb`, { waitUntil: 'networkidle' })
  await choose(balance)
  assert.match(await page.getByTestId('api-full-url').innerText(), /https:\/\/test.example\/api\/account\/balance/)
  assert.equal(await page.locator('[data-asset-id="config"], [data-asset-id="scenarios"]').count(), 0)
  await page.getByText('编辑完整请求内容', { exact: true }).click()
  await page.getByLabel('临时请求内容').fill('{"temporary":true}')
  await page.getByRole('button', { name: '执行 API', exact: true }).click()
  await page.getByTestId('api-run-response').waitFor()
  assert.deepEqual(requests.at(-1).request_override, { body: { temporary: true } })
  assert.match(await page.getByLabel('响应内容', { exact: true }).innerText(), /隔离模拟响应/)
  await page.screenshot({ path: path.join(out, 'balance-desktop.png'), fullPage: true })
  await changeEnv('staging')
  assert.equal(await page.getByLabel('临时请求内容').count(), 0)
  assert.equal(await page.getByTestId('api-run-response').count(), 0)
  assert.match(await page.getByTestId('api-full-url').innerText(), /staging.example/)
  await choose(search)
  await page.getByText('编辑完整请求内容', { exact: true }).click()
  await page.getByLabel('临时请求内容').fill('{"keywords":"鞋 & 包","count":2}')
  await page.getByRole('button', { name: '执行 API', exact: true }).click()
  await page.getByTestId('api-run-response').waitFor()
  assert.deepEqual(requests.at(-1).request_override.body, { keywords: '鞋 & 包', count: 2 })
  await page.getByRole('tab', { name: '实际请求', exact: true }).click()
  assert.match(await page.getByLabel('实际请求快照').innerText(), /鞋 & 包/)
  await changeEnv('missing')
  assert(await page.getByRole('button', { name: '执行 API', exact: true }).isDisabled())
  await changeEnv('test')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '打开资产浏览' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('过滤资产').fill(balance.id)
  await dialog.locator(`[data-asset-id="${balance.id}"]`).click()
  await dialog.waitFor({ state: 'hidden' })
  await page.getByTestId('api-info-panel').waitFor()
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
  await page.screenshot({ path: path.join(out, 'balance-mobile.png'), fullPage: true })
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.getByTestId('feature-project-select').locator('.ant-select-selector').click()
  await page.getByTitle('另一个项目 · other/demo', { exact: true }).click()
  await page.waitForURL('**/apis/other/demo')
  assert.equal(await page.getByTestId('api-execution-panel').count(), 0)
  assert.deepEqual(errors, [])
  assert.deepEqual(unexpected, [])
  const report = { mode: 'isolated-browser-mocks', real_business_acceptance: false, checks: ['API tree', 'environment URL', 'JSON override', 'Query override', 'response tabs', 'environment draft reset', 'missing host', 'mobile', 'project reset'], run_count: requests.length, page_errors: errors.length }
  fs.writeFileSync(path.join(out, 'report.json'), `${JSON.stringify(report, null, 2)}\n`)
  console.log(JSON.stringify(report))
} catch (error) {
  await page.screenshot({ path: path.join(out, 'failure.png'), fullPage: true })
  console.error(JSON.stringify({ unexpected, page_errors: errors, page_title: await page.title() }))
  throw error
} finally {
  await browser.close()
}
