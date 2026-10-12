import { Alert, Collapse, Descriptions, Space, Tag, Typography } from 'antd'
import { useMemo, useState } from 'react'
import { stepAuthDisplayMode } from './auth'
import { AuthSummary } from './AuthSummary'
import { findFirstFailedStepIndex } from './caseParse'
import { JsonBlock } from './JsonBlock'
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
  return (
    <div style={{ maxWidth: '100%', overflowX: 'hidden' }}>
      {step.skip_reason ? (
        <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
          跳过原因：{step.skip_reason === 'fail_fast' ? '前序失败（fail_fast）' : step.skip_reason}
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

      {step.error ? (
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
          <JsonBlock value={step.request} aria-label={`${step.step_id} request`} />
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
 * Case 汇总 + 可展开步骤。默认突出首个失败步骤；JSON 按步展开，避免一次铺开。
 */
export function CaseResultView({ result, recordId, locateNote }: CaseResultViewProps) {
  const firstFailed = useMemo(
    () => findFirstFailedStepIndex(result.steps),
    [result.steps],
  )
  const [activeKeys, setActiveKeys] = useState<string[]>(() =>
    firstFailed >= 0 ? [String(firstFailed)] : [],
  )

  return (
    <div data-testid="case-result-view" style={{ maxWidth: '100%', overflowX: 'hidden' }}>
      {locateNote ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="已从历史定位系统错误记录"
          description={locateNote}
        />
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
          <Tag color={runStatusColor(result.status)}>
            {runStatusLabel(result.status)}（{result.status}）
          </Tag>
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
                {isFirstFailed ? (
                  <Tag color="magenta" data-testid="first-failed-marker">
                    首个失败
                  </Tag>
                ) : null}
              </Space>
            ),
            className: isFirstFailed ? 'tp-case-step-first-failed' : undefined,
            children: <StepDetail step={step} />,
          }
        })}
      />
    </div>
  )
}
