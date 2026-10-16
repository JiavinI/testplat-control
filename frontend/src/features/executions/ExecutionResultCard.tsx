import { Alert, Descriptions, Space, Tag, Typography } from 'antd'
import { apiAuthDisplayMode } from './auth'
import { AuthSummary } from './AuthSummary'
import { JsonBlock } from './JsonBlock'
import { LoginFailedBanner } from './LoginFailedBanner'
import { LoginProcessPanel } from './LoginProcessPanel'
import { isCacheReuseWithoutLogin } from './loginDisplay'
import {
  apiResultHasLoginFailed,
  extractLoginsFromResult,
} from './loginDisplay'
import { RequestSnapshot } from './RequestSnapshot'
import { shortSha } from '@/shared/project/display'
import type { CaseStepRequest, RunResponse } from './types'

interface ExecutionResultCardProps {
  result: RunResponse
  /** 本次运行所选环境。响应体本身不带回 env。 */
  env?: string | null
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

function asRequestSnapshot(value: unknown): CaseStepRequest | null {
  if (value === null || value === undefined) {
    return null
  }
  if (typeof value !== 'object' || Array.isArray(value)) {
    return null
  }
  const obj = value as Record<string, unknown>
  if (typeof obj.method !== 'string' || typeof obj.url !== 'string') {
    // 单 API 快照可能是 {api_id, params, body_type, headers}，无 method/url
    return {
      method: typeof obj.method === 'string' ? obj.method : '—',
      url: typeof obj.url === 'string' ? obj.url : typeof obj.api_id === 'string' ? String(obj.api_id) : '—',
      headers:
        obj.headers && typeof obj.headers === 'object' && !Array.isArray(obj.headers)
          ? (obj.headers as Record<string, unknown>)
          : undefined,
      body: 'body' in obj ? obj.body : 'params' in obj ? obj.params : undefined,
      body_type: typeof obj.body_type === 'string' ? obj.body_type : 'json',
      query:
        obj.query && typeof obj.query === 'object' && !Array.isArray(obj.query)
          ? (obj.query as Record<string, unknown>)
          : null,
    }
  }
  return {
    method: obj.method,
    url: obj.url,
    headers:
      obj.headers && typeof obj.headers === 'object' && !Array.isArray(obj.headers)
        ? (obj.headers as Record<string, unknown>)
        : undefined,
    body: obj.body,
    body_type: typeof obj.body_type === 'string' ? obj.body_type : 'json',
    query:
      obj.query && typeof obj.query === 'object' && !Array.isArray(obj.query)
        ? (obj.query as Record<string, unknown>)
        : null,
  }
}

export function ExecutionResultCard({ result, env }: ExecutionResultCardProps) {
  const payload =
    result.result && typeof result.result === 'object'
      ? (result.result as Record<string, unknown>)
      : null
  const errorValue = payload?.error
  const requestValue = payload?.request
  const responseValue = payload?.response
  const logins = extractLoginsFromResult(result.result)
  const loginFailed = apiResultHasLoginFailed(result.result)
  const errorObj =
    errorValue && typeof errorValue === 'object' && !Array.isArray(errorValue)
      ? (errorValue as Record<string, unknown>)
      : null
  const loginMeta =
    errorObj?.login && typeof errorObj.login === 'object' && !Array.isArray(errorObj.login)
      ? (errorObj.login as Record<string, unknown>)
      : null

  return (
    <div
      data-testid="execution-result"
      data-login-failed={loginFailed ? 'true' : 'false'}
    >
      <Descriptions size="small" column={2} style={{ marginBottom: 12 }}>
        <Descriptions.Item label="状态">
          <Space wrap size={[8, 4]}>
            <Tag color={result.status === 'success' ? 'success' : 'error'}>
              {result.status}
            </Tag>
            {loginFailed ? (
              <Tag className="tp-login-failed-tag" data-testid="api-login-failed-marker">
                登录失败
              </Tag>
            ) : null}
          </Space>
        </Descriptions.Item>
        <Descriptions.Item label="耗时">
          {formatDurationSeconds(result.duration)}
        </Descriptions.Item>
        <Descriptions.Item label="操作人">
          <span data-testid="run-result-operator">{result.operator || '—'}</span>
        </Descriptions.Item>
        <Descriptions.Item label="环境">
          <Typography.Text code data-testid="run-result-env">
            {env || '—'}
          </Typography.Text>
        </Descriptions.Item>
        <Descriptions.Item label="Commit">
          <Typography.Text code data-testid="run-result-commit-sha">
            {shortSha(result.commit_sha)}
          </Typography.Text>
        </Descriptions.Item>
        {typeof result.config_revision === 'number' ? (
          <Descriptions.Item label="配置版本">
            <span data-testid="run-result-config-revision">{result.config_revision}</span>
          </Descriptions.Item>
        ) : null}
        {/* 单 API：auth 为 null 只表示匿名执行 */}
        <Descriptions.Item label="身份" span={2}>
          <AuthSummary
            auth={result.auth ?? null}
            mode={apiAuthDisplayMode(result.auth ?? null)}
          />
        </Descriptions.Item>
        <Descriptions.Item label="记录 ID" span={2}>
          <Typography.Text copyable code>
            {result.record_id}
          </Typography.Text>
        </Descriptions.Item>
      </Descriptions>

      {loginFailed && errorObj && typeof errorObj.message === 'string' ? (
        <div style={{ marginBottom: 12 }}>
          <LoginFailedBanner
            message={errorObj.message}
            reason={typeof loginMeta?.reason === 'string' ? loginMeta.reason : null}
            failedStep={
              typeof loginMeta?.failed_step === 'string' ? loginMeta.failed_step : null
            }
            identity={
              typeof loginMeta?.identity === 'string'
                ? loginMeta.identity
                : result.auth?.identity
            }
          />
        </div>
      ) : null}

      {!loginFailed && errorValue != null && errorValue !== '' ? (
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

      {logins.length > 0 ? (
        <div style={{ marginBottom: 16 }}>
          <LoginProcessPanel
            logins={logins}
            defaultExpanded={loginFailed}
            highlightRef={result.auth?.login_ref ?? null}
          />
        </div>
      ) : isCacheReuseWithoutLogin(result.auth) ? (
        <Typography.Text
          type="secondary"
          data-testid="login-cache-reuse-note"
          style={{ display: 'block', marginBottom: 16 }}
        >
          复用登录（未重新登录），本次无登录过程可查看
        </Typography.Text>
      ) : null}

      <Typography.Text strong>Request</Typography.Text>
      {asRequestSnapshot(requestValue) ? (
        <RequestSnapshot
          request={asRequestSnapshot(requestValue)}
          ariaLabel="执行 request"
        />
      ) : (
        <JsonBlock value={requestValue ?? null} aria-label="执行 request" />
      )}

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
