import type { ReactElement } from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider, App as AntApp } from 'antd'
import { ApiHttpError } from '@/shared/api/errors'
import { AccountSection } from './AccountSection'
import { EnvironmentSection } from './EnvironmentSection'
import type { ProjectEnvironment, TestAccount } from './types'

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
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntApp>
        <QueryClientProvider client={client}>{node}</QueryClientProvider>
      </AntApp>
    </ConfigProvider>,
  )
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
})
