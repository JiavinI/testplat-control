import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider } from 'antd'
import { useState } from 'react'
import { AssetBrowser } from './AssetBrowser'
import type { AssetDetails, AssetNode } from './types'
import { ApiHttpError } from '@/shared/api/errors'

const treeA: AssetNode = {
  id: 'assets',
  name: 'assets',
  type: 'directory',
  path: '.',
  children: [
    {
      id: 'api',
      name: 'api',
      type: 'directory',
      path: 'api',
      children: [
        {
          id: 'api.common',
          name: 'common',
          type: 'directory',
          path: 'api/common',
          children: [
            {
              id: 'api.common.health_check',
              name: 'health_check.yaml',
              type: 'file',
              path: 'api/common/health_check.yaml',
              metadata: { method: 'GET' },
            },
          ],
        },
      ],
    },
    {
      id: 'scenarios',
      name: 'scenarios',
      type: 'directory',
      path: 'scenarios',
      children: [
        {
          id: 'scenarios.login',
          name: 'login.case.yaml',
          type: 'file',
          path: 'scenarios/login.case.yaml',
          metadata: { type: 'case' },
        },
      ],
    },
  ],
}

const treeB: AssetNode = {
  id: 'assets',
  name: 'assets',
  type: 'directory',
  path: '.',
  children: [
    {
      id: 'api',
      name: 'api',
      type: 'directory',
      path: 'api',
      children: [
        {
          id: 'api.other',
          name: 'other.yaml',
          type: 'file',
          path: 'api/other.yaml',
        },
      ],
    },
  ],
}

const healthDetails: AssetDetails = {
  id: 'api.common.health_check',
  name: 'health_check.yaml',
  type: 'file',
  path: 'api/common/health_check.yaml',
  metadata: { method: 'GET', url: '/health', api_id: 'api.common.health_check' },
}

const getAssetsTree = vi.fn()
const getAssetDetails = vi.fn()

vi.mock('./api', () => ({
  getAssetsTree: (...args: unknown[]) => getAssetsTree(...args),
  getAssetDetails: (...args: unknown[]) => getAssetDetails(...args),
}))

function renderBrowser(props: {
  projectId: string
  selectedAssetId?: string
  onSelectAsset?: (asset: AssetNode) => void
}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const onSelectAsset = props.onSelectAsset ?? vi.fn()
  const result = render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <QueryClientProvider client={client}>
        <AssetBrowser
          projectId={props.projectId}
          selectedAssetId={props.selectedAssetId}
          onSelectAsset={onSelectAsset}
        />
      </QueryClientProvider>
    </ConfigProvider>,
  )
  return { ...result, onSelectAsset, client }
}

function ControlledBrowser({
  initialProjectId,
}: {
  initialProjectId: string
}) {
  const [projectId, setProjectId] = useState(initialProjectId)
  const [selectedAssetId, setSelectedAssetId] = useState<string | undefined>()
  return (
    <div>
      <button type="button" onClick={() => setProjectId('p-b')}>
        切换到项目B
      </button>
      <AssetBrowser
        projectId={projectId}
        selectedAssetId={selectedAssetId}
        onSelectAsset={(asset) => setSelectedAssetId(asset.id)}
      />
    </div>
  )
}


function clickTreeNode(user: ReturnType<typeof userEvent.setup>, assetId: string) {
  const el = document.querySelector(`[data-asset-id="${assetId}"]`)
  if (!el) {
    throw new Error(`tree node not found: ${assetId}`)
  }
  return user.click(el)
}

