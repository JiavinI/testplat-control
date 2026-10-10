import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { ConfigProvider, App as AntApp } from 'antd'
import { ProjectListPage } from '@/pages/ProjectListPage'
import type { ProjectResponse } from '@/shared/types/project'

const sample: ProjectResponse = {
  id: 'p-1',
  name: 'alpha',
  env: 'test',
  assets_root: '/assets/alpha',
  config_root: '/config/alpha',
  created_at: '2026-10-10T00:00:00.000Z',
  updated_at: '2026-10-10T01:00:00.000Z',
}

const listProjects = vi.fn()
const createProject = vi.fn()
const updateProject = vi.fn()
const deleteProject = vi.fn()

vi.mock('./api', () => ({
  listProjects: (...args: unknown[]) => listProjects(...args),
  createProject: (...args: unknown[]) => createProject(...args),
  updateProject: (...args: unknown[]) => updateProject(...args),
  deleteProject: (...args: unknown[]) => deleteProject(...args),
  getProject: vi.fn(),
}))

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <ConfigProvider>
      <AntApp>
        <QueryClientProvider client={client}>
          <MemoryRouter initialEntries={['/projects']}>
            <Routes>
              <Route path="/projects" element={<ProjectListPage />} />
              <Route path="/projects/:projectId" element={<div>workspace</div>} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>,
  )
}

beforeEach(() => {
  listProjects.mockReset()
  createProject.mockReset()
  updateProject.mockReset()
  deleteProject.mockReset()
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('ProjectListPage CRUD', () => {
  it('空态展示新建引导', async () => {
    listProjects.mockResolvedValue([])
    renderPage()
    expect(await screen.findByText(/还没有项目/)).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /新建项目/ }).length).toBeGreaterThan(0)
  })

  it('列表渲染名称/环境/资产目录/更新时间，不出现最后运行', async () => {
    listProjects.mockResolvedValue([sample])
    renderPage()
    expect(await screen.findByText('alpha')).toBeInTheDocument()
    expect(screen.getByText('test')).toBeInTheDocument()
    expect(screen.getByText('/assets/alpha')).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: /最后运行/ })).not.toBeInTheDocument()
  })

  it('创建成功后进入工作台路由', async () => {
    const user = userEvent.setup()
    listProjects.mockResolvedValue([])
    createProject.mockResolvedValue({ ...sample, id: 'new-1', name: 'beta' })
    renderPage()

    await user.click(await screen.findByRole('button', { name: /新建项目/ }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText(/项目名称/), 'beta')
    await user.type(within(dialog).getByLabelText(/资产目录/), '/assets/beta')
    await user.type(within(dialog).getByLabelText(/配置目录/), '/config/beta')
    await user.click(within(dialog).getByRole('button', { name: /确\s*定|OK/i }))

    await waitFor(() => {
      expect(createProject).toHaveBeenCalledWith(
        expect.objectContaining({
          name: 'beta',
          assets_root: '/assets/beta',
          config_root: '/config/beta',
        }),
      )
    })
    expect(await screen.findByText('workspace')).toBeInTheDocument()
  })

  it('删除需二次确认', async () => {
    const user = userEvent.setup()
    listProjects.mockResolvedValue([sample])
    deleteProject.mockResolvedValue({ message: 'Project deleted successfully' })
    renderPage()

    await screen.findByText('alpha')
    await user.click(screen.getByRole('button', { name: /删除项目 alpha/ }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent(/确认删除该项目/)
    // 未点确认前不应调用删除 API
    expect(deleteProject).not.toHaveBeenCalled()
    await user.click(within(dialog).getByRole('button', { name: /删\s*除/ }))

    await waitFor(() => {
      expect(deleteProject).toHaveBeenCalledWith('p-1')
    })
  })

  it('加载失败可重试', async () => {
    const user = userEvent.setup()
    listProjects
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce([sample])
    renderPage()

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByText('alpha')).toBeInTheDocument()
  })
})
