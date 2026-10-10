import { Alert, Button, Card, Divider, Space, Typography } from 'antd'
import { PlayCircleOutlined } from '@ant-design/icons'
import { Form } from 'antd'
import { useState } from 'react'
import {
  ApiHttpError,
  fieldErrorsFromDetail,
} from '@/shared/api/errors'
import { ErrorState, LoadingState } from '@/shared/ui/AsyncState'
import { formatErrorMessage } from '@/shared/ui/errorMessage'
import { useAssetParams, useRunAsset } from './hooks'
import { ParamForm } from './ParamForm'
import { ExecutionResultCard } from './ExecutionResultCard'
import { serializeRunParams } from './serializeParams'
import type { ApiExecutionPanelProps, RunResponse } from './types'

/**
 * 单 API 执行面板：动态参数表单 + 执行 + 结果。
 * 父级用 key 绑定 projectId:assetId，切换资产时整树重挂载以清空状态。
 */
export function ApiExecutionPanel({ projectId, assetId }: ApiExecutionPanelProps) {
  const paramsQuery = useAssetParams(projectId, assetId)

  if (paramsQuery.isLoading) {
    return <LoadingState tip="加载参数…" />
  }

  if (paramsQuery.isError) {
    return (
      <ErrorState
        error={paramsQuery.error}
        title="参数加载失败"
        onRetry={() => {
          void paramsQuery.refetch()
        }}
      />
    )
  }

  return (
    <ApiExecutionPanelReady
      projectId={projectId}
      assetId={assetId}
      params={paramsQuery.data?.params ?? []}
    />
  )
}

function ApiExecutionPanelReady({
  projectId,
  assetId,
  params,
}: ApiExecutionPanelProps & { params: NonNullable<ReturnType<typeof useAssetParams>['data']>['params'] }) {
  // Form 实例仅在已挂载 ParamForm 的子树中创建，避免 useForm disconnected 警告
  const [form] = Form.useForm<Record<string, unknown>>()
  const [runResult, setRunResult] = useState<RunResponse | null>(null)
  const [submitError, setSubmitError] = useState<unknown>(null)
  const runMutation = useRunAsset(projectId, assetId)
  const submitting = runMutation.isPending

  const handleRun = async () => {
    setSubmitError(null)
    try {
      const values = await form.validateFields()
      const serialized = serializeRunParams(params, values)
      const data = await runMutation.mutateAsync({ params: serialized })
      // HTTP 200 的 success / failed 都当可查看结果，不进网络错误态
      setRunResult(data)
    } catch (error) {
      if (error && typeof error === 'object' && 'errorFields' in error) {
        return
      }
      if (error instanceof ApiHttpError) {
        const fieldErrors = fieldErrorsFromDetail(error.detail)
        const entries = Object.entries(fieldErrors)
        if (entries.length > 0) {
          form.setFields(
            entries.map(([name, message]) => ({
              name,
              errors: [message],
            })),
          )
        }
        setSubmitError(error)
        setRunResult(null)
        return
      }
      setSubmitError(error)
      setRunResult(null)
    }
  }

  return (
    <Card
      size="small"
      className="tp-pane-enter"
      title={
        <Space>
          <Typography.Text>执行</Typography.Text>
          <Typography.Text type="secondary" code>
            {assetId}
          </Typography.Text>
        </Space>
      }
      data-testid="api-execution-panel"
    >
      <ParamForm form={form} params={params} disabled={submitting} />

      <Space style={{ marginTop: 8 }}>
        <Button
          type="primary"
          className="tp-run-btn"
          icon={<PlayCircleOutlined />}
          loading={submitting}
          disabled={submitting}
          onClick={() => {
            void handleRun()
          }}
          aria-label="执行 API"
        >
          {submitting ? '执行中…' : '执行'}
        </Button>
      </Space>

      {submitError ? (
        <Alert
          type="error"
          showIcon
          role="alert"
          style={{ marginTop: 12 }}
          message="执行失败"
          description={formatErrorMessage(submitError)}
        />
      ) : null}

      {runResult ? (
        <div
          key={runResult.record_id}
          className="tp-result-flash"
          data-testid="execution-result-wrap"
        >
          <Divider style={{ margin: '16px 0 12px' }} />
          <Typography.Title level={5} style={{ marginTop: 0 }}>
            执行结果
          </Typography.Title>
          <ExecutionResultCard result={runResult} />
        </div>
      ) : null}
    </Card>
  )
}
