import type { ReactElement } from 'react'
import { useState } from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { ConfigProvider, App as AntApp } from 'antd'
import { ApiHttpError } from '@/shared/api/errors'
import { createAppQueryClient } from '@/app/queryClient'
import { AppLayout } from '@/app/AppLayout'
import { RequireAuth } from '@/features/auth/RequireAuth'
import { authKeys } from '@/features/auth/session'
import { AccountSection } from './AccountSection'
import { EnvironmentSection } from './EnvironmentSection'
import { ProjectConfigPanel } from './ProjectConfigPanel'
import { environmentKeys } from './hooks'
import type { AccountCredentials, ProjectEnvironment, TestAccount } from './types'

const listEnvironments = vi.fn()
const createEnvironment = vi.fn()
const updateEnvironment = vi.fn()
const getEnvironment = vi.fn()
const listAccounts = vi.fn()
const createAccount = vi.fn()
const updateAccount = vi.fn()
const getAccount = vi.fn()
const getAccountCredentials = vi.fn()
const listLoginProfiles = vi.fn()

vi.mock('@/features/auth/api', () => ({
  getMe: vi.fn().mockResolvedValue({ username: 'alice' }),
  login: vi.fn(),
  logout: vi.fn(),
  register: vi.fn(),
}))

vi.mock('./api', () => ({
  listEnvironments: (...args: unknown[]) => listEnvironments(...args),
  createEnvironment: (...args: unknown[]) => createEnvironment(...args),
  updateEnvironment: (...args: unknown[]) => updateEnvironment(...args),
  getEnvironment: (...args: unknown[]) => getEnvironment(...args),
  listAccounts: (...args: unknown[]) => listAccounts(...args),
  createAccount: (...args: unknown[]) => createAccount(...args),
  updateAccount: (...args: unknown[]) => updateAccount(...args),
  getAccount: (...args: unknown[]) => getAccount(...args),
  getAccountCredentials: (...args: unknown[]) => getAccountCredentials(...args),
  listLoginProfiles: (...args: unknown[]) => listLoginProfiles(...args),
}))

const testEnv: ProjectEnvironment = {
  env: 'test',
  enabled: true,
  api_hosts: { gsb: 'http://127.0.0.1:9' },
  timeout_seconds: 15,
  case_params: { product_keyword: 'shoes' },
  revision: 1,
  updated_by: 'alice',
}

const gsbAccount: TestAccount = {
  account_name: 'gsb',
  display_name: '采购',
  business_role: '买家',
  login_profile: 'gsb_login',
  enabled: true,
  revision: 1,
  updated_by: 'alice',
}

function renderSection(node: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return {
    client,
    ...render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <AntApp>
          <QueryClientProvider client={client}>{node}</QueryClientProvider>
        </AntApp>
      </ConfigProvider>,
    ),
  }
}

function renderAuthed(node: ReactElement) {
  const client = createAppQueryClient()
  client.setQueryDefaults([...authKeys.me], {
    staleTime: Infinity,
    refetchOnMount: false,
    refetchOnReconnect: false,
    refetchOnWindowFocus: false,
  })
  client.setQueryData(authKeys.me, { username: 'alice' })
  return {
    client,
    ...render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <AntApp>
          <QueryClientProvider client={client}>
            <MemoryRouter initialEntries={['/work']}>
              <Routes>
                <Route element={<AppLayout />}>
                  <Route element={<RequireAuth />}>
                    <Route path="/work" element={node} />
                  </Route>
                </Route>
              </Routes>
            </MemoryRouter>
          </QueryClientProvider>
        </AntApp>
      </ConfigProvider>,
    ),
  }
}

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

const otherAccount: TestAccount = {
  account_name: 'other',
  display_name: '另一个',
  business_role: '访客',
  login_profile: 'gsb_login',
  enabled: true,
  revision: 4,
  updated_by: 'alice',
}

const secondEnv: ProjectEnvironment = {
  ...testEnv,
  timeout_seconds: 40,
  case_params: { product_keyword: 'second-default' },
  api_hosts: { gsb: 'http://10.0.0.2:9' },
  revision: 3,
  updated_by: 'bob',
}

