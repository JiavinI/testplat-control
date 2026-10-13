import { Space, Tag, Typography } from 'antd'
import { JsonBlock } from './JsonBlock'
import { bodyTypeLabel } from './loginDisplay'
import type { CaseStepRequest } from './types'

export type RequestSnapshotProps = {
  request: CaseStepRequest | null
  ariaLabel: string
}

/**
 * 结果视图中的请求快照：显式标出 body_type，query 类型参数单独展示（不进 url）。
 * 不提供录入能力——只读展示后端已脱敏快照。
 */
export function RequestSnapshot({ request, ariaLabel }: RequestSnapshotProps) {
  if (request === null) {
    return <JsonBlock value={null} aria-label={ariaLabel} />
  }
  const bodyType = bodyTypeLabel(request.body_type)
  return (
    <div data-testid="request-snapshot" className="tp-request-snapshot">
      <Space wrap size={[8, 4]} style={{ marginBottom: 8 }}>
        <Typography.Text type="secondary">请求体类型</Typography.Text>
        <Tag data-testid="request-body-type" className="tp-body-type-tag">
          {bodyType}
        </Tag>
        <Typography.Text code>
          {request.method} {request.url}
        </Typography.Text>
      </Space>
      {bodyType === 'query' || (request.query !== undefined && request.query !== null) ? (
        <div style={{ marginBottom: 8 }}>
          <Typography.Text strong>Query</Typography.Text>
          <JsonBlock value={request.query ?? null} aria-label={`${ariaLabel} query`} />
        </div>
      ) : null}
      <Typography.Text strong>完整快照</Typography.Text>
      <JsonBlock value={request} aria-label={ariaLabel} />
    </div>
  )
}
