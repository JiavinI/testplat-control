import { chromium } from 'playwright'
import assert from 'node:assert/strict'
const fixture = process.env.E2E_PARAMETER_FIXTURE_URL
if (!fixture) throw new Error('Run through scripts/verify_parameter_workspace.py')
const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173'
const browser = await chromium.launch({headless:true})
const page = await browser.newPage({viewport:{width:1440,height:1000}})
const errors=[]
await import('node:fs').then(({default:fs})=>fs.mkdirSync('/tmp/testplat-parameter-preview',{recursive:true}))
page.on('pageerror',e=>errors.push(e.name))
await page.route(url => url.pathname.startsWith('/api/') || url.pathname === '/projects' || url.pathname.startsWith('/auth/') || url.pathname.startsWith('/repos/'), async route=>{
 const url = new URL(route.request().url())
 const path = url.pathname.replace(/^\/api/, '')
 if(path === '/auth/me') { await route.fulfill({json:{username:'fixture-user'}}); return }
 const response = await route.fetch({url:`${fixture}${path}${url.search}`})
 await route.fulfill({response})
})
try {
 await page.goto(`${base}/apis/demo/demo`)
 await page.getByTestId('asset-tree').waitFor()
 for (const id of ['api','api.gsb']) {
  const node=page.locator(`[data-asset-id="${id}"]`)
  const child=page.locator('[data-asset-id="api.gsb.parameters"]')
  if(!await child.isVisible() && await node.isVisible()) await node.click()
 }
 await page.locator('[data-asset-id="api.gsb.parameters"]').click()
 await page.getByRole('button',{name:'维护 test 覆盖',exact:true}).click()
 await page.getByLabel('持久化参数 JSON').fill('{"count":0,"active":false,"keyword":"saved-browser"}')
 await page.getByRole('button',{name:'保存参数',exact:true}).click()
 await page.getByTestId('parameter-effective-keyword').filter({hasText:'saved-browser'}).waitFor()
 await page.getByRole('button',{name:'执行 API',exact:true}).click()
 await page.getByTestId('api-run-response').waitFor()
 await page.getByRole('tab',{name:'实际请求'}).click()
 assert((await page.getByTestId('api-execution-panel').textContent()).includes('saved-browser'))
 await page.screenshot({path:'/tmp/testplat-parameter-preview/fullstack-api.png',fullPage:true,animations:'disabled'})
 await page.reload()
 await page.getByTestId('asset-tree').waitFor()
 for(const id of ['api','api.gsb']) {
  const child=page.locator('[data-asset-id="api.gsb.parameters"]')
  if(!await child.isVisible()) await page.locator(`[data-asset-id="${id}"]`).click()
 }
 await page.locator('[data-asset-id="api.gsb.parameters"]').click()
 await page.getByTestId('parameter-effective-keyword').filter({hasText:'saved-browser'}).waitFor()
 await page.goto(`${base}/scenarios/demo/demo`)
 await page.getByTestId('asset-tree').waitFor()
 for(const id of ['scenarios','scenarios.gsb']) {
  const child=page.locator('[data-asset-id="case.gsb.parameters"]')
  if(!await child.isVisible() && await page.locator(`[data-asset-id="${id}"]`).isVisible()) await page.locator(`[data-asset-id="${id}"]`).click()
 }
 await page.locator('[data-asset-id="case.gsb.parameters"]').click()
 await page.getByRole('button',{name:'维护 test 覆盖',exact:true}).click()
 await page.getByLabel('持久化参数 JSON').fill('{"filter":{"a":0},"active":false,"keyword":"saved-case","optional":null}')
 await page.getByRole('button',{name:'保存参数',exact:true}).click()
 await page.getByTestId('parameter-effective-keyword').filter({hasText:'saved-case'}).waitFor()
 await page.getByRole('button',{name:'执行 Case',exact:true}).click()
 await page.getByTestId('case-run-result-wrap').waitFor()
 await page.screenshot({path:'/tmp/testplat-parameter-preview/fullstack-case.png',fullPage:true,animations:'disabled'})
 await page.setViewportSize({width:390,height:844})
 await page.getByRole('button',{name:'维护 test 覆盖',exact:true}).click()
 const dialog = page.getByRole('dialog')
 await dialog.waitFor({state:'visible'})
 // 等 AntD 入场动画完成再检查几何位置；长页面截图无法可靠呈现 fixed 弹窗。
 await page.waitForFunction(() => {
  const modal = document.querySelector('.ant-modal')
  return modal && !/zoom-(appear|enter)/.test(modal.className) && getComputedStyle(modal).opacity === '1'
 })
 const dialogBox = await dialog.boundingBox()
 const editorBox = await page.getByLabel('持久化参数 JSON').boundingBox()
 assert(dialogBox && dialogBox.width > 300 && dialogBox.x >= 0 && dialogBox.x + dialogBox.width <= 390)
 assert(editorBox && editorBox.width > 250 && editorBox.y >= 0 && editorBox.y + editorBox.height <= 844)
 assert(await dialog.getByRole('button',{name:'保存参数',exact:true}).isVisible())
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false)
 await page.screenshot({path:'/tmp/testplat-parameter-preview/fullstack-editor-mobile.png',fullPage:false})
 assert.deepEqual(errors,[])
 console.log(JSON.stringify({real_control:true,real_local_engine:true,isolated_memory_database:true,local_fake_target:true,browser_save_run_reload:true,case_save_run:true,page_errors:errors.length}))
}catch(error){await page.screenshot({path:'/tmp/testplat-parameter-preview/fullstack-failure.png',fullPage:true,animations:'disabled'});console.error(await page.locator('body').innerText());throw error}finally{await browser.close()}