const secondAccount: TestAccount = {
  ...gsbAccount,
  display_name: '第二项目',
  revision: 5,
  updated_by: 'bob',
}

beforeEach(() => {
  listEnvironments.mockReset()
  createEnvironment.mockReset()
  updateEnvironment.mockReset()
  getEnvironment.mockReset()
  listAccounts.mockReset()
  createAccount.mockReset()
  updateAccount.mockReset()
  getAccount.mockReset()
  getAccountCredentials.mockReset()
  listLoginProfiles.mockReset()
  listLoginProfiles.mockResolvedValue({
    commit_sha: 'abcdef0',
    profiles: [{ name: 'gsb_login', credential_fields: ['username', 'password'] }],
  })
  listAccounts.mockResolvedValue([])
})

describe('环境管理', () => {
  it('新增环境提交服务地址、超时和参数默认值', async () => {
    const user = userEvent.setup({ delay: null })
    listEnvironments.mockResolvedValue([])
    createEnvironment.mockResolvedValue({ ...testEnv, env: 'pre', revision: 1 })
    renderSection(<EnvironmentSection projectId="main/gsb" />)
    await user.click(await screen.findByTestId('env-create-open'))
    fireEvent.change(screen.getByLabelText('环境名'), { target: { value: 'pre' } })
    fireEvent.change(screen.getByLabelText('服务名 1'), { target: { value: 'gsb' } })
    fireEvent.change(screen.getByLabelText('地址 1'), {
      target: { value: 'http://127.0.0.1:9' },
    })
    fireEvent.change(screen.getByLabelText('超时（秒）'), { target: { value: '15' } })
    fireEvent.change(screen.getByLabelText('参数默认值'), {
      target: { value: '{"product_keyword":"shoes"}' },
    })
    await user.click(screen.getByTestId('env-save'))
    await waitFor(() => {
      expect(createEnvironment).toHaveBeenCalledWith('main/gsb', {
        env: 'pre',
        enabled: true,
        api_hosts: { gsb: 'http://127.0.0.1:9' },
        timeout_seconds: 15,
        case_params: { product_keyword: 'shoes' },
      })
    })
  })

  it('停用环境只提交 revision 和 enabled', async () => {
    const user = userEvent.setup({ delay: null })
    listEnvironments.mockResolvedValue([testEnv])
    updateEnvironment.mockResolvedValue({ ...testEnv, enabled: false, revision: 2 })
    renderSection(<EnvironmentSection projectId="main/gsb" />)
    await user.click(await screen.findByTestId('env-toggle-test'))
    await waitFor(() => {
      expect(updateEnvironment).toHaveBeenCalledWith('main/gsb', 'test', {
        revision: 1,
        enabled: false,
      })
    })
  })

  it('旧 revision 保存得到 409，刷新后再带新版本保存', async () => {
    const user = userEvent.setup({ delay: null })
    listEnvironments.mockResolvedValue([testEnv])
    updateEnvironment.mockRejectedValueOnce(
      new ApiHttpError(409, '配置版本冲突，请刷新后再保存', ''),
    )
    getEnvironment.mockResolvedValue({ ...testEnv, revision: 2, timeout_seconds: 20 })
    renderSection(<EnvironmentSection projectId="main/gsb" />)
    await user.click(await screen.findByTestId('env-edit-test'))
    expect(screen.getByTestId('editing-revision')).toHaveTextContent('版本 1')
    fireEvent.change(screen.getByLabelText('超时（秒）'), { target: { value: '18' } })
    await user.click(screen.getByTestId('env-save'))
    expect(await screen.findByTestId('revision-conflict')).toHaveTextContent(
      '配置版本冲突，请刷新后再保存',
    )
    expect(updateEnvironment).toHaveBeenCalledWith(
      'main/gsb',
      'test',
      expect.objectContaining({ revision: 1, timeout_seconds: 18 }),
    )

    updateEnvironment.mockResolvedValue({ ...testEnv, revision: 3, timeout_seconds: 20 })
    await user.click(screen.getByTestId('revision-refresh'))
    expect(await screen.findByTestId('editing-revision')).toHaveTextContent('版本 2')
    await user.click(screen.getByTestId('env-save'))
    await waitFor(() => {
      expect(updateEnvironment).toHaveBeenLastCalledWith(
        'main/gsb',
        'test',
        expect.objectContaining({ revision: 2 }),
      )
    })
  })
})

