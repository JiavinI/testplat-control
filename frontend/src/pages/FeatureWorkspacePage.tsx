import { useEffect } from 'react'
import { Alert, Button, Select, Space, Typography } from 'antd'
import { Link, Navigate, useLocation, useNavigate, useParams } from 'react-router-dom'
import { useProjectList } from '@/features/projects/hooks'
import { EmptyState, ErrorState, LoadingState } from '@/shared/ui/AsyncState'
import {
  readPreferredProject,
  SECTIONS,
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

  const heading = SECTIONS[section]
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

  return (
    <div>
      <div className="tp-feature-heading">
        <div>
          <Typography.Title level={3} className="tp-page-title" style={{ margin: '0 0 6px' }}>
            {heading.label}
          </Typography.Title>
          <Typography.Text type="secondary">{heading.description}</Typography.Text>
        </div>
        <Space wrap>
          <Typography.Text>平台</Typography.Text>
          <Select
            aria-label="选择平台"
            data-testid="feature-platform-select"
            style={{ width: 190, maxWidth: '100%' }}
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
          <Typography.Text>项目</Typography.Text>
          <Select
            aria-label="选择项目"
            data-testid="feature-project-select"
            style={{ width: 280, maxWidth: '100%' }}
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
          {section === 'configuration' ? <Link to="/configuration/repositories"><Button>仓库同步</Button></Link> : null}
        </Space>
      </div>
      {contextLabel ? <Typography.Title level={4} data-testid="workspace-context-title" style={{ marginTop: 0 }}>{contextLabel}</Typography.Title> : null}
      {workspace?.platform === 'daifa_admin' ? <Alert type="warning" showIcon style={{ marginBottom: 16 }} message="代发后台入口与账号可维护；验证码／Redis 登录待适配，当前仅提供匿名入口检查。" /> : null}
      {workspace && ['go2', 'e3e3'].includes(workspace.platform) ? <Alert type="info" showIcon style={{ marginBottom: 16 }} message="当前提供网站 SSO 匿名入口检查；网站浏览器登录尚未接入。账号与所属网站的 GSB 共用。" /> : null}
      {section === 'configuration' && shared.length > 0 ? (
        <Alert type="info" showIcon style={{ marginBottom: 16 }} message={`环境和账号与「${shared.map((item) => item.name).join('、')}」共用，在任一入口修改都会同步生效。`} />
      ) : null}
      {available.length === 0 ? (
        <EmptyState description={<span>暂无项目，请到 <Link to="/configuration/repositories">配置 / 仓库同步</Link> 同步项目。</span>} />
      ) : !selected ? (
        <EmptyState description="当前项目不存在，请从上方重新选择项目。" />
      ) : section === 'configuration' ? (
        <ProjectConfigurationPage key={projectId} project={selected} />
      ) : (
        <ProjectWorkspacePage key={`${section}:${projectId}`} section={section} />
      )}
    </div>
  )
}
