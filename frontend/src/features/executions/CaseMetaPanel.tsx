import { Descriptions, Empty, Tag, Typography } from 'antd'
import { ApiHttpError } from '@/shared/api/errors'
import { ErrorState, LoadingState } from '@/shared/ui/AsyncState'
import type { CaseAssetDetail } from './types'

export type CaseMetaPanelProps = {
  caseId: string
  detail: CaseAssetDetail | undefined
  loading: boolean
  error: unknown
  onRetry: () => void
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

function formatModifiedAt(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString('zh-CN', { hour12: false })
}

/**
 * Case 运行前只展示文件元信息；不渲染 YAML，不推导 tags/步骤。
 */
export function CaseMetaPanel({
  caseId,
  detail,
  loading,
  error,
  onRetry,
}: CaseMetaPanelProps) {
  if (loading && !detail) {
    return <LoadingState tip="加载 Case 元信息…" />
  }

  if (error) {
    const is404 = error instanceof ApiHttpError && error.status === 404
    return (
      <ErrorState
        title={is404 ? 'Case 不存在' : '加载 Case 详情失败'}
        error={error}
        onRetry={onRetry}
      />
    )
  }

  if (!detail) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="无法加载 Case 元信息"
      />
    )
  }

  return (
    <div data-testid="case-meta-panel">
      <Typography.Title level={5} style={{ marginTop: 0, marginBottom: 8 }}>
        {detail.file_name}
      </Typography.Title>
      <div style={{ marginBottom: 12 }}>
        <Tag>Case 文件</Tag>
        <Tag color="blue">可运行</Tag>
      </div>

      <Descriptions size="small" column={1} bordered>
        <Descriptions.Item label="case_id">
          <Typography.Text copyable code style={{ wordBreak: 'break-all' }}>
            {detail.case_id}
          </Typography.Text>
        </Descriptions.Item>
        <Descriptions.Item label="路径">
          <Typography.Text code style={{ wordBreak: 'break-all' }}>
            {detail.path}
          </Typography.Text>
        </Descriptions.Item>
        <Descriptions.Item label="文件名">
          <Typography.Text style={{ wordBreak: 'break-all' }}>
            {detail.file_name}
          </Typography.Text>
        </Descriptions.Item>
        <Descriptions.Item label="大小">
          {formatBytes(detail.size_bytes)}（{detail.size_bytes} 字节）
        </Descriptions.Item>
        <Descriptions.Item label="修改时间">
          {formatModifiedAt(detail.modified_at)}
        </Descriptions.Item>
      </Descriptions>

      <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
        运行前不预览 YAML、tags 或步骤；步骤信息来自运行结果与历史详情。
        {caseId !== detail.case_id ? (
          <>
            {' '}
            树节点 ID（
            <Typography.Text code>{caseId}</Typography.Text>
            ）与详情 case_id 不一致时以详情为准。
          </>
        ) : null}
      </Typography.Paragraph>
    </div>
  )
}
