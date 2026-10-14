import { Alert, Collapse, Descriptions, Space, Tag, Typography } from 'antd'
import { useMemo, useState } from 'react'
import { stepAuthDisplayMode } from './auth'
import { AuthSummary } from './AuthSummary'
import { findFirstFailedStepIndex } from './caseParse'
import { JsonBlock } from './JsonBlock'
import { LoginFailedBanner } from './LoginFailedBanner'
import { LoginProcessPanel } from './LoginProcessPanel'
import { isCacheReuseWithoutLogin } from './loginDisplay'
import {
  caseHasLoginFailed,
  isLoginFailedStep,
  skipReasonLabel,
} from './loginDisplay'
import { RequestSnapshot } from './RequestSnapshot'
import {
  formatDurationSeconds,
  runStatusColor,
  runStatusLabel,
  stepStatusColor,
  stepStatusLabel,
} from './statusLabel'
import type { CaseResult, CaseStepResult } from './types'

export type CaseResultViewProps = {
  result: CaseResult
  recordId?: string | null
  /** 系统错误定位历史时的补充说明 */
  locateNote?: string | null
}

function StepDetail({ step }: { step: CaseStepResult }) {
  const loginFailed = isLoginFailedStep(step)
  const skipLabel = skipReasonLabel(step.skip_reason)
  return (
    <div style={{ maxWidth: '100%', overflowX: 'hidden' }}>
      {step.skip_reason ? (
        <Typography.Paragraph
          type="secondary"
          style={{ marginBottom: 8 }}
          data-testid={`step-skip-reason-${step.step_id}`}
          className={
            step.skip_reason === 'login_failed' ? 'tp-skip-login-failed' : undefined
          }
        >
          跳过原因：{skipLabel || step.skip_reason}
        </Typography.Paragraph>
      ) : null}

      {/* 步骤身份：null 需区分“匿名”与“未发请求（—）”，判定见 auth.ts */}
      <div style={{ marginBottom: 8 }}>
        <Typography.Text type="secondary" style={{ marginRight: 8 }}>
          身份
        </Typography.Text>
        <AuthSummary
          auth={step.auth ?? null}
          mode={stepAuthDisplayMode(step)}
          testId={`step-auth-${step.step_id}`}
        />
      </div>

      {loginFailed && step.error ? (
        <LoginFailedBanner
          message={step.error.message}
          reason={step.error.login?.reason}
          failedStep={step.error.login?.failed_step}
          identity={
            typeof step.error.login?.identity === 'string'
              ? step.error.login.identity
              : step.auth?.identity
          }
          testId={`step-login-failed-${step.step_id}`}
        />
      ) : null}

      {step.error && !loginFailed ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          message={`${step.error.kind}${step.error.stage ? ` · ${step.error.stage}` : ''}`}
          description={step.error.message}
        />
      ) : null}

      {step.output ? (
        <Typography.Paragraph style={{ marginBottom: 8 }}>
          output alias：
          <Typography.Text code>{step.output}</Typography.Text>
        </Typography.Paragraph>
      ) : null}

      {step.status !== 'skipped' ? (
        <>
          <Typography.Text strong>Request</Typography.Text>
          <RequestSnapshot
            request={step.request}
            ariaLabel={`${step.step_id} request`}
          />
          <Typography.Text strong style={{ display: 'block', marginTop: 12 }}>
            Response
          </Typography.Text>
          <JsonBlock value={step.response} aria-label={`${step.step_id} response`} />
        </>
      ) : null}
    </div>
  )
}

/**
 * Case 汇总 + 可展开步骤。默认突出首个失败步骤；
 * login_failed 时使用独立色板，并默认展开登录过程面板。
 */
