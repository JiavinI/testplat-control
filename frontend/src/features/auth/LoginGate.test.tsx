import type { ReactNode } from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useQuery } from '@tanstack/react-query'
import { QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { ConfigProvider, App as AntApp } from 'antd'
import { ApiHttpError } from '@/shared/api/errors'
import { createAppQueryClient } from '@/app/queryClient'
import { AppLayout } from '@/app/AppLayout'
import { RequireAuth } from './RequireAuth'

const getMe = vi.fn()
const login = vi.fn()
const logout = vi.fn()
const register = vi.fn()

vi.mock('./api', () => ({
  getMe: (...args: unknown[]) => getMe(...args),
  login: (...args: unknown[]) => login(...args),
  logout: (...args: unknown[]) => logout(...args),
  register: (...args: unknown[]) => register(...args),
}))

function Boom() {
  const query = useQuery({
    queryKey: ['projects', 'boom'],
    queryFn: async () => {
      throw new ApiHttpError(401, '未登录', '')
    },
    retry: false,
  })
  return <div>{query.isError ? '请求失败' : '项目列表'}</div>
}

function renderGate(child: ReactNode = <div>项目列表</div>) {
  const client = createAppQueryClient()
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntApp>
        <QueryClientProvider client={client}>
          <MemoryRouter initialEntries={['/projects']}>
            <Routes>
              <Route element={<AppLayout />}>
                <Route element={<RequireAuth />}>
                  <Route path="/projects" element={child} />
                </Route>
              </Route>
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>,
  )
}

beforeEach(() => {
  getMe.mockReset()
  login.mockReset()
  logout.mockReset()
  register.mockReset()
})

describe('登录态', () => {
  it('未登录时引导登录，顶栏没有操作人', async () => {
    getMe.mockRejectedValue(new ApiHttpError(401, '未登录', ''))
    renderGate()
    expect(await screen.findByTestId('login-guidance')).toHaveTextContent('401')
    expect(screen.getByTestId('auth-submit')).toHaveTextContent(/登\s*录/)
    expect(screen.queryByText('项目列表')).not.toBeInTheDocument()
    expect(screen.queryByTestId('current-operator')).not.toBeInTheDocument()
  })

  it('登录后顶栏显示操作人，注销后回到登录', async () => {
    const user = userEvent.setup({ delay: null })
    getMe.mockRejectedValue(new ApiHttpError(401, '未登录', ''))
    login.mockImplementation(async () => {
      getMe.mockResolvedValue({ username: 'alice' })
      return { username: 'alice' }
    })
    logout.mockImplementation(async () => {
      getMe.mockRejectedValue(new ApiHttpError(401, '未登录', ''))
    })
    renderGate()
    await screen.findByTestId('login-page')
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'alice' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'password-1' } })
    await user.click(screen.getByTestId('auth-submit'))
    expect(await screen.findByTestId('current-operator')).toHaveTextContent('alice')
    expect(screen.getByText('项目列表')).toBeInTheDocument()
    expect(login).toHaveBeenCalledWith({ username: 'alice', password: 'password-1' })

    await user.click(screen.getByTestId('logout-button'))
    expect(await screen.findByTestId('login-guidance')).toBeInTheDocument()
    expect(screen.queryByTestId('current-operator')).not.toBeInTheDocument()
  })

  it('注册成功后进入已登录状态', async () => {
    const user = userEvent.setup({ delay: null })
    getMe.mockRejectedValue(new ApiHttpError(401, '未登录', ''))
    register.mockResolvedValue({ username: 'bob' })
    renderGate()
    await screen.findByTestId('login-page')
    await user.click(screen.getByRole('tab', { name: '注册' }))
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'bob' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'password-1' } })
    await user.click(screen.getByTestId('auth-submit'))
    await waitFor(() => {
      expect(register).toHaveBeenCalledWith({ username: 'bob', password: 'password-1' })
    })
    expect(await screen.findByTestId('current-operator')).toHaveTextContent('bob')
  })

  it('已登录后业务请求 401 会引导重新登录', async () => {
    getMe.mockResolvedValue({ username: 'alice' })
    renderGate(<Boom />)
    expect(await screen.findByTestId('login-guidance')).toBeInTheDocument()
    expect(screen.queryByText('项目列表')).not.toBeInTheDocument()
  })
})
