import { Alert, Descriptions, Tag, Typography } from 'antd'
import { JsonBlock } from './JsonBlock'
import type { RunResponse } from './types'

interface ExecutionResultCardProps {
  result: RunResponse
}

function formatDurationSeconds(seconds: number | null): string {
  if (seconds === null || Number.isNaN(seconds)) {
    return '—'
  }
  if (seconds < 1) {
    return `${Math.round(seconds * 1000)}ms`
  }
  return `${seconds.toFixed(2)}s`
}

export function ExecutionResultCard({ result }: ExecutionResultCardProps) {
  const payload =
    result.result && typeof result.result === 'object'
      ? (result.result as Record<string, unknown>)
      : null
  const errorValue = payload?.error
  const requestValue = payload?.request
  const responseValue = payload?.response

  return (
    <div data-testid="execution-result">
      <Descriptions size="small" column={2} style={{ marginBottom: 12 }}>
        <Descriptions.Item label="状态">
          <Tag color={result.status === 'success' ? 'success' : 'error'}>
            {result.status}
          </Tag>
        </Descriptions.Item>
        <Descriptions.Item label="耗时">
          {formatDurationSeconds(result.duration)}
        </Descriptions.Item>
        <Descriptions.Item label="记录 ID" span={2}>
          <Typography.Text copyable code>
            {result.record_id}
          </Typography.Text>
        </Descriptions.Item>
      </Descriptions>

      {errorValue != null && errorValue !== '' ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          message="错误信息"
          description={
            typeof errorValue === 'string' ? errorValue : safePreview(errorValue)
          }
        />
      ) : null}

      <Typography.Text strong>Request</Typography.Text>
      <JsonBlock value={requestValue ?? null} aria-label="执行 request" />

      <Typography.Text strong style={{ display: 'block', marginTop: 12 }}>
        Response
      </Typography.Text>
      <JsonBlock value={responseValue ?? null} aria-label="执行 response" />

      <Typography.Text strong style={{ display: 'block', marginTop: 12 }}>
        原始 result
      </Typography.Text>
      <JsonBlock value={result.result} aria-label="原始 result" />
    </div>
  )
}

function safePreview(value: unknown): string {
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}