beforeEach(() => {
  getAssetsTree.mockReset()
  getAssetDetails.mockReset()
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('AssetBrowser', () => {
  it('加载并展示资产树节点', async () => {
    getAssetsTree.mockResolvedValue(treeA)
    renderBrowser({ projectId: 'p-a' })
    expect(await screen.findByText('api')).toBeInTheDocument()
    expect(screen.getByTestId('asset-tree')).toBeInTheDocument()
    expect(getAssetDetails).not.toHaveBeenCalled()
  })

  it('本地过滤保留祖先，清空后恢复', async () => {
    const user = userEvent.setup({ delay: null })
    getAssetsTree.mockResolvedValue(treeA)
    renderBrowser({ projectId: 'p-a' })
    await screen.findByText('scenarios')

    const filter = screen.getByLabelText('过滤资产')
    await user.clear(filter)
    await user.type(filter, 'health_check')

    expect(await screen.findByText('health_check.yaml')).toBeInTheDocument()
    // 祖先仍在
    expect(document.querySelector('[data-asset-id="api"]')).toBeTruthy()
    expect(document.querySelector('[data-asset-id="api.common"]')).toBeTruthy()
    // 未命中的 scenarios 消失
    expect(document.querySelector('[data-asset-id="scenarios"]')).toBeNull()

    await user.clear(filter)
    expect(await screen.findByText('scenarios')).toBeInTheDocument()
  })

  it('选中文件才请求详情；目录不请求', async () => {
    const user = userEvent.setup({ delay: null })
    getAssetsTree.mockResolvedValue(treeA)
    getAssetDetails.mockResolvedValue(healthDetails)

    function Harness() {
      const [selected, setSelected] = useState<string | undefined>()
      return (
        <AssetBrowser
          projectId="p-a"
          selectedAssetId={selected}
          onSelectAsset={(a) => setSelected(a.id)}
        />
      )
    }

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <QueryClientProvider client={client}>
          <Harness />
        </QueryClientProvider>
      </ConfigProvider>,
    )

    await screen.findByText('scenarios')
    await clickTreeNode(user, 'api')
    await clickTreeNode(user, 'api.common')
    await clickTreeNode(user, 'api.common.health_check')

    await waitFor(() => {
      expect(getAssetDetails).toHaveBeenCalledWith('p-a', 'api.common.health_check')
    })

    const panel = await screen.findByTestId('asset-detail-panel')
    expect(within(panel).getByText('可运行（api.*）')).toBeInTheDocument()
    expect(within(panel).getByText('/health')).toBeInTheDocument()
    // 无运行按钮
    expect(screen.queryByRole('button', { name: /运行/ })).not.toBeInTheDocument()

    getAssetDetails.mockClear()
    await clickTreeNode(user, 'api')
    await waitFor(() => {
      expect(screen.getByText(/目录仅供浏览/)).toBeInTheDocument()
    })
    expect(getAssetDetails).not.toHaveBeenCalled()
  })

  it('选中非 api 文件显示只读且不出现运行按钮', async () => {
    const user = userEvent.setup({ delay: null })
    getAssetsTree.mockResolvedValue(treeA)
    getAssetDetails.mockResolvedValue({
      id: 'scenarios.login',
      name: 'login.case.yaml',
      type: 'file',
      path: 'scenarios/login.case.yaml',
      metadata: { type: 'case' },
    })

    function Harness() {
      const [selected, setSelected] = useState<string | undefined>()
      return (
        <AssetBrowser
          projectId="p-a"
          selectedAssetId={selected}
          onSelectAsset={(a) => setSelected(a.id)}
        />
      )
    }

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <QueryClientProvider client={client}>
          <Harness />
        </QueryClientProvider>
      </ConfigProvider>,
    )

    await screen.findByText('scenarios')
    await clickTreeNode(user, 'scenarios')
    await clickTreeNode(user, 'scenarios.login')

    const panel = await screen.findByTestId('asset-detail-panel')
    expect(within(panel).getByText(/只读 · 当前不可运行/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /运行/ })).not.toBeInTheDocument()
  })

  it('树加载失败可重试', async () => {
    const user = userEvent.setup({ delay: null })
    getAssetsTree
      .mockRejectedValueOnce(new Error('scan failed'))
      .mockResolvedValueOnce(treeA)
    renderBrowser({ projectId: 'p-a' })

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByText('api')).toBeInTheDocument()
  })

  it('项目 404 展示错误态', async () => {
    getAssetsTree.mockRejectedValue(
      new ApiHttpError(404, 'Project not found', '{"detail":"Project not found"}'),
    )
    renderBrowser({ projectId: 'missing' })
    expect(await screen.findByText('项目不存在')).toBeInTheDocument()
  })

  it('项目切换后不再展示旧项目节点，且不带着旧选择拉详情', async () => {
    const user = userEvent.setup({ delay: null })
    getAssetsTree.mockImplementation(async (projectId: string) => {
      if (projectId === 'p-a') return treeA
      if (projectId === 'p-b') return treeB
      throw new Error('unknown project')
    })
    getAssetDetails.mockResolvedValue(healthDetails)

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <QueryClientProvider client={client}>
          <ControlledBrowser initialProjectId="p-a" />
        </QueryClientProvider>
      </ConfigProvider>,
    )

    await screen.findByText('scenarios')
    // 先选中 A 的文件
    await clickTreeNode(user, 'api')
    await clickTreeNode(user, 'api.common')
    await clickTreeNode(user, 'api.common.health_check')
    await waitFor(() => {
      expect(getAssetDetails).toHaveBeenCalled()
    })

    getAssetDetails.mockClear()
    await user.click(screen.getByRole('button', { name: '切换到项目B' }))

    await waitFor(() => {
      expect(getAssetsTree).toHaveBeenCalledWith('p-b')
    })
    // 新树第一层目录应自动展开，文件可见
    await waitFor(() => {
      expect(document.querySelector('[data-asset-id="api.other"]')).toBeTruthy()
    })
    expect(document.querySelector('[data-asset-id="api.common.health_check"]')).toBeNull()
    expect(document.querySelector('[data-asset-id="scenarios"]')).toBeNull()
    // 旧 selectedAssetId 不在新树中 → 不拉详情
    await waitFor(() => {
      expect(getAssetDetails).not.toHaveBeenCalled()
    })
    expect(screen.getByText(/选择左侧资产以查看元信息/)).toBeInTheDocument()
  })

  it('选择回调传递完整 AssetNode', async () => {
    const user = userEvent.setup({ delay: null })
    getAssetsTree.mockResolvedValue(treeA)
    const onSelectAsset = vi.fn()
    renderBrowser({ projectId: 'p-a', onSelectAsset })

    await screen.findByText('scenarios')
    await clickTreeNode(user, 'api')
    expect(onSelectAsset).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'api', type: 'directory', path: 'api' }),
    )
  })
})
