import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { ConfigProvider, App as AntApp } from 'antd'
import { ProjectListPage } from '@/pages/ProjectListPage'
import type { ProjectResponse, RepoResponse } from '@/shared/types/project'

const sampleProject: ProjectResponse = {
  id: 'main/alpha',
  repo: 'main',
  project: 'alpha',
  name: 'alpha',
  envs: ['test'],
  default_env: 'test',
  archived: false,
  commit_sha: 'abcdef0123456789abcdef0123456789abcdef01',
  created_at: '2026-10-10T00:00:00.000Z',
  updated_at: '2026-10-10T01:00:00.000Z',
}

const archivedProject: ProjectResponse = {
  ...sampleProject,
  id: 'main/legacy',
  project: 'legacy',
  name: 'legacy',
  archived: true,
  commit_sha: 'abcdef0123456789abcdef0123456789abcdef01',
}

const sampleRepo: RepoResponse = {
  key: 'main',
  branch: 'main',
  current_sha: 'abcdef0123456789abcdef0123456789abcdef01',
  last_sync_at: '2026-10-15T01:00:00.000Z',
  last_sync_result: 'ok',
}

const listProjects = vi.fn()
const listRepos = vi.fn()
const syncRepo = vi.fn()

vi.mock('./api', () => ({
  listProjects: (...args: unknown[]) => listProjects(...args),
  getProject: vi.fn(),
}))

vi.mock('@/features/repos/api', () => ({
  listRepos: (...args: unknown[]) => listRepos(...args),
  syncRepo: (...args: unknown[]) => syncRepo(...args),
}))

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntApp>
        <QueryClientProvider client={client}>
          <MemoryRouter initialEntries={['/projects']}>
            <Routes>
              <Route path="/projects" element={<ProjectListPage />} />
              <Route
                path="/projects/:repo/:project"
                element={<div data-testid="workspace-route">workspace</div>}
              />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>,
  )
}

beforeEach(() => {
  listProjects.mockReset()
  listRepos.mockReset()
  syncRepo.mockReset()
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('ProjectListPage Phase 4.0', () => {
  it('空态无新建入口，提示服务端配置仓库', async () => {
    listProjects.mockResolvedValue([])
    listRepos.mockResolvedValue([])
    renderPage()
    expect(await screen.findByText(/尚未配置用例仓库/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /新建项目/ })).not.toBeInTheDocument()
  })

  it('按仓库分组显示短 SHA 与同步结果，无编辑/删除', async () => {
    listProjects.mockResolvedValue([sampleProject, archivedProject])
    listRepos.mockResolvedValue([sampleRepo])
    renderPage()
    expect(await screen.findByTestId('repo-group-main')).toBeInTheDocument()
    expect(screen.getByTestId('repo-sha-main')).toHaveTextContent('abcdef0')
    expect(screen.getByTestId('repo-sync-result-main')).toHaveTextContent('成功')
    expect(screen.getByText('alpha')).toBeInTheDocument()
    expect(screen.getByText('legacy')).toBeInTheDocument()
    expect(screen.getByText('已归档')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /编辑/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /删除/ })).not.toBeInTheDocument()
    expect(screen.queryByText(/assets_root|资产目录/)).not.toBeInTheDocument()
  })

  it('同步成功刷新列表', async () => {
    const user = userEvent.setup({ delay: null })
    listProjects.mockResolvedValue([sampleProject])
    listRepos.mockResolvedValue([sampleRepo])
    syncRepo.mockResolvedValue({
      repo: 'main',
      ok: true,
      category: 'ok',
      commit_sha: '1111222233334444555566667777888899990000',
    })
    renderPage()
    await screen.findByTestId('sync-repo-main')
    await user.click(screen.getByTestId('sync-repo-main'))
    await waitFor(() => {
      expect(syncRepo).toHaveBeenCalledWith('main')
    })
    await waitFor(() => {
      expect(listRepos.mock.calls.length).toBeGreaterThan(1)
    })
  })

  it('同步失败展示类别中文文案', async () => {
    const user = userEvent.setup({ delay: null })
    listProjects.mockResolvedValue([sampleProject])
    listRepos.mockResolvedValue([
      { ...sampleRepo, last_sync_result: 'network' },
    ])
    syncRepo.mockResolvedValue({
      repo: 'main',
      ok: false,
      category: 'auth',
      commit_sha: sampleRepo.current_sha,
    })
    renderPage()
    expect(await screen.findByTestId('repo-sync-result-main')).toHaveTextContent(
      '网络错误',
    )
    // 列表上已有失败类别；再点同步失败应 toast（文案含认证失败）
    await user.click(screen.getByTestId('sync-repo-main'))
    await waitFor(() => {
      expect(syncRepo).toHaveBeenCalled()
    })
    expect(await screen.findByText(/同步失败：认证失败/)).toBeInTheDocument()
  })

  it('打开工作台走两段式路由', async () => {
    const user = userEvent.setup({ delay: null })
    listProjects.mockResolvedValue([sampleProject])
    listRepos.mockResolvedValue([sampleRepo])
    renderPage()
    await screen.findByText('alpha')
    await user.click(screen.getByRole('button', { name: '打开工作台 alpha' }))
    expect(await screen.findByTestId('workspace-route')).toBeInTheDocument()
  })

  it('加载失败可重试', async () => {
    const user = userEvent.setup({ delay: null })
    listProjects.mockRejectedValueOnce(new Error('boom')).mockResolvedValue([sampleProject])
    listRepos.mockResolvedValue([sampleRepo])
    renderPage()
    expect(await screen.findByRole('button', { name: /重试/ })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /重试/ }))
    expect(await screen.findByText('alpha')).toBeInTheDocument()
  })
})
