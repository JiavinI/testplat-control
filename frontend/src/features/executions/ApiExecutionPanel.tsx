import { Alert, Button, Card, Divider, Space, Typography } from 'antd'
import { PlayCircleOutlined } from '@ant-design/icons'
import { Form } from 'antd'
import { useEffect, useState } from 'react'
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
 * 由 Agent 4 在工作台挂载；切换 asset 时通过 effect 清空参数/错误/结果。
 */
export function ApiExecutionPanel({ projectId, assetId }: ApiExecutionPanelProps) {
  const [form] = Form.useForm<Record<string, unknown>>()
  const [runResult, setRunResult] = useState<RunResponse | null>(null)
  const [submitError, setSubmitError] = useState<unknown>(null)

  const paramsQuery = useAssetParams(projectId, assetId)
  const runMutation = useRunAsset(projectId, assetId)

  // 切换资产时清空旧参数、旧错误与旧结果，避免跨资产污染
  useEffect(() => {
    form.resetFields()
    setRunResult(null)
    setSubmitError(null)
    runMutation.reset()
    // 仅跟踪身份变化；mutation 对象本身每次渲染不同
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 有意只依赖 projectId/assetId
  }, [projectId, assetId, form])

  const submitting = runMutation.isPending

  const handleRun = async () => {
    setSubmitError(null)
    const paramDefs = paramsQuery.data?.params ?? []
    try {
      const values = await form.validateFields()
      const params = serializeRunParams(paramDefs, values)
      const data = await runMutation.mutateAsync({ params })
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
        // 字符串 detail（如 missing required param）展示在表单上方
        setSubmitError(error)
        setRunResult(null)
        return
      }
      setSubmitError(error)
      setRunResult(null)
    }
  }

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

  const params = paramsQuery.data?.params ?? []

  return (
    <Card
      size="small"
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
        <>
          <Divider style={{ margin: '16px 0 12px' }} />
          <Typography.Title level={5} style={{ marginTop: 0 }}>
            执行结果
          </Typography.Title>
          <ExecutionResultCard result={runResult} />
        </>
      ) : null}
    </Card>
  )
}
