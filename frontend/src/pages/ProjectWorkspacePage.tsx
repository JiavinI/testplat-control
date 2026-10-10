import { Button, Card, Descriptions, Divider, Space, Typography } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { Link, useParams } from 'react-router-dom'
import { useProject } from '@/features/projects/hooks'
import { ErrorState, LoadingState } from '@/shared/ui/AsyncState'

/**
 * 项目工作台占位骨架。
 * 资产区 / 执行区仅提供空集成容器，具体能力由后续 Phase 实现。
 */
export function ProjectWorkspacePage() {
  const { projectId = '' } = useParams()
  const projectQuery = useProject(projectId)

  if (projectQuery.isLoading) {
    return <LoadingState tip="加载项目…" />
  }

  if (projectQuery.isError) {
    return (
      <div>
        <Space style={{ marginBottom: 16 }}>
          <Link to="/projects">
            <Button icon={<ArrowLeftOutlined />}>返回项目列表</Button>
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

  return (
    <div>
      <Space
        style={{ width: '100%', justifyContent: 'space-between', marginBottom: 12 }}
        align="start"
      >
        <div>
          <Space align="center" style={{ marginBottom: 4 }}>
            <Link to="/projects">
              <Button icon={<ArrowLeftOutlined />} aria-label="返回项目列表">
                返回
              </Button>
            </Link>
            <Typography.Title level={4} style={{ margin: 0 }}>
              {project.name}
            </Typography.Title>
            <Typography.Text code>{project.env}</Typography.Text>
          </Space>
          <Typography.Text type="secondary">项目工作台</Typography.Text>
        </div>
      </Space>

      <Card size="small" title="项目摘要" style={{ marginBottom: 16 }}>
        <Descriptions size="small" column={2}>
          <Descriptions.Item label="项目 ID">
            <Typography.Text copyable={{ text: project.id }} code>
              {project.id}
            </Typography.Text>
          </Descriptions.Item>
          <Descriptions.Item label="环境">{project.env}</Descriptions.Item>
          <Descriptions.Item label="资产目录" span={2}>
            <Typography.Text code>{project.assets_root}</Typography.Text>
          </Descriptions.Item>
          <Descriptions.Item label="配置目录" span={2}>
            <Typography.Text code>{project.config_root}</Typography.Text>
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">{project.created_at}</Descriptions.Item>
          <Descriptions.Item label="更新时间">{project.updated_at}</Descriptions.Item>
        </Descriptions>
      </Card>

      <Divider style={{ margin: '12px 0 16px' }} />

      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {/* 后续 Agent 在此挂载 features/assets */}
        <Card
          size="small"
          title="资产区"
          extra={<Typography.Text type="secondary">待集成</Typography.Text>}
        >
          <div
            data-testid="assets-slot"
            role="region"
            aria-label="资产区集成容器"
            style={{
              minHeight: 120,
              border: '1px dashed #d9d9d9',
              borderRadius: 4,
              padding: 16,
              color: 'rgba(0,0,0,0.45)',
            }}
          >
            资产树与资产详情将在此集成。当前无假数据。
          </div>
        </Card>

        {/* 后续 Agent 在此挂载 features/executions */}
        <Card
          size="small"
          title="执行区"
          extra={<Typography.Text type="secondary">待集成</Typography.Text>}
        >
          <div
            data-testid="executions-slot"
            role="region"
            aria-label="执行区集成容器"
            style={{
              minHeight: 120,
              border: '1px dashed #d9d9d9',
              borderRadius: 4,
              padding: 16,
              color: 'rgba(0,0,0,0.45)',
            }}
          >
            执行触发与历史记录将在此集成。当前无假数据。
          </div>
        </Card>
      </Space>
    </div>
  )
}
