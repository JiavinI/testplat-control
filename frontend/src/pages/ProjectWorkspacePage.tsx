import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Collapse,
  Drawer,
  Select,
  Space,
  Typography,
} from 'antd'
import {
  FolderOpenOutlined,
} from '@ant-design/icons'
import { Link, useParams } from 'react-router-dom'
import {
  AssetBrowser,
  AssetDetailPanel,
  findAssetById,
  isRunnableApiAsset,
  isRunnableCaseAsset,
  useAssetDetails,
  useAssetsTree,
  type AssetNode,
} from '@/features/assets'
import {
  ApiExecutionPanel,
  CaseExecutionPanel,
  CaseMetaPanel,
  ExecutionHistory,
} from '@/features/executions'
import { ApiInfoPanel } from '@/features/assets/ApiInfoPanel'
import { useCaseAssetDetail } from '@/features/executions/hooks'
import { StoredParameters } from '@/features/executions/StoredParameters'
import { useEnvironments } from '@/features/environments/hooks'
import { useProject } from '@/features/projects/hooks'
import { joinProjectId } from '@/shared/project/ids'
import { shortSha } from '@/shared/project/display'
import { SECTIONS, sectionPath, type WorkspaceSection } from '@/shared/project/sections'
import { treeForSection } from '@/features/assets/treeUtils'
import {
  resolveInitialEnv,
  writePreferredEnv,
} from '@/shared/project/envPreference'
import { ErrorState, LoadingState } from '@/shared/ui/AsyncState'

/** 窄屏用抽屉挂载资产树；jsdom stub 的 matchMedia 恒为 false，测试走桌面布局 */
function useIsNarrowViewport(query = '(max-width: 767px)'): boolean {
  const [narrow, setNarrow] = useState(false)
  useEffect(() => {
    const mq = window.matchMedia(query)
    const update = () => setNarrow(mq.matches)
    update()
    mq.addEventListener('change', update)
    return () => mq.removeEventListener('change', update)
  }, [query])
  return narrow
}

export type ProjectWorkspacePageProps = {
  section?: Exclude<WorkspaceSection, 'configuration'>
  headerPrefix?: React.ReactNode
  alerts?: React.ReactNode
}

/**
 * 项目工作台：组合资产浏览、API/Case 执行与执行历史。
 * api.* 挂动态参数面板；case.* 挂文件元信息 + 运行（步骤只来自运行/历史）。
 * 运行环境下拉只使用该项目已启用的数据库环境，不回退 Git 示例环境。
 */