describe('测试账号凭据', () => {
  it('列表不显示密码，点击查看后才能看到并切换明文', async () => {
    const user = userEvent.setup({ delay: null })
    listEnvironments.mockResolvedValue([testEnv])
    listAccounts.mockResolvedValue([gsbAccount])
    getAccountCredentials.mockResolvedValue({
      account_name: 'gsb',
      credentials: { username: 'buyer-user', password: 'secret-pass' },
    })
    renderSection(<AccountSection projectId="main/gsb" />)
    expect(await screen.findByText('gsb')).toBeInTheDocument()
    expect(screen.getByTestId('account-table')).not.toHaveTextContent('secret-pass')
    expect(getAccountCredentials).not.toHaveBeenCalled()

    await user.click(screen.getByTestId('account-edit-gsb'))
    expect(getAccountCredentials).not.toHaveBeenCalled()
    await user.click(await screen.findByTestId('reveal-credentials'))
    const password = await screen.findByLabelText('password')
    expect(password).toHaveAttribute('type', 'password')
    expect(password).toHaveValue('secret-pass')
    expect(getAccountCredentials).toHaveBeenCalledWith('main/gsb', 'test', 'gsb')
    expect(screen.getByTestId('account-table')).not.toHaveTextContent('secret-pass')

    const icon = password.closest('.ant-input-password')?.querySelector('.ant-input-password-icon')
    expect(icon).toBeTruthy()
    fireEvent.click(icon as Element)
    expect(password).toHaveAttribute('type', 'text')
  })

  it('账号保存带 revision，409 后刷新再保存', async () => {
    const user = userEvent.setup({ delay: null })
    listEnvironments.mockResolvedValue([testEnv])
    listAccounts.mockResolvedValue([gsbAccount])
    updateAccount.mockRejectedValueOnce(
      new ApiHttpError(409, '配置版本冲突，请刷新后再保存', ''),
    )
    getAccount.mockResolvedValue({ ...gsbAccount, revision: 2, display_name: '新采购' })
    renderSection(<AccountSection projectId="main/gsb" />)
    await user.click(await screen.findByTestId('account-edit-gsb'))
    fireEvent.change(await screen.findByLabelText('展示名'), { target: { value: '门店' } })
    await user.click(screen.getByTestId('account-save'))
    expect(await screen.findByTestId('revision-conflict')).toHaveTextContent(
      '请刷新后再保存',
    )
    expect(updateAccount).toHaveBeenCalledWith(
      'main/gsb',
      'test',
      'gsb',
      expect.objectContaining({ revision: 1, display_name: '门店' }),
    )
    expect(updateAccount.mock.calls[0][3]).not.toHaveProperty('credentials')

    updateAccount.mockResolvedValue({ ...gsbAccount, revision: 3, display_name: '新采购' })
    await user.click(screen.getByTestId('revision-refresh'))
    expect(await screen.findByTestId('editing-revision')).toHaveTextContent('版本 2')
    await user.click(screen.getByTestId('account-save'))
    await waitFor(() => {
      expect(updateAccount).toHaveBeenLastCalledWith(
        'main/gsb',
        'test',
        'gsb',
        expect.objectContaining({ revision: 2 }),
      )
    })
    const saved = updateAccount.mock.calls.at(-1)?.[3] as { credentials?: unknown }
    expect(saved.credentials).toBeUndefined()
  })

  it('取消后迟到的凭据响应不会写入下一个账号，改密码保存也不带旧用户名', async () => {
    const user = userEvent.setup({ delay: null })
    const pending = deferred<AccountCredentials>()
    getAccountCredentials.mockImplementation((_project: string, _env: string, name: string) => {
      if (name === 'gsb') {
        return pending.promise
      }
      return Promise.resolve({
        account_name: 'other',
        credentials: { username: 'account-B-user', password: 'bbbbbbbb' },
      })
    })
    listEnvironments.mockResolvedValue([testEnv])
    listAccounts.mockResolvedValue([gsbAccount, otherAccount])
    updateAccount.mockResolvedValue(otherAccount)
    const { client } = renderSection(<AccountSection projectId="main/gsb" />)

    await user.click(await screen.findByTestId('account-edit-gsb'))
    await user.click(await screen.findByTestId('reveal-credentials'))
    await user.click(screen.getByTestId('account-cancel'))
    await user.click(screen.getByTestId('account-edit-other'))
    expect(screen.queryByLabelText('username')).not.toBeInTheDocument()

    await act(async () => {
      pending.resolve({
        account_name: 'gsb',
        credentials: { username: 'account-A-user', password: 'aaaaaaaa' },
      })
    })
    expect(screen.queryByDisplayValue('account-A-user')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('username')).not.toBeInTheDocument()

    await user.click(screen.getByTestId('reveal-credentials'))
    expect(await screen.findByLabelText('username')).toHaveValue('account-B-user')
    fireEvent.change(screen.getByLabelText('password'), {
      target: { value: 'changed-by-B-editor' },
    })
    await user.click(screen.getByTestId('account-save'))
    await waitFor(() => {
      expect(updateAccount).toHaveBeenCalledWith(
        'main/gsb',
        'test',
        'other',
        expect.objectContaining({
          credentials: { username: 'account-B-user', password: 'changed-by-B-editor' },
        }),
      )
    })
    expect(JSON.stringify(updateAccount.mock.calls)).not.toContain('account-A-user')
    expect(JSON.stringify(client.getQueryCache().getAll().map((query) => query.state.data))).not.toContain(
      'account-A-user',
    )
  })

  it('取消后迟到的账号刷新不会覆盖下一个账号', async () => {
    const user = userEvent.setup({ delay: null })
    const pending = deferred<TestAccount>()
    listEnvironments.mockResolvedValue([testEnv])
    listAccounts.mockResolvedValue([gsbAccount, otherAccount])
    updateAccount.mockRejectedValueOnce(
      new ApiHttpError(409, '配置版本冲突，请刷新后再保存', ''),
    )
    getAccount.mockImplementation((projectId: string, env: string, name: string) => {
      if (projectId === 'main/gsb' && env === 'test' && name === 'gsb') {
        return pending.promise
      }
      return Promise.resolve(otherAccount)
    })
    renderSection(<AccountSection projectId="main/gsb" />)
    await user.click(await screen.findByTestId('account-edit-gsb'))
    fireEvent.change(await screen.findByLabelText('展示名'), { target: { value: '门店' } })
    await user.click(screen.getByTestId('account-save'))
    expect(await screen.findByTestId('revision-conflict')).toBeInTheDocument()
    await user.click(screen.getByTestId('revision-refresh'))
    await user.click(screen.getByTestId('account-cancel'))
    await user.click(screen.getByTestId('account-edit-other'))
    expect(await screen.findByLabelText('展示名')).toHaveValue('另一个')

    await act(async () => {
      pending.resolve({ ...gsbAccount, display_name: 'from-account-A', revision: 9 })
    })
    expect(screen.getByLabelText('展示名')).toHaveValue('另一个')
    expect(screen.getByTestId('editing-revision')).toHaveTextContent('版本 4')
  })
})

