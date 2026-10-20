import { Collapse, Descriptions, Empty, Typography } from 'antd'
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
 * 场景执行页只保留轻量标题；文件元信息按需查看。
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
    <div data-testid="case-meta-panel" className="tp-case-meta-compact">
      <Typography.Text type="secondary">{detail.definition?.name ?? detail.file_name}</Typography.Text>
      <Collapse size="small" ghost items={[{ key: 'metadata', label: '资产信息', children: <Descriptions size="small" column={{ xs: 1, sm: 2 }}>
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
      </Descriptions> }]} />
      {!detail.definition ? <Typography.Text type="secondary">当前 Engine 未提供场景步骤描述。</Typography.Text> : null}
      {caseId !== detail.case_id ? <Typography.Text type="secondary">
        树节点 ID（<Typography.Text code>{caseId}</Typography.Text>）与详情 ID 不一致。
      </Typography.Text> : null}
    </div>
  )
}
