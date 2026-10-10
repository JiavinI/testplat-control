import { Button, Card, Grid, Pagination, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { DeleteOutlined, EditOutlined, FolderOpenOutlined } from '@ant-design/icons'
import { useEffect, useState } from 'react'
import type { ProjectResponse } from '@/shared/types/project'

const PAGE_SIZE = 20

interface ProjectListTableProps {
  data: ProjectResponse[]
  loading?: boolean
  deletingId?: string | null
  onOpen: (project: ProjectResponse) => void
  onEdit: (project: ProjectResponse) => void
  onDelete: (project: ProjectResponse) => void
}

interface ProjectActionsProps extends Pick<
  ProjectListTableProps,
  'deletingId' | 'onOpen' | 'onEdit' | 'onDelete'
> {
  project: ProjectResponse
  wrap?: boolean
}

function formatUpdatedAt(value: string): string {
  // 后端返回 ISO 字符串；展示时尽量本地可读，解析失败则回退原文
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString('zh-CN', { hour12: false })
}

function ProjectActions({
  project,
  deletingId,
  onOpen,
  onEdit,
  onDelete,
  wrap = false,
}: ProjectActionsProps) {
  return (
    <Space wrap={wrap} size={wrap ? 6 : 4}>
      <Button
        size="small"
        icon={<FolderOpenOutlined />}
        onClick={() => onOpen(project)}
        aria-label={`打开工作台 ${project.name}`}
      >
        工作台
      </Button>
      <Button
        size="small"
        icon={<EditOutlined />}
        onClick={() => onEdit(project)}
        aria-label={`编辑项目 ${project.name}`}
      >
        编辑
      </Button>
      <Button
        size="small"
        danger
        icon={<DeleteOutlined />}
        loading={deletingId === project.id}
        aria-label={`删除项目 ${project.name}`}
        onClick={() => onDelete(project)}
      >
        删除
      </Button>
    </Space>
  )
}

export function ProjectListTable({
  data,
  loading,
  deletingId,
  onOpen,
  onEdit,
  onDelete,
}: ProjectListTableProps) {
  const screens = Grid.useBreakpoint()
  const [mobilePage, setMobilePage] = useState(1)

  useEffect(() => {
    const lastPage = Math.max(1, Math.ceil(data.length / PAGE_SIZE))
    setMobilePage((page) => Math.min(page, lastPage))
  }, [data.length])

  const columns: ColumnsType<ProjectResponse> = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      ellipsis: true,
      render: (name: string, record) => (
        <Button
          type="link"
          style={{ paddingInline: 0 }}
          onClick={() => onOpen(record)}
          aria-label={`打开项目 ${name}`}
        >
          {name}
        </Button>
      ),
    },
    {
      title: '环境',
      dataIndex: 'env',
      key: 'env',
      width: 100,
      render: (env: string) => <Typography.Text code>{env}</Typography.Text>,
    },
    {
      title: '资产目录',
      dataIndex: 'assets_root',
      key: 'assets_root',
      ellipsis: true,
      render: (path: string) => (
        <Typography.Text type="secondary" style={{ fontFamily: 'ui-monospace, monospace' }}>
          {path}
        </Typography.Text>
      ),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 180,
      render: (value: string) => formatUpdatedAt(value),
    },
    {
      title: '操作',
      key: 'actions',
      width: 220,
      render: (_: unknown, record) => (
        <ProjectActions
          project={record}
          deletingId={deletingId}
          onOpen={onOpen}
          onEdit={onEdit}
          onDelete={onDelete}
        />
      ),
    },
  ]

  if (!screens.md) {
    const start = (mobilePage - 1) * PAGE_SIZE
    const visibleProjects = data.slice(start, start + PAGE_SIZE)
    return (
      <div aria-label="项目列表" data-testid="project-list-mobile">
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          {visibleProjects.map((project) => (
            <Card
              key={project.id}
              size="small"
              data-testid="project-row"
              aria-label={`项目 ${project.name}`}
            >
              <Space direction="vertical" size={10} style={{ width: '100%' }}>
                <Space style={{ width: '100%', justifyContent: 'space-between' }} align="start">
                  <Button
                    type="link"
                    style={{ paddingInline: 0, fontWeight: 600, textAlign: 'left' }}
                    onClick={() => onOpen(project)}
                    aria-label={`打开项目 ${project.name}`}
                  >
                    {project.name}
                  </Button>
                  <Tag>{project.env}</Tag>
                </Space>
                <div>
                  <Typography.Text type="secondary">资产目录</Typography.Text>
                  <Typography.Text
                    code
                    style={{ display: 'block', overflowWrap: 'anywhere', whiteSpace: 'normal' }}
                  >
                    {project.assets_root}
                  </Typography.Text>
                </div>
                <Typography.Text type="secondary">
                  更新时间：{formatUpdatedAt(project.updated_at)}
                </Typography.Text>
                <ProjectActions
                  project={project}
                  deletingId={deletingId}
                  onOpen={onOpen}
                  onEdit={onEdit}
                  onDelete={onDelete}
                  wrap
                />
              </Space>
            </Card>
          ))}
        </Space>
        <Pagination
          current={mobilePage}
          pageSize={PAGE_SIZE}
          total={data.length}
          hideOnSinglePage
          showSizeChanger={false}
          size="small"
          style={{ marginTop: 16, justifyContent: 'center' }}
          onChange={setMobilePage}
          aria-label="项目列表分页"
        />
      </div>
    )
  }

  return (
    <Table
      rowKey="id"
      size="middle"
      columns={columns}
      dataSource={data}
      loading={loading}
      pagination={{ pageSize: PAGE_SIZE, hideOnSinglePage: true }}
      locale={{ emptyText: '暂无项目' }}
      onRow={(project) => ({
        'data-testid': 'project-row',
        'aria-label': `项目 ${project.name}`,
      })}
    />
  )
}