describe('缓存项目切换', () => {
  function CachedProjects() {
    const [projectId, setProjectId] = useState('main/gsb')
    return (
      <>
        <button type="button" data-testid="switch-cached-project" onClick={() => setProjectId('main/second')}>
          切换到已缓存项目
        </button>
        <ProjectConfigPanel projectId={projectId} open onOpenChange={() => undefined} />
      </>
    )
  }

  function renderCached() {
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false, staleTime: Infinity },
        mutations: { retry: false },
      },
    })
    client.setQueryData(environmentKeys.list('main/gsb'), [testEnv])
    client.setQueryData(environmentKeys.list('main/second'), [secondEnv])
    client.setQueryData(environmentKeys.accounts('main/gsb', 'test'), [gsbAccount])
    client.setQueryData(environmentKeys.accounts('main/second', 'test'), [secondAccount])
    listEnvironments.mockImplementation(async (projectId: string) =>
      projectId === 'main/second' ? [secondEnv] : [testEnv],
    )
    listAccounts.mockImplementation(async (projectId: string) =>
      projectId === 'main/second' ? [secondAccount] : [gsbAccount],
    )
    return {
      client,
      ...render(
        <ConfigProvider theme={{ token: { motion: false } }}>
          <AntApp>
            <QueryClientProvider client={client}>
              <CachedProjects />
            </QueryClientProvider>
          </AntApp>
        </ConfigProvider>,
      ),
    }
  }

  it('目标项目已缓存时切换后账号草稿属于当前项目，保存不写旧凭据', async () => {
    const user = userEvent.setup({ delay: null })
    getAccountCredentials.mockResolvedValue({
      account_name: 'gsb',
      credentials: { username: 'project-A-user', password: 'secret-pass' },
    })
    updateAccount.mockResolvedValue(secondAccount)
    renderCached()

    await user.click(await screen.findByRole('tab', { name: '测试账号' }))
    await user.click(await screen.findByTestId('account-edit-gsb'))
    await user.click(await screen.findByTestId('reveal-credentials'))
    expect(await screen.findByLabelText('username')).toHaveValue('project-A-user')

    await user.click(screen.getByTestId('switch-cached-project'))
    expect(screen.queryByText('加载环境…')).not.toBeInTheDocument()
    expect(screen.queryByText('加载账号…')).not.toBeInTheDocument()
    expect(screen.queryByDisplayValue('project-A-user')).not.toBeInTheDocument()
    expect(screen.queryByTestId('account-editor')).not.toBeInTheDocument()
    expect(await screen.findByText('第二项目')).toBeInTheDocument()

    await user.click(screen.getByTestId('account-edit-gsb'))
    expect(screen.getByLabelText('展示名')).toHaveValue('第二项目')
    expect(screen.queryByLabelText('username')).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('展示名'), { target: { value: '第二项目已改' } })
    await user.click(screen.getByTestId('account-save'))
    await waitFor(() => {
      expect(updateAccount).toHaveBeenCalledWith(
        'main/second',
        'test',
        'gsb',
        expect.objectContaining({ display_name: '第二项目已改', revision: 5 }),
      )
    })
    const saved = updateAccount.mock.calls.at(-1)?.[3] as { credentials?: unknown }
    expect(saved.credentials).toBeUndefined()
    expect(JSON.stringify(updateAccount.mock.calls)).not.toContain('project-A-user')
  })

  it('目标项目已缓存时切换后环境草稿属于当前项目', async () => {
    const user = userEvent.setup({ delay: null })
    updateEnvironment.mockResolvedValue({ ...secondEnv, timeout_seconds: 41, revision: 4 })
    renderCached()

    await user.click(await screen.findByTestId('env-edit-test'))
    expect(screen.getByLabelText('超时（秒）')).toHaveValue('15')
    fireEvent.change(screen.getByLabelText('超时（秒）'), { target: { value: '99' } })
    expect(screen.getByLabelText('参数默认值')).toHaveValue(
      JSON.stringify({ product_keyword: 'shoes' }, null, 2),
    )

    await user.click(screen.getByTestId('switch-cached-project'))
    expect(screen.queryByText('加载环境…')).not.toBeInTheDocument()
    expect(screen.queryByDisplayValue('99')).not.toBeInTheDocument()
    expect(screen.queryByTestId('env-editor')).not.toBeInTheDocument()

    await user.click(screen.getByTestId('env-edit-test'))
    expect(screen.getByLabelText('超时（秒）')).toHaveValue('40')
    expect(screen.getByLabelText('参数默认值')).toHaveValue(
      JSON.stringify({ product_keyword: 'second-default' }, null, 2),
    )
    fireEvent.change(screen.getByLabelText('超时（秒）'), { target: { value: '41' } })
    await user.click(screen.getByTestId('env-save'))
    await waitFor(() => {
      expect(updateEnvironment).toHaveBeenCalledWith(
        'main/second',
        'test',
        expect.objectContaining({
          revision: 3,
          timeout_seconds: 41,
          case_params: { product_keyword: 'second-default' },
        }),
      )
    })
    expect(JSON.stringify(updateEnvironment.mock.calls)).not.toContain('"timeout_seconds":99')
  })
})

