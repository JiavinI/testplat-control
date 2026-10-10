import { App, Button, Space, Typography } from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ProjectFormModal } from '@/features/projects/ProjectFormModal'
import { ProjectListTable } from '@/features/projects/ProjectListTable'
import {
  useCreateProject,
  useDeleteProject,
  useProjectList,
  useUpdateProject,
} from '@/features/projects/hooks'
import type { ProjectCreate, ProjectResponse } from '@/shared/types/project'
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from '@/shared/ui/AsyncState'
import { formatErrorMessage } from '@/shared/ui/errorMessage'
import { ApiHttpError } from '@/shared/api/errors'

export function ProjectListPage() {
  const { message, modal } = App.useApp()
  const navigate = useNavigate()
  const listQuery = useProjectList()
  const createMutation = useCreateProject()
  const deleteMutation = useDeleteProject()

  const [createOpen, setCreateOpen] = useState(false)
  const [editing, setEditing] = useState<ProjectResponse | null>(null)

  // 编辑 mutation 依赖当前编辑项 id；无编辑项时用占位 id 且不会提交
  const updateMutation = useUpdateProject(editing?.id ?? '')

  const handleCreate = async (values: ProjectCreate) => {
    const created = await createMutation.mutateAsync(values)
    message.success('项目已创建')
    setCreateOpen(false)
    navigate(`/projects/${created.id}`)
  }

  const handleEdit = async (values: ProjectCreate) => {
    if (!editing) {
      return
    }
    try {
      await updateMutation.mutateAsync(values)
      message.success('项目已更新')
      setEditing(null)
      await listQuery.refetch()
    } catch (error) {
      if (error instanceof ApiHttpError) {
        throw error
      }
      message.error(formatErrorMessage(error))
      throw error
    }
  }

  const handleDelete = (project: ProjectResponse) => {
    modal.confirm({
      title: '确认删除该项目？',
      content: `将删除「${project.name}」，此操作不可撤销。`,
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      centered: true,
      onOk: async () => {
        try {
          await deleteMutation.mutateAsync(project.id)
          message.success(`已删除「${project.name}」`)
        } catch (error) {
          message.error(formatErrorMessage(error))
          throw error
        }
      },
    })
  }

  const renderBody = () => {
    if (listQuery.isLoading) {
      return <LoadingState tip="加载项目列表…" />
    }
    if (listQuery.isError) {
      return (
        <ErrorState
          error={listQuery.error}
          onRetry={() => {
            void listQuery.refetch()
          }}
        />
      )
    }
    const projects = listQuery.data ?? []
    if (projects.length === 0) {
      return (
        <EmptyState
          description="还没有项目。创建后可进入工作台管理资产与执行。"
          action={
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setCreateOpen(true)}
            >
              新建项目
            </Button>
          }
        />
      )
    }
    return (
      <ProjectListTable
        data={projects}
        loading={listQuery.isFetching && !listQuery.isLoading}
        deletingId={deleteMutation.isPending ? deleteMutation.variables ?? null : null}
        onOpen={(p) => navigate(`/projects/${p.id}`)}
        onEdit={setEditing}
        onDelete={handleDelete}
      />
    )
  }

  return (
    <div>
      <Space
        style={{ width: '100%', justifyContent: 'space-between', marginBottom: 16 }}
        align="center"
      >
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>
            项目列表
          </Typography.Title>
          <Typography.Text type="secondary">
            管理测试项目配置（名称、环境、资产目录、更新时间）。
          </Typography.Text>
        </div>
        <Space>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => {
              void listQuery.refetch()
            }}
            loading={listQuery.isFetching}
            aria-label="刷新项目列表"
          >
            刷新
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateOpen(true)}
          >
            新建项目
          </Button>
        </Space>
      </Space>

      {renderBody()}

      <ProjectFormModal
        open={createOpen}
        mode="create"
        submitting={createMutation.isPending}
        onCancel={() => setCreateOpen(false)}
        onSubmit={handleCreate}
      />

      <ProjectFormModal
        open={Boolean(editing)}
        mode="edit"
        initial={editing}
        submitting={updateMutation.isPending}
        onCancel={() => setEditing(null)}
        onSubmit={handleEdit}
      />
    </div>
  )
}
