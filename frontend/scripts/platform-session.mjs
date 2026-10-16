/**
 * 浏览器门禁的平台会话。配置和执行页未登录时就地显示登录，不跳转独立路由。
 */

export async function captureLoggedOut(page, baseUrl) {
  await page.goto(`${baseUrl}/projects`, { waitUntil: 'networkidle' })
  await page.getByTestId('login-page').waitFor({ timeout: 20000 })
}

export async function submitPlatformAuth(page, { username, password, mode }) {
  if (mode === 'register') {
    await page.getByRole('tab', { name: '注册' }).click()
  }
  await page.getByTestId('auth-username').fill(username)
  await page.getByTestId('auth-password').fill(password)
  await page.getByTestId('auth-submit').click()
  const landed = page.getByTestId('project-list-grouped')
  const failed = page.getByTestId('login-error')
  const winner = await Promise.race([
    landed.waitFor({ timeout: 20000 }).then(() => 'ok'),
    failed.waitFor({ timeout: 20000 }).then(() => 'fail'),
  ])
  if (winner === 'fail') {
    throw new Error(`平台会话失败: ${(await failed.innerText()).replaceAll(password, '[redacted]')}`)
  }
}