export function CaseResultView({ result, recordId, locateNote }: CaseResultViewProps) {
  const firstFailed = useMemo(
    () => findFirstFailedStepIndex(result.steps),
    [result.steps],
  )
  const hasLoginFailed = useMemo(() => caseHasLoginFailed(result), [result])
  const firstLoginFailed = useMemo(
    () => result.steps.find((step) => isLoginFailedStep(step)) ?? null,
    [result.steps],
  )
  const [activeKeys, setActiveKeys] = useState<string[]>(() =>
    firstFailed >= 0 ? [String(firstFailed)] : [],
  )

  return (
    <div
      data-testid="case-result-view"
      data-login-failed={hasLoginFailed ? 'true' : 'false'}
      style={{ maxWidth: '100%', overflowX: 'hidden' }}
    >
      {locateNote ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="已从历史定位系统错误记录"
          description={locateNote}
        />
      ) : null}

      {hasLoginFailed && firstLoginFailed?.error ? (
        <div style={{ marginBottom: 12 }}>
          <LoginFailedBanner
            message={firstLoginFailed.error.message}
            reason={firstLoginFailed.error.login?.reason}
            failedStep={firstLoginFailed.error.login?.failed_step}
            identity={
              typeof firstLoginFailed.error.login?.identity === 'string'
                ? firstLoginFailed.error.login.identity
                : firstLoginFailed.auth?.identity
            }
          />
        </div>
      ) : null}

      {result.error ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          message={`系统错误 · ${result.error.kind} · ${result.error.stage}`}
          description={result.error.message}
        />
      ) : null}

      <Descriptions size="small" column={1} style={{ marginBottom: 12 }}>
        <Descriptions.Item label="Case 状态">
          <Space wrap size={[8, 4]}>
            <Tag color={runStatusColor(result.status)}>
              {runStatusLabel(result.status)}（{result.status}）
            </Tag>
            {hasLoginFailed ? (
              <Tag className="tp-login-failed-tag" data-testid="case-login-failed-marker">
                登录失败
              </Tag>
            ) : null}
          </Space>
        </Descriptions.Item>
        <Descriptions.Item label="耗时">
          {formatDurationSeconds(result.duration_seconds)}
        </Descriptions.Item>
        <Descriptions.Item label="Case ID">
          <Typography.Text code copyable style={{ wordBreak: 'break-all' }}>
            {result.case_id}
          </Typography.Text>
        </Descriptions.Item>
        {recordId ? (
          <Descriptions.Item label="记录 ID">
            <Typography.Text code copyable style={{ wordBreak: 'break-all' }}>
              {recordId}
            </Typography.Text>
          </Descriptions.Item>
        ) : null}
        <Descriptions.Item label="汇总">
          <Space wrap size={[8, 4]}>
            <Tag>合计 {result.summary.total}</Tag>
            <Tag color="success">成功 {result.summary.success}</Tag>
            <Tag color="error">失败 {result.summary.failed}</Tag>
            <Tag color="warning">跳过 {result.summary.skipped}</Tag>
          </Space>
        </Descriptions.Item>
      </Descriptions>

      {result.logins.length > 0 ? (
        <div style={{ marginBottom: 16 }}>
          <LoginProcessPanel
            logins={result.logins}
            defaultExpanded={hasLoginFailed}
            highlightRef={firstLoginFailed?.auth?.login_ref ?? null}
          />
        </div>
      ) : result.steps.some((step) => isCacheReuseWithoutLogin(step.auth)) ? (
        <Typography.Text
          type="secondary"
          data-testid="login-cache-reuse-note"
          style={{ display: 'block', marginBottom: 16 }}
        >
          复用登录（未重新登录），本次无登录过程可查看
        </Typography.Text>
      ) : null}

      <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
        步骤
      </Typography.Text>
      <Collapse
        accordion={false}
        activeKey={activeKeys}
        onChange={(keys) => {
          setActiveKeys(Array.isArray(keys) ? keys.map(String) : [String(keys)])
        }}
        items={result.steps.map((step, index) => {
          const isFirstFailed = index === firstFailed
          const loginFailed = isLoginFailedStep(step)
          const skippedByLogin = step.skip_reason === 'login_failed'
          const title = step.name?.trim() ? step.name : step.step_id
          return {
            key: String(index),
            label: (
              <Space wrap size={[8, 4]} style={{ maxWidth: '100%' }}>
                <Typography.Text
                  code
                  style={{ wordBreak: 'break-all', maxWidth: '100%' }}
                >
                  {step.step_id}
                </Typography.Text>
                <Typography.Text style={{ wordBreak: 'break-word' }}>
                  {title}
                </Typography.Text>
                <Tag color={stepStatusColor(step.status)}>
                  {stepStatusLabel(step.status)}（{step.status}）
                </Tag>
                <Typography.Text type="secondary">
                  {formatDurationSeconds(step.duration_seconds)}
                </Typography.Text>
                {loginFailed ? (
                  <Tag
                    className="tp-login-failed-tag"
                    data-testid={`step-login-failed-marker-${step.step_id}`}
                  >
                    登录失败
                  </Tag>
                ) : null}
                {skippedByLogin ? (
                  <Tag
                    className="tp-skip-login-failed-tag"
                    data-testid={`step-skipped-login-failed-${step.step_id}`}
                  >
                    因登录失败跳过
                  </Tag>
                ) : null}
                {isFirstFailed ? (
                  <Tag color="magenta" data-testid="first-failed-marker">
                    首个失败
                  </Tag>
                ) : null}
              </Space>
            ),
            className: [
              isFirstFailed ? 'tp-case-step-first-failed' : '',
              loginFailed ? 'tp-case-step-login-failed' : '',
              skippedByLogin ? 'tp-case-step-skipped-login-failed' : '',
            ]
              .filter(Boolean)
              .join(' ') || undefined,
            children: <StepDetail step={step} />,
          }
        })}
      />
    </div>
  )
}
