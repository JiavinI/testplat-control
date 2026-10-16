import { Alert, Collapse, Space, Tabs, Tag, Typography } from 'antd'
import { ExecutionResultCard } from './ExecutionResultCard'
import { JsonBlock } from './JsonBlock'
import type { RunResponse } from './types'

function object(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : null
}

/** 单接口调试优先展示响应；身份、登录和完整运行记录按需展开。 */
export function ApiRunResult({ result, env }: { result: RunResponse; env: string }) {
  const payload = object(result.result)
  const response = object(payload?.response)
  const error = object(payload?.error)
  const duration = result.duration == null ? '—' : `${Math.round(result.duration * 1000)} ms`
  return (
    <div data-testid="api-run-response">
      <Space wrap style={{ marginBottom: 8 }}>
        <Tag color={result.status === 'success' ? 'success' : 'error'} data-testid="api-business-result">
          {result.status === 'success' ? '业务判定通过' : '执行未通过'} · {result.status}
        </Tag>
        <Typography.Text>HTTP {String(response?.status_code ?? '—')}</Typography.Text>
        <Typography.Text>耗时 {duration}</Typography.Text>
        <Typography.Text type="secondary">环境 {env}</Typography.Text>
      </Space>
      {payload?.error ? <Alert type="error" showIcon message={error?.kind === 'login_failed' ? '登录失败' : '执行失败'}
        description={typeof error?.message === 'string' ? error.message : typeof payload.error === 'string' ? payload.error : '查看运行详情获取失败原因'} /> : null}
      <Tabs defaultActiveKey="body" items={[
        { key: 'body', label: '响应体', children: <JsonBlock value={response?.body} emptyText="尚无响应体" maxHeight={480} aria-label="响应内容" /> },
        { key: 'headers', label: '响应头', children: <JsonBlock value={response?.headers} aria-label="响应头" /> },
        { key: 'request', label: '实际请求', children: <JsonBlock value={payload?.request} aria-label="实际请求快照" /> },
      ]} />
      <Collapse size="small" items={[{
        key: 'details', label: '运行详情与登录过程',
        children: <ExecutionResultCard result={result} env={env} />,
      }]} />
    </div>
  )
}
