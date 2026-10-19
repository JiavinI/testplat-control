import { useEffect } from 'react'
import { Alert, Button, Select, Space, Typography } from 'antd'
import { Link, Navigate, useLocation, useNavigate, useParams } from 'react-router-dom'
import { useProjectList } from '@/features/projects/hooks'
import { EmptyState, ErrorState, LoadingState } from '@/shared/ui/AsyncState'
import {
  readPreferredProject,
  sectionPath,
  writePreferredProject,
  type WorkspaceSection,
} from '@/shared/project/sections'
import { ProjectWorkspacePage } from './ProjectWorkspacePage'
import { ProjectConfigurationPage } from './ProjectConfigurationPage'

/** 功能菜单内按平台、业务项目选择；URL 保留已有运行上下文 ID。 */
export function FeatureWorkspacePage({ section }: { section: WorkspaceSection }) {
  const { repo, project } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const projects = useProjectList()
  const projectId = repo && project ? `${repo}/${project}` : undefined
  const selected = projects.data?.find((item) => item.id === projectId)

  useEffect(() => {
    if (selected) writePreferredProject(selected.id)
  }, [selected])

  if (projects.isLoading) return <LoadingState tip="加载项目…" />
  if (projects.isError) return <ErrorState error={projects.error} onRetry={() => { void projects.refetch() }} />

  const available = projects.data ?? []
  if (!projectId && available.length) {
    const preferred = readPreferredProject()
    const initial = available.find((item) => item.id === preferred)
      ?? available.find((item) => !item.archived) ?? available[0]
    return <Navigate to={sectionPath(section, initial.id)} replace />
  }

  const platformKey = (item: typeof available[number]) => item.workspace ? `${item.repo}/${item.workspace.platform}` : '_legacy'
  const platforms = Array.from(new Map(available.map((item) => [platformKey(item), {
    value: platformKey(item), label: item.workspace?.platform_name ?? '未分平台',
  }])).values())
  const activePlatform = selected ? platformKey(selected) : undefined
  const platformProjects = available.filter((item) => platformKey(item) === activePlatform)
  const goTo = (id: string) => {
    writePreferredProject(id)
    navigate(`${sectionPath(section, id)}${section === 'configuration' ? location.search : ''}`)
  }
  const workspace = selected?.workspace
  const contextLabel = workspace
    ? workspace.platform === 'gsb' ? `${workspace.project_name} 的 GSB` : `${workspace.platform_name} · ${workspace.project_name}`
    : undefined
  const shared = workspace ? available.filter((item) => item.workspace?.configuration_project_id === workspace.configuration_project_id && item.id !== selected?.id) : []

  const contextSwitchers = (
    <Space size={10} wrap align="center">
      <Space size={6} align="center">
        <Typography.Text type="secondary" className="tp-toolbar-label">平台</Typography.Text>
        <Select
          aria-label="选择平台"
          data-testid="feature-platform-select"
          style={{ width: 170, maxWidth: '100%' }}
          value={activePlatform}
          options={platforms}
          placeholder="选择平台"
          onChange={(key: string) => {
            const candidates = available.filter((item) => platformKey(item) === key)
            const next = candidates.find((item) => item.workspace?.project === workspace?.project && !item.archived)
              ?? candidates.find((item) => !item.archived) ?? candidates[0]
            if (next) goTo(next.id)
          }}
        />
      </Space>
      <Space size={6} align="center">
        <Typography.Text type="secondary" className="tp-toolbar-label">项目</Typography.Text>
        <Select
          aria-label="选择项目"
          data-testid="feature-project-select"
          style={{ width: 240, maxWidth: '100%' }}
          showSearch
          optionFilterProp="label"
          value={selected?.id}
          placeholder="选择项目"
          options={platformProjects.map((item) => ({
            value: item.id,
            label: `${item.workspace?.project_name ?? `${item.name} · ${item.id}`}${item.archived ? '（已归档）' : ''}`,
          }))}
          onChange={goTo}
        />
      </Space>
      {contextLabel ? (
        <span className="tp-context-tag" data-testid="workspace-context-title">
          {contextLabel}
        </span>
      ) : null}
    </Space>
  )

  const alerts = (
    <>
      {workspace?.platform === 'daifa_admin' ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="代发后台入口与账号可维护；验证码／Redis 登录待适配，当前仅提供匿名入口检查。"
        />
      ) : null}
      {workspace && ['go2', 'e3e3'].includes(workspace.platform) ? (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="当前提供网站 SSO 匿名入口检查；网站浏览器登录尚未接入。账号与所属网站的 GSB 共用。"
        />
      ) : null}
      {section === 'configuration' && shared.length > 0 ? (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message={`环境和账号与「${shared.map((item) => item.name).join('、')}」共用，在任一入口修改都会同步生效。`}
        />
      ) : null}
    </>
  )

  if (available.length === 0) {
    return (
      <EmptyState
        description={
          <span>
            暂无项目，请到 <Link to="/configuration/repositories">配置 / 仓库同步</Link> 同步项目。
          </span>
        }
      />
    )
  }

  if (!selected) {
    return (
      <div className="tp-feature-workspace">
        <div className="tp-workspace-toolbar">
          <div className="tp-workspace-toolbar__left">{contextSwitchers}</div>
        </div>
        <EmptyState description="当前项目不存在，请从上方重新选择项目。" />
      </div>
    )
  }

  if (section === 'configuration') {
    return (
      <div className="tp-feature-workspace">
        <div className="tp-workspace-toolbar">
          <div className="tp-workspace-toolbar__left">{contextSwitchers}</div>
          <div className="tp-workspace-toolbar__right">
            <Link to="/configuration/repositories">
              <Button>仓库同步</Button>
            </Link>
          </div>
        </div>
        {alerts}
        <ProjectConfigurationPage key={projectId} project={selected} />
      </div>
    )
  }

  return (
    <div className="tp-feature-workspace">
      <ProjectWorkspacePage
        key={`${section}:${projectId}`}
        section={section}
        headerPrefix={contextSwitchers}
        alerts={alerts}
      />
    </div>
  )
}
