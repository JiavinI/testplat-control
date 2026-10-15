import { Button, Card, Grid, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { FolderOpenOutlined, SyncOutlined } from '@ant-design/icons'
import type { ProjectResponse, RepoResponse } from '@/shared/types/project'
import { shortSha, syncResultLabel } from '@/shared/project/display'

interface RepoGroup {
  repo: RepoResponse
  projects: ProjectResponse[]
}

interface ProjectListTableProps {
  groups: RepoGroup[]
  loading?: boolean
  syncingRepo: string | null
  onOpen: (project: ProjectResponse) => void
  onSync: (repoKey: string) => void
}

function formatTime(value: string | null | undefined): string {
  if (!value) {
    return '—'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString('zh-CN', { hour12: false })
}

export function ProjectListTable({
  groups,
  loading,
  syncingRepo,
  onOpen,
  onSync,
}: ProjectListTableProps) {
  const screens = Grid.useBreakpoint()

  if (groups.length === 0) {
    return null
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }} data-testid="project-list-grouped">
      {groups.map(({ repo, projects }) => {
        const syncing = syncingRepo === repo.key
        const resultText = syncResultLabel(repo.last_sync_result)
        const failed = Boolean(repo.last_sync_result && repo.last_sync_result !== 'ok')

        return (
          <Card
            key={repo.key}
            size="small"
            data-testid={`repo-group-${repo.key}`}
            title={
              <Space wrap>
                <Typography.Text strong>{repo.key}</Typography.Text>
                <Tag>{repo.branch}</Tag>
                <Typography.Text code data-testid={`repo-sha-${repo.key}`}>
                  {shortSha(repo.current_sha)}
                </Typography.Text>
              </Space>
            }
            extra={
              <Button
                size="small"
                icon={<SyncOutlined spin={syncing} />}
                loading={syncing}
                disabled={syncing}
                onClick={() => onSync(repo.key)}
                aria-label={`同步仓库 ${repo.key}`}
                data-testid={`sync-repo-${repo.key}`}
              >
                同步
              </Button>
            }
          >
            <Space wrap style={{ marginBottom: 12 }} size={[12, 4]}>
              <Typography.Text type="secondary">
                最近同步：{formatTime(repo.last_sync_at)}
              </Typography.Text>
              <Typography.Text
                type={failed ? 'danger' : 'secondary'}
                data-testid={`repo-sync-result-${repo.key}`}
              >
                结果：{resultText}
              </Typography.Text>
            </Space>

            {!screens.md ? (
              <Space direction="vertical" size={10} style={{ width: '100%' }}>
                {projects.map((project) => (
                  <Card
                    key={project.id}
                    size="small"
                    data-testid="project-row"
                    aria-label={`项目 ${project.name}`}
                    style={project.archived ? { opacity: 0.55 } : undefined} // 清单消失项目 archived 灰显，历史仍可查
                  >
                    <Space direction="vertical" size={8} style={{ width: '100%' }}>
                      <Space style={{ width: '100%', justifyContent: 'space-between' }} wrap>
                        <Button
                          type="link"
                          style={{
                            paddingInline: 0,
                            fontWeight: 600,
                            color: project.archived ? undefined : undefined,
                          }}
                          onClick={() => onOpen(project)}
                          aria-label={`打开项目 ${project.name}`}
                        >
                          {project.name}
                        </Button>
                        {project.archived ? <Tag>已归档</Tag> : null}
                      </Space>
                      <Typography.Text type="secondary" code>
                        {project.id}
                      </Typography.Text>
                      <Typography.Text type="secondary">
                        SHA {shortSha(project.commit_sha)}
                      </Typography.Text>
                      <Button
                        size="small"
                        icon={<FolderOpenOutlined />}
                        onClick={() => onOpen(project)}
                        aria-label={`打开工作台 ${project.name}`}
                      >
                        工作台
                      </Button>
                    </Space>
                  </Card>
                ))}
              </Space>
            ) : (
              <RepoProjectsTable
                projects={projects}
                loading={loading}
                onOpen={onOpen}
              />
            )}
          </Card>
        )
      })}
    </Space>
  )
}

function RepoProjectsTable({
  projects,
  loading,
  onOpen,
}: {
  projects: ProjectResponse[]
  loading?: boolean
  onOpen: (project: ProjectResponse) => void
}) {
  const columns: ColumnsType<ProjectResponse> = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      ellipsis: true,
      render: (name: string, record) => (
        <Space>
          <Button
            type="link"
            style={{
              paddingInline: 0,
              opacity: record.archived ? 0.65 : 1,
            }}
            onClick={() => onOpen(record)}
            aria-label={`打开项目 ${name}`}
          >
            {name}
          </Button>
          {record.archived ? <Tag>已归档</Tag> : null}
        </Space>
      ),
    },
    {
      title: '项目键',
      dataIndex: 'project',
      key: 'project',
      width: 140,
      render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
    },
    {
      title: '环境',
      dataIndex: 'envs',
      key: 'envs',
      width: 160,
      render: (envs: string[]) =>
        envs.length ? envs.map((e) => <Tag key={e}>{e}</Tag>) : '—',
    },
    {
      title: '短 SHA',
      dataIndex: 'commit_sha',
      key: 'commit_sha',
      width: 100,
      render: (sha: string | null) => (
        <Typography.Text code>{shortSha(sha)}</Typography.Text>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 100,
      render: (_: unknown, record) => (
        <Button
          size="small"
          icon={<FolderOpenOutlined />}
          onClick={() => onOpen(record)}
          aria-label={`打开工作台 ${record.name}`}
        >
          工作台
        </Button>
      ),
    },
  ]

  return (
    <Table
      rowKey="id"
      size="small"
      columns={columns}
      dataSource={projects}
      loading={loading}
      pagination={false}
      locale={{ emptyText: '该仓库暂无项目' }}
      onRow={(project) => ({
        'data-testid': 'project-row',
        'aria-label': `项目 ${project.name}`,
        style: project.archived ? { opacity: 0.55 } : undefined,
      })}
    />
  )
}
