/** 通过独立 Vite 代理访问真实隔离后端；不拦截或伪造应用 API。 */
import { chromium } from 'playwright'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const base = process.env.E2E_BASE_URL
const out = process.env.E2E_OUT_DIR
if (!base || !out) throw new Error('Run through scripts/verify_gsb_workspace.py')
const address = new URL(base)
assert.equal(address.hostname, '127.0.0.1')
fs.mkdirSync(out, { recursive: true })
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
page.setDefaultTimeout(15000)
const errors = []
const requests = []
page.on('pageerror', error => errors.push(error.name))
page.on('request', request => {
  // 只计数，不打印请求内容或登录材料。
  if (new URL(request.url()).pathname.endsWith('/run')) requests.push(request.method())
})
const apiBase = project => `/api/repos/isolated/projects/${project}`
const nodes = node => [node, ...(node.children ?? []).flatMap(nodes)]
const ancestorIds = (node, id, parents = []) => {
  if (node.id === id) return parents
  for (const child of node.children ?? []) {
    const result = ancestorIds(child, id, [...parents, node.id])
    if (result) return result
  }
  return null
}
let tree
const visit = async project => {
  await page.goto(`${base}/apis/isolated/${project}`)
  await page.getByTestId('asset-tree').waitFor()
  const response = await page.request.get(`${base}${apiBase(project)}/assets`)
  assert.equal(response.status(), 200)
  tree = await response.json()
}
const select = async id => {
  const ancestors = ancestorIds(tree, id)
  assert(ancestors, `Asset missing: ${id}`)
  for (const parent of ancestors) {
    if (parent === 'assets') continue
    const element = page.locator(`[data-asset-id="${parent}"]`)
    await element.waitFor({ state: 'visible' })
    const treeNode = element.locator('xpath=ancestor::*[contains(@class,"ant-tree-treenode")][1]')
    if (await treeNode.getAttribute('aria-expanded') !== 'true') await element.click()
  }
  await page.locator(`[data-asset-id="${id}"]`).click()
  await page.getByTestId('api-execution-panel').waitFor()
  await page.getByTestId('api-info-panel').getByText('调用身份由本次调试或场景步骤选择').waitFor()
  assert(!(await page.getByTestId('api-info-panel').textContent()).includes('gsb.b2.primary'))
}
const identity = async name => {
  await page.locator('.ant-select').filter({
    has: page.getByRole('combobox', { name: '调用账号', exact: true }),
  }).locator('.ant-select-selector').click()
  const label = name === '匿名调用' ? name : `${name} · ${name}`
  await page.locator('.ant-select-dropdown:visible').getByText(label, { exact: true }).click()
}
const noIdentity = async () => {
  await page.getByText('选择本次调用账号', { exact: true }).waitFor()
}
const run = async (status = 200) => {
  const result = page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/run'))
  await page.getByRole('button', { name: '执行 API', exact: true }).click()
  const response = await result
  assert.equal(response.status(), status)
  if (status === 200) {
    const data = await response.json()
    assert.equal(data.status, 'success')
    assert(!JSON.stringify(data).includes('fake-token'))
    await page.getByTestId('api-business-result').filter({ hasText: '业务判定通过' }).waitFor()
  }
  return response
}
const blocked = async () => {
  const count = requests.length
  await page.getByRole('button', { name: '执行 API', exact: true }).click()
  assert.equal(requests.length, count)
}
const noOverflow = async () => assert.equal(
  await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false,
)
const fillFreight = async () => {
  await page.getByLabel('express_id', { exact: true }).fill('fixture-express')
  await page.getByLabel('quantity', { exact: true }).fill('2')
  await page.getByLabel('receiver_province', { exact: true }).fill('四川省')
}
try {
  for (const [project, allowed, excluded] of [['gsb', 'go2', 'e3e3'], ['gsb_e3e3', 'e3e3', 'go2']]) {
    await visit(project)
    const all = nodes(tree)
    assert.equal(all.filter(node => node.id === 'api.gsb.b2.order.freight').length, 1)
    assert.equal(all.filter(node => node.id === 'api.gsb.b2.order.search_page').length, 1)
    assert(all.some(node => node.id === `api.gsb.b2.order.${allowed}.create`))
    assert(!all.some(node => node.id === `api.gsb.b2.order.${excluded}.create`))
    await select(`api.gsb.b2.order.${allowed}.create`)
    assert.equal(await page.locator(`[data-asset-id="api.gsb.b2.order.${excluded}"]`).count(), 0)
    await page.screenshot({ path: `${out}/tree-${allowed}.png`, fullPage: false, animations: 'disabled' })
  }

  await visit('gsb')
  await select('api.gsb.b2.order.freight')
  await blocked()
  await page.getByText('请填写该参数', { exact: true }).first().waitFor()
  await fillFreight()
  await identity('buyer')
  await run()
  await identity('alternate')
  await run()
  await identity('匿名调用')
  await run()
  await noOverflow()
  await page.screenshot({ path: `${out}/freight-go2.png`, fullPage: true, animations: 'disabled' })
  await select('api.gsb.b2.order.search_page')
  await noIdentity()
  await select('api.gsb.b2.order.freight')
  await noIdentity()
  assert.equal(await page.getByLabel('quantity', { exact: true }).inputValue(), '')

  await visit('gsb_e3e3')
  await select('api.gsb.b2.order.freight')
  await noIdentity()
  await fillFreight()
  await identity('buyer')
  await run()
  await page.screenshot({ path: `${out}/freight-e3e3.png`, fullPage: true, animations: 'disabled' })

  await select('api.gsb.b2.order.e3e3.coupons')
  await noIdentity()
  await identity('alternate')
  await page.getByLabel('quantity', { exact: true }).fill('2')
  await page.getByLabel('product', { exact: true }).fill('{')
  await blocked()
  await page.getByRole('alert').filter({ hasText: /JSON/ }).waitFor()
  await page.getByLabel('product', { exact: true }).fill('{}')
  const missing = await run(422)
  assert((await missing.text()).includes('product.id'))
  await page.getByRole('alert').filter({ hasText: /product.id/ }).waitFor()
  await page.screenshot({ path: `${out}/nested-required.png`, fullPage: true, animations: 'disabled' })
  await page.getByLabel('product', { exact: true }).fill('{"id":"fixture-product","sku_price":12.5}')
  await run()
  await page.getByRole('tab', { name: '实际请求', exact: true }).click()
  await page.screenshot({ path: `${out}/object-json.png`, fullPage: true, animations: 'disabled' })

  await select('api.gsb.b2.order.search_page')
  await noIdentity()
  await identity('buyer')
  await page.getByLabel('search_field', { exact: true }).fill('orderNo')
  await page.getByLabel('search_terms', { exact: true }).fill('fixture-order')
  await page.getByLabel('page_size', { exact: true }).fill('20')
  await page.getByLabel('page_no', { exact: true }).fill('1')
  await page.getByLabel('error_print_tag', { exact: true }).fill('0')
  await page.getByLabel('take_states', { exact: true }).fill('{}')
  await blocked()
  await page.getByRole('alert').filter({ hasText: /JSON 数组/ }).waitFor()
  await page.getByLabel('take_states', { exact: true }).fill('["WAIT"]')
  await run()
  await page.getByRole('tab', { name: '实际请求', exact: true }).click()
  await page.screenshot({ path: `${out}/array-json.png`, fullPage: true, animations: 'disabled' })
  await page.getByTestId('workspace-env-select').locator('.ant-select-selector').click()
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option').filter({ hasText: /^pre$/ }).click()
  await noIdentity()
  assert.equal(await page.getByLabel('search_field', { exact: true }).inputValue(), '')
  assert.equal(await page.getByLabel('take_states', { exact: true }).inputValue(), '')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.evaluate(() => window.scrollTo(0, 0))
  await noOverflow()
  await page.screenshot({ path: `${out}/mobile-top.png`, fullPage: false, animations: 'disabled' })
  await page.getByRole('combobox', { name: '调用账号', exact: true }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: `${out}/mobile-identity.png`, fullPage: false, animations: 'disabled' })
  await identity('buyer')
  await page.getByLabel('take_states', { exact: true }).scrollIntoViewIfNeeded()
  await noOverflow()
  await page.screenshot({ path: `${out}/mobile-json.png`, fullPage: false, animations: 'disabled' })
  assert.deepEqual(errors, [])
  assert.equal(requests.length, 7) // 六次成功业务调用，加一次嵌套必填 422。
  fs.rmSync(`${out}/failure.png`, { force: true })
  console.log(JSON.stringify({
    public_and_project_trees: true, identity_switch_and_reset: true,
    required_and_json_validation: true, mobile_no_overflow: true,
    api_requests: requests.length, page_errors: errors.length,
  }))
} catch (error) {
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true, animations: 'disabled' })
  throw error
} finally {
  await browser.close()
}
