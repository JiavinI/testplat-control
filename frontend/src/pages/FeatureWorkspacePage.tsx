import { useEffect } from 'react'
import { Button, Select, Space, Typography } from 'antd'
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

/** 功能是入口，项目是每个功能的上下文；URL 可直接打开和刷新。 */
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
          <Typography.Text>项目</Typography.Text>
          <Select
            aria-label="选择项目"
            data-testid="feature-project-select"
            style={{ width: 280, maxWidth: '100%' }}
            showSearch
            optionFilterProp="label"
            value={selected?.id}
            placeholder="选择项目"
            options={available.map((item) => ({
              value: item.id,
              label: `${item.name} · ${item.id}${item.archived ? '（已归档）' : ''}`,
            }))}
            onChange={(id: string) => {
              writePreferredProject(id)
              navigate(`${sectionPath(section, id)}${section === 'configuration' ? location.search : ''}`)
            }}
          />
          {section === 'configuration' ? <Link to="/configuration/repositories"><Button>仓库同步</Button></Link> : null}
        </Space>
      </div>
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