describe('直接请求的 401', () => {
  it('查看凭据返回 401 时清会话并引导登录，凭据不进查询缓存', async () => {
    const user = userEvent.setup({ delay: null })
    listEnvironments.mockResolvedValue([testEnv])
    listAccounts.mockResolvedValue([gsbAccount])
    getAccountCredentials.mockRejectedValue(new ApiHttpError(401, '未登录', ''))
    const { client } = renderAuthed(<AccountSection projectId="main/gsb" />)
    expect(await screen.findByTestId('current-operator')).toHaveTextContent('alice')
    await user.click(await screen.findByTestId('account-edit-gsb'))
    await user.click(await screen.findByTestId('reveal-credentials'))
    expect(await screen.findByTestId('login-page')).toBeInTheDocument()
    expect(screen.queryByTestId('account-editor')).not.toBeInTheDocument()
    expect(screen.queryByTestId('current-operator')).not.toBeInTheDocument()
    expect(client.getQueryData(authKeys.me)).toBeNull()
    const cached = JSON.stringify(client.getQueryCache().getAll().map((query) => query.state.data))
    expect(cached).not.toContain('secret-pass')
    expect(cached).not.toContain('credentials')
  })

  it('账号冲突刷新返回 401 时清会话并引导登录', async () => {
    const user = userEvent.setup({ delay: null })
    listEnvironments.mockResolvedValue([testEnv])
    listAccounts.mockResolvedValue([gsbAccount])
    updateAccount.mockRejectedValueOnce(
      new ApiHttpError(409, '配置版本冲突，请刷新后再保存', ''),
    )
    getAccount.mockRejectedValue(new ApiHttpError(401, '未登录', ''))
    const { client } = renderAuthed(<AccountSection projectId="main/gsb" />)
    await user.click(await screen.findByTestId('account-edit-gsb'))
    fireEvent.change(await screen.findByLabelText('展示名'), { target: { value: '门店' } })
    await user.click(screen.getByTestId('account-save'))
    expect(await screen.findByTestId('revision-refresh')).toBeInTheDocument()
    await user.click(screen.getByTestId('revision-refresh'))
    expect(await screen.findByTestId('login-page')).toBeInTheDocument()
    expect(screen.queryByTestId('account-editor')).not.toBeInTheDocument()
    expect(client.getQueryData(authKeys.me)).toBeNull()
  })

  it('环境冲突刷新返回 401 时清会话并引导登录', async () => {
    const user = userEvent.setup({ delay: null })
    listEnvironments.mockResolvedValue([testEnv])
    updateEnvironment.mockRejectedValueOnce(
      new ApiHttpError(409, '配置版本冲突，请刷新后再保存', ''),
    )
    getEnvironment.mockRejectedValue(new ApiHttpError(401, '未登录', ''))
    const { client } = renderAuthed(<EnvironmentSection projectId="main/gsb" />)
    await user.click(await screen.findByTestId('env-edit-test'))
    fireEvent.change(screen.getByLabelText('超时（秒）'), { target: { value: '18' } })
    await user.click(screen.getByTestId('env-save'))
    expect(await screen.findByTestId('revision-refresh')).toBeInTheDocument()
    await user.click(screen.getByTestId('revision-refresh'))
    expect(await screen.findByTestId('login-page')).toBeInTheDocument()
    expect(screen.queryByTestId('env-editor')).not.toBeInTheDocument()
    expect(client.getQueryData(authKeys.me)).toBeNull()
  })
})
