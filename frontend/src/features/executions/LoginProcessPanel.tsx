import { Collapse, Space, Tag, Typography } from 'antd'
import { JsonBlock } from './JsonBlock'
import { RequestSnapshot } from './RequestSnapshot'
import {
  loginReasonLabel,
  loginTierLabel,
} from './loginDisplay'
import { formatDurationSeconds } from './statusLabel'
import type { LoginRecord } from './types'

export type LoginProcessPanelProps = {
  logins: LoginRecord[]
  /** 登录失败时默认展开（设计要求） */
  defaultExpanded?: boolean
  /** 高亮与某步骤 login_ref 对应的那次登录 */
  highlightRef?: number | null
  testId?: string
}

/**
 * 登录过程面板：按 logins 顺序展示身份、策略、档位、每步请求/响应（已脱敏）、probe、失败原因。
 * 同一身份多次登录靠下标与步骤 auth.login_ref 关联。
 */
export function LoginProcessPanel({
  logins,
  defaultExpanded = false,
  highlightRef = null,
  testId = 'login-process-panel',
}: LoginProcessPanelProps) {
  if (logins.length === 0) {
    return null
  }
  const defaultKeys =
    defaultExpanded || highlightRef !== null
      ? logins.map((_, i) => String(i))
      : []

  return (
    <div data-testid={testId} className="tp-login-process">
      <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
        登录过程
      </Typography.Text>
      <Collapse
        defaultActiveKey={defaultKeys}
        items={logins.map((login, index) => {
          const failed = login.status === 'failed'
          const highlighted = highlightRef === index
          const reason = login.error?.reason
          const reasonLabel = loginReasonLabel(
            typeof reason === 'string' ? reason : null,
          )
          return {
            key: String(index),
            className: [
              failed ? 'tp-login-process__failed' : '',
              highlighted ? 'tp-login-process__highlight' : '',
            ]
              .filter(Boolean)
              .join(' '),
            label: (
              <Space wrap size={[8, 4]} data-testid={`${testId}-item-${index}`}>
                <Tag data-testid={`${testId}-ref-${index}`}>#{index}</Tag>
                <Typography.Text>身份：{login.identity}</Typography.Text>
                <Tag>{login.strategy}</Tag>
                <Tag className="tp-auth-tier">档位：{loginTierLabel(login.tier)}</Tag>
                <Tag color={failed ? undefined : 'success'} className={failed ? 'tp-login-failed-tag' : undefined}>
                  {failed ? '失败' : '成功'}（{login.status}）
                </Tag>
                <Typography.Text type="secondary">
                  {formatDurationSeconds(login.duration_seconds)}
                </Typography.Text>
                {highlighted ? (
                  <Tag color="blue" data-testid={`${testId}-used-${index}`}>
                    本步骤使用
                  </Tag>
                ) : null}
              </Space>
            ),
            children: (
              <div className="tp-login-process__body">
                {failed && login.error ? (
                  <div className="tp-login-failed-banner tp-login-failed-banner--compact" data-testid={`${testId}-error-${index}`}>
                    <Typography.Text strong>登录失败</Typography.Text>
                    {reasonLabel ? (
                      <Tag className="tp-login-failed-tag">
                        {reasonLabel}
                        {typeof reason === 'string' ? `（${reason}）` : ''}
                      </Tag>
                    ) : null}
                    {login.error.failed_step ? (
                      <Typography.Text type="secondary">
                        失败步骤：{String(login.error.failed_step)}
                      </Typography.Text>
                    ) : null}
                  </div>
                ) : null}
                {login.steps.map((step, stepIndex) => (
                  <div key={`${step.name}-${stepIndex}`} style={{ marginBottom: 12 }}>
                    <Typography.Text strong>步骤：{step.name}</Typography.Text>
                    <div style={{ marginTop: 4 }}>
                      <Typography.Text type="secondary">Request</Typography.Text>
                      <RequestSnapshot
                        request={step.request}
                        ariaLabel={`login ${index} step ${step.name} request`}
                      />
                    </div>
                    <div style={{ marginTop: 8 }}>
                      <Typography.Text type="secondary">Response</Typography.Text>
                      <JsonBlock
                        value={step.response}
                        aria-label={`login ${index} step ${step.name} response`}
                      />
                    </div>
                  </div>
                ))}
                {login.probe ? (
                  <div style={{ marginTop: 8 }} data-testid={`${testId}-probe-${index}`}>
                    <Typography.Text strong>Probe：{login.probe.name}</Typography.Text>
                    <RequestSnapshot
                      request={login.probe.request}
                      ariaLabel={`login ${index} probe request`}
                    />
                    <JsonBlock
                      value={login.probe.response}
                      aria-label={`login ${index} probe response`}
                    />
                  </div>
                ) : null}
              </div>
            ),
          }
        })}
      />
    </div>
  )
}
