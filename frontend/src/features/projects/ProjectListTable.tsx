import { Button, Space, Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { DeleteOutlined, EditOutlined, FolderOpenOutlined } from '@ant-design/icons'
import type { ProjectResponse } from '@/shared/types/project'

interface ProjectListTableProps {
  data: ProjectResponse[]
  loading?: boolean
  deletingId?: string | null
  onOpen: (project: ProjectResponse) => void
  onEdit: (project: ProjectResponse) => void
  onDelete: (project: ProjectResponse) => void
}

function formatUpdatedAt(value: string): string {
  // 后端返回 ISO 字符串；展示时尽量本地可读，解析失败则回退原文
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString('zh-CN', { hour12: false })
}

export function ProjectListTable({
  data,
  loading,
  deletingId,
  onOpen,
  onEdit,
  onDelete,
}: ProjectListTableProps) {
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
        <Space size={4}>
          <Button
            size="small"
            icon={<FolderOpenOutlined />}
            onClick={() => onOpen(record)}
          >
            工作台
          </Button>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => onEdit(record)}
          >
            编辑
          </Button>
          <Button
            size="small"
            danger
            icon={<DeleteOutlined />}
            loading={deletingId === record.id}
            aria-label={`删除项目 ${record.name}`}
            onClick={() => onDelete(record)}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <Table
      rowKey="id"
      size="middle"
      columns={columns}
      dataSource={data}
      loading={loading}
      pagination={{ pageSize: 20, hideOnSinglePage: true }}
      locale={{ emptyText: '暂无项目' }}
    />
  )
}