export function ProjectWorkspacePage({
  section = 'apis',
  headerPrefix,
  alerts,
}: ProjectWorkspacePageProps) {
  const { repo = '', project: projectKey = '' } = useParams()
  const projectId = repo && projectKey ? joinProjectId(repo, projectKey) : ''
  const projectQuery = useProject(projectId)
  const environmentQuery = useEnvironments(section === 'pages' ? '' : projectId)
  const isNarrow = useIsNarrowViewport()

  const [selectedAssetId, setSelectedAssetId] = useState<string | undefined>()
  const [assetDrawerOpen, setAssetDrawerOpen] = useState(false)
  const [selectedEnv, setSelectedEnv] = useState<string | null>(null)

  // 项目切换时清空选中与抽屉，避免串数据
  useEffect(() => {
    setSelectedAssetId(undefined)
    setAssetDrawerOpen(false)
    setSelectedEnv(null)
  }, [projectId, section])

  // 只在启用的数据库环境里解析初始值。没有启用环境时不沿用 Git envs。
  useEffect(() => {
    if (!projectQuery.data || !environmentQuery.data) {
      return
    }
    const enabled = environmentQuery.data
      .filter((item) => item.enabled)
      .map((item) => item.env)
    setSelectedEnv(
      resolveInitialEnv(
        projectQuery.data.id,
        enabled,
        projectQuery.data.default_env,
      ),
    )
  }, [projectQuery.data, environmentQuery.data])

  const treeQuery = useAssetsTree(projectId)

  const scopedTree = useMemo(() => treeQuery.data ? treeForSection(treeQuery.data, section) : null, [treeQuery.data, section])

  const selectedFromTree = useMemo(() => {
    if (!scopedTree || !selectedAssetId) {
      return null
    }
    return findAssetById(scopedTree, selectedAssetId)
  }, [scopedTree, selectedAssetId])

  const isCase =
    selectedFromTree !== null && isRunnableCaseAsset(selectedFromTree)
  const isApi =
    selectedFromTree !== null && isRunnableApiAsset(selectedFromTree)

  const shouldFetchApiDetails = Boolean(
    selectedFromTree && selectedFromTree.type === 'file' && !isCase,
  )
  const detailsQuery = useAssetDetails(
    projectId,
    selectedFromTree?.type === 'file' && !isCase
      ? selectedFromTree.id
      : undefined,
    shouldFetchApiDetails,
  )

  const caseDetailQuery = useCaseAssetDetail(
    projectId,
    isCase && selectedFromTree ? selectedFromTree.id : undefined,
    isCase,
  )

  const handleSelectAsset = (asset: AssetNode) => {
    setSelectedAssetId(asset.id)
    if (isNarrow) {
      setAssetDrawerOpen(false)
    }
  }

  const handleEnvChange = (env: string) => {
    setSelectedEnv(env)
    if (projectId) {
      writePreferredEnv(projectId, env)
    }
  }

  if (projectQuery.isLoading) {
    return <LoadingState tip="加载项目…" />
  }

  if (projectQuery.isError) {
    return (
      <div>
        <Space style={{ marginBottom: 16 }}>
          <Link to={sectionPath(section)}>
            <Button>选择项目</Button>
          </Link>
        </Space>
        <ErrorState
          error={projectQuery.error}
          onRetry={() => {
            void projectQuery.refetch()
          }}
        />
      </div>
    )
  }

  const project = projectQuery.data
  if (!project) {
    return (
      <ErrorState
        error={new Error('项目不存在')}
        onRetry={() => {
          void projectQuery.refetch()
        }}
      />
    )
  }

  const enabledEnvNames = (environmentQuery.data ?? [])
    .filter((item) => item.enabled)
    .map((item) => item.env)
  const historyEnvNames = (environmentQuery.data ?? []).map((item) => item.env)
  const envOptions = enabledEnvNames.map((envName) => ({ value: envName, label: envName }))
  const canRun = Boolean(selectedEnv && enabledEnvNames.includes(selectedEnv))
  const noEnabledEnv = environmentQuery.isSuccess && enabledEnvNames.length === 0
  const apiDetails = detailsQuery.data ?? selectedFromTree
  const apiMetadata = apiDetails?.metadata
  const requestDefinition = apiMetadata?.request && typeof apiMetadata.request === 'object'
    && !Array.isArray(apiMetadata.request) ? apiMetadata.request as Record<string, unknown> : undefined
  const activeEnvironment = environmentQuery.data?.find((item) => item.env === selectedEnv && item.enabled)
  const missingApiHost = isApi && typeof apiMetadata?.host === 'string'
    && !activeEnvironment?.api_hosts[apiMetadata.host]

  const browser = (
    <AssetBrowser
      projectId={projectId}
      selectedAssetId={selectedFromTree?.id}
      onSelectAsset={handleSelectAsset}
      layout="tree"
      section={section}
    />
  )

  const centerColumn = (
    <div
      data-testid="workspace-main"
      className="tp-workspace-main"
      style={{
        flex: '1 1 360px',
        minWidth: 0,
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
      }}
    >
      <section
        key={selectedFromTree?.id ?? 'empty'}
        data-testid="workspace-asset-meta"
        aria-label="资产元信息"
        className="tp-surface tp-pane-enter"
        style={{
          padding: 16,
        }}
      >
        {isCase && selectedFromTree ? (
          <CaseMetaPanel
            caseId={selectedFromTree.id}
            detail={caseDetailQuery.data}
            loading={caseDetailQuery.isLoading || caseDetailQuery.isFetching}
            error={caseDetailQuery.error}
            onRetry={() => {
              void caseDetailQuery.refetch()
            }}
          />
        ) : isApi && apiDetails && !detailsQuery.isError && (!detailsQuery.isLoading || detailsQuery.data) ? (
          <ApiInfoPanel asset={apiDetails} environment={activeEnvironment} projectId={projectId} />
        ) : (
          <AssetDetailPanel
            selectedFromTree={selectedFromTree}
            details={detailsQuery.data}
            detailsLoading={detailsQuery.isLoading || detailsQuery.isFetching}
            detailsError={detailsQuery.error}
            onRetryDetails={() => {
              void detailsQuery.refetch()
            }}
          />
        )}
      </section>

      {noEnabledEnv && (isApi || isCase) ? (
        <Alert
          type="warning"
          showIcon
          message="还没有启用的环境，无法运行"
          data-testid="workspace-env-required"
        />
      ) : null}
      {!noEnabledEnv && !canRun && (isApi || isCase) ? (
        <Alert
          type="warning"
          showIcon
          message="请先选择运行环境"
          data-testid="workspace-env-required"
        />
      ) : null}

      {isApi && selectedFromTree && selectedEnv && canRun && !detailsQuery.isLoading && !detailsQuery.isError ? (
        <StoredParameters key={`${projectId}:${selectedFromTree.id}:${selectedEnv}:${project.commit_sha}`} projectId={projectId} assetType="api" assetId={selectedFromTree.id} env={selectedEnv} commit={project.commit_sha ?? ''}>
          {(context) =>
        <ApiExecutionPanel
          parameterContext={context}
          key={`${projectId}:${selectedFromTree.id}:${selectedEnv}`}
          projectId={projectId}
          assetId={selectedFromTree.id}
          env={selectedEnv}
          requestDefinition={requestDefinition}
          runDisabled={Boolean(missingApiHost)}
          caseParams={
            environmentQuery.data?.find((item) => item.env === selectedEnv)?.case_params
          }
        />
          }
        </StoredParameters>
      ) : null}

      {isCase && selectedFromTree && selectedEnv && canRun ? (
        <StoredParameters key={`${projectId}:${selectedFromTree.id}:${selectedEnv}:${project.commit_sha}`} projectId={projectId} assetType="case" assetId={selectedFromTree.id} env={selectedEnv} commit={project.commit_sha ?? ''}>
          {(context) =>
        <CaseExecutionPanel
          parameterContext={context}
          key={`${projectId}:case:${selectedFromTree.id}:${selectedEnv}`}
          projectId={projectId}
          caseId={selectedFromTree.id}
          env={selectedEnv}
          assetDefaults={
            selectedFromTree.metadata?.params && typeof selectedFromTree.metadata.params === 'object' && !Array.isArray(selectedFromTree.metadata.params)
              ? selectedFromTree.metadata.params as Record<string, unknown> : undefined
          }
          caseParams={activeEnvironment?.case_params}
        />
          }
        </StoredParameters>
      ) : null}

      {!isApi && !isCase && selectedFromTree ? (
        <Typography.Paragraph
          type="secondary"
          style={{ margin: 0 }}
          data-testid="workspace-capability-note"
        >
          {selectedFromTree.type === 'directory'
            ? '目录仅供浏览，不提供参数或运行。'
            : section === 'pages' ? 'Page 定义可查看，页面执行能力尚未接入。' : '该文件供浏览引用，无独立执行面板。'}
        </Typography.Paragraph>
      ) : null}

      {section === 'apis' ? <Collapse size="small" items={[{
        key: `${projectId}:${selectedFromTree?.id ?? 'all'}`, label: '执行历史',
        children: <ExecutionHistory
          key={`${projectId}:${selectedFromTree?.id ?? 'all'}`}
          assetTypeScope="api" projectId={projectId}
          assetId={selectedFromTree?.type === 'file' ? selectedFromTree.id : undefined}
          envs={historyEnvNames}
        />,
      }]} /> : section === 'scenarios' ? <ExecutionHistory
        key={`${projectId}:${section}`} assetTypeScope="case" projectId={projectId}
        assetId={selectedFromTree?.type === 'file' ? selectedFromTree.id : undefined}
        envs={historyEnvNames}
      /> : null}
    </div>
  )

  return (
    <div
      data-testid="project-workspace"
      className="tp-project-workspace"
      style={{ maxWidth: '100%', overflowX: 'hidden' }}
    >
      <div className="tp-workspace-toolbar">
        <div className="tp-workspace-toolbar__left">
          {headerPrefix}
        </div>
        <div className="tp-workspace-toolbar__right">
          <Space align="center" size={14} wrap>
            <Space size={6} align="center">
              <Typography.Text type="secondary" className="tp-toolbar-label">Commit</Typography.Text>
              <Typography.Text code data-testid="workspace-commit-sha" className="tp-commit-sha">
                {shortSha(project.commit_sha)}
              </Typography.Text>
            </Space>
            {section !== 'pages' ? (
              <Space size={6} align="center">
                <Typography.Text type="secondary" className="tp-toolbar-label">环境</Typography.Text>
                <Select
                  style={{ minWidth: 130 }}
                  value={selectedEnv ?? undefined}
                  options={envOptions}
                  placeholder={environmentQuery.isLoading ? '加载环境…' : '无可用环境'}
                  onChange={handleEnvChange}
                  loading={environmentQuery.isLoading}
                  disabled={envOptions.length === 0}
                  aria-label="运行环境"
                  data-testid="workspace-env-select"
                />
              </Space>
            ) : null}
            {isNarrow ? (
              <Button
                icon={<FolderOpenOutlined />}
                onClick={() => setAssetDrawerOpen(true)}
                aria-label="打开资产浏览"
              >
                资产
              </Button>
            ) : null}
          </Space>
        </div>
      </div>

      {alerts}

      {noEnabledEnv && section !== 'pages' ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          data-testid="workspace-no-env"
          message="还没有启用的环境"
          description="运行环境来自本项目已启用的数据库环境。请先配置环境后再运行。"
          action={
            <Link to={`${sectionPath('configuration', projectId)}?tab=environments`}>
              <Button size="small" data-testid="open-env-config">去配置</Button>
            </Link>
          }
        />
      ) : null}
      {environmentQuery.isError ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          message="环境列表加载失败"
          description={
            <Button
              size="small"
              onClick={() => {
                void environmentQuery.refetch()
              }}
            >
              重试
            </Button>
          }
        />
      ) : null}

      <div
        className="tp-workspace-columns"
        style={{
          display: 'flex',
          gap: 14,
          alignItems: 'flex-start',
          flexWrap: isNarrow ? 'wrap' : 'nowrap',
        }}
      >
        {!isNarrow ? (
          <aside
            data-testid="workspace-assets-aside"
            aria-label="资产浏览"
            className="tp-surface tp-workspace-aside"
            style={{
              flex: '0 0 280px',
              width: 280,
              maxWidth: 320,
              minWidth: 260,
              position: 'sticky',
              top: 8,
              alignSelf: 'flex-start',
              maxHeight: 'calc(100vh - 120px)',
              overflow: 'auto',
              padding: 0,
            }}
          >
            {browser}
          </aside>
        ) : null}

        {centerColumn}
      </div>

      <Drawer
        title={`${SECTIONS[section].label}资产`}
        placement="left"
        width={Math.min(360, typeof window !== 'undefined' ? window.innerWidth - 24 : 360)}
        open={isNarrow && assetDrawerOpen}
        onClose={() => setAssetDrawerOpen(false)}
        destroyOnClose={false}
      >
        {browser}
      </Drawer>
    </div>
  )
}
