import { Alert, Button, Card, Descriptions, Divider, Input, Space, Typography } from 'antd'
import { PlayCircleOutlined } from '@ant-design/icons'
import { useState } from 'react'
import { ApiHttpError, ApiParseError } from '@/shared/api/errors'
import { formatRunFailure } from './accountFailure'
import { formatErrorMessage } from '@/shared/ui/errorMessage'
import { shortSha } from '@/shared/project/display'
import {
  getCaseExecutionRecord,
  listExecutionRecords,
} from './api'
import { CaseResultView } from './CaseResultView'
import { useRunCase } from './hooks'
import { ParameterPreview } from './ParameterPreview'
import type {
  CaseExecutionPanelProps,
  CaseExecutionRecordDetail,
  CaseRunResponse,
} from './types'

type LocatedSystemFailure = {
  record: CaseExecutionRecordDetail
  publicMessage: string
  httpStatus: number
}

/**
 * Case 执行面板：单次 JSON 参数覆盖，不解析 YAML、不覆盖 fail_fast/timeout。
 * 5xx 错误体无 record_id，需按 asset_type=case + asset_id + status=failed 定位历史。
 */
export function CaseExecutionPanel(props: CaseExecutionPanelProps) {
  return <CaseExecutionPanelReady key={`${props.projectId}:${props.caseId}:${props.env}`} {...props} />
}

function CaseExecutionPanelReady({ projectId, caseId, env, assetDefaults, caseParams, parameterContext }: CaseExecutionPanelProps) {
  const runMutation = useRunCase(projectId, caseId)
  const [runResult, setRunResult] = useState<CaseRunResponse | null>(null)
  const [submitError, setSubmitError] = useState<unknown>(null)
  const [located, setLocated] = useState<LocatedSystemFailure | null>(null)
  const [locating, setLocating] = useState(false)
  const [paramsText, setParamsText] = useState('')
  const temporary = parseTemporaryParams(paramsText)
  const submitting = runMutation.isPending || locating

  const handleRun = async () => {
    setSubmitError(null)
    setLocated(null)
    setRunResult(null)
    try {
      if ('error' in temporary) throw new Error(temporary.error)
      // 只传 env + params；禁止 fail_fast / timeout 覆盖字段
      const data = await runMutation.mutateAsync({ env, params: temporary.value })
      setRunResult(data)
    } catch (error) {
      if (error instanceof ApiHttpError && error.status >= 500) {
        setSubmitError(error)
        setLocating(true)
        try {
          const items = await listExecutionRecords(projectId, {
            asset_type: 'case',
            asset_id: caseId,
            status: 'failed',
            limit: 5,
            order_by: '-start_time',
          })
          if (items.length > 0) {
            const record = await getCaseExecutionRecord(projectId, items[0].id)
            setLocated({
              record,
              publicMessage: formatErrorMessage(error),
              httpStatus: error.status,
            })
          }
        } catch {
          // 定位失败时仍保留上方 5xx public message，不展示二次错误栈
        } finally {
          setLocating(false)
        }
        return
      }
      setSubmitError(error)
    }
  }

  return (
    <Card
      size="small"
      className="tp-pane-enter"
      title={
        <Space wrap>
          <Typography.Text>执行 Case</Typography.Text>
          <Typography.Text type="secondary" code style={{ wordBreak: 'break-all' }}>
            {caseId}
          </Typography.Text>
        </Space>
      }
      data-testid="case-execution-panel"
    >
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
        使用当前场景的资产默认值和所选环境覆盖。下方仅填写本次变化，留空沿用默认值。
      </Typography.Paragraph>

      <Typography.Text>本次场景参数（JSON 对象）</Typography.Text>
      <Input.TextArea
        aria-label="本次场景参数"
        value={paramsText}
        onChange={(event) => setParamsText(event.target.value)}
        disabled={submitting}
        placeholder='例如 {"product_keyword":"示例商品"}'
        autoSize={{ minRows: 3, maxRows: 12 }}
        style={{ margin: '8px 0', fontFamily: 'monospace' }}
      />
      <Button size="small" disabled={submitting} onClick={() => setParamsText('')}>清除本次场景输入</Button>
      {'error' in temporary ? (
        <Alert type="error" style={{ marginTop: 8 }} message={temporary.error} description="修正 JSON 后再预览和执行。" />
      ) : <ParameterPreview env={env} assetDefaults={assetDefaults} caseParams={caseParams} temporary={temporary.value} context={parameterContext} />}
      <Typography.Paragraph type="secondary">
        环境覆盖目前仍在共享配置中维护；单次输入不会保存或修改步骤。完整场景校验由运行预检完成。
      </Typography.Paragraph>

      <Space style={{ marginTop: 4 }}>
        <Button
          type="primary"
          className="tp-run-btn"
          icon={<PlayCircleOutlined />}
          loading={submitting}
          disabled={submitting || 'error' in temporary}
          onClick={() => {
            void handleRun()
          }}
          aria-label="执行 Case"
          data-testid="case-run-button"
        >
          {submitting ? (locating ? '定位历史记录…' : '执行中…') : '执行'}
        </Button>
      </Space>

      {submitError ? (
        <Alert
          type="error"
          showIcon
          role="alert"
          style={{ marginTop: 12 }}
          message={
            submitError instanceof ApiHttpError && submitError.status >= 500
              ? `系统错误（HTTP ${submitError.status}）`
              : submitError instanceof ApiHttpError && submitError.status === 422
                ? '预检失败（HTTP 422）'
                : submitError instanceof ApiParseError
                  ? '响应格式异常'
                  : '执行失败'
          }
          description={
            <div>
              <div data-testid="case-run-failure">{formatRunFailure(submitError, env)}</div>
              {submitError instanceof ApiHttpError && submitError.status >= 500 ? (
                <Typography.Paragraph type="secondary" style={{ marginBottom: 0, marginTop: 8 }}>
                  错误体不含 record_id；正在/已按 asset_type=case、本 Case ID、status=failed
                  查找最近失败记录。
                </Typography.Paragraph>
              ) : null}
            </div>
          }
        />
      ) : null}

      {located ? (
        <div className="tp-result-flash" data-testid="case-system-error-located">
          <Divider style={{ margin: '16px 0 12px' }} />
          <Typography.Title level={5} style={{ marginTop: 0 }}>
            系统错误 · 历史步骤
          </Typography.Title>
          {located.record.result ? (
            <CaseResultView
              result={located.record.result}
              recordId={located.record.id}
              locateNote={`HTTP ${located.httpStatus}：${located.publicMessage}；已定位记录 ${located.record.id}`}
            />
          ) : (
            <Alert
              type="warning"
              showIcon
              message="已定位失败记录，但 result 无法解析"
              description={`记录 ID：${located.record.id}`}
            />
          )}
        </div>
      ) : null}

      {runResult ? (
        <div
          key={runResult.record_id}
          className="tp-result-flash"
          data-testid="case-run-result-wrap"
        >
          <Divider style={{ margin: '16px 0 12px' }} />
          <Typography.Title level={5} style={{ marginTop: 0 }}>
            执行结果
          </Typography.Title>
          <Descriptions
            size="small"
            column={2}
            style={{ marginBottom: 12 }}
            data-testid="case-run-trace"
          >
            <Descriptions.Item label="操作人">{runResult.operator || '—'}</Descriptions.Item>
            <Descriptions.Item label="环境">{env}</Descriptions.Item>
            <Descriptions.Item label="Commit">
              <Typography.Text code>{shortSha(runResult.commit_sha)}</Typography.Text>
            </Descriptions.Item>
            {typeof runResult.config_revision === 'number' ? (
              <Descriptions.Item label="配置版本">{runResult.config_revision}</Descriptions.Item>
            ) : null}
          </Descriptions>
          <CaseResultView result={runResult.result} recordId={runResult.record_id} />
        </div>
      ) : null}
    </Card>
  )
}

function parseTemporaryParams(text: string): { value: Record<string, unknown> } | { error: string } {
  if (!text.trim()) return { value: {} }
  try {
    const value: unknown = JSON.parse(text)
    if (value === null || typeof value !== 'object' || Array.isArray(value)) return { error: '场景参数必须是 JSON 对象' }
    return { value: value as Record<string, unknown> }
  } catch {
    return { error: '场景参数不是合法 JSON' }
  }
}
