import { Alert, Button, Card, Divider, Input, Radio, Select, Space, Tag, Typography } from 'antd'
import { PlayCircleOutlined } from '@ant-design/icons'
import { Form } from 'antd'
import { useState } from 'react'
import {
  ApiHttpError,
  fieldErrorsFromDetail,
} from '@/shared/api/errors'
import { ErrorState, LoadingState } from '@/shared/ui/AsyncState'
import { formatRunFailure } from './accountFailure'
import { useAssetParams, useRunAsset } from './hooks'
import { ParamForm } from './ParamForm'
import { ParameterPreview } from './ParameterPreview'
import { ApiRunResult } from './ApiRunResult'
import { JsonBlock } from './JsonBlock'
import { serializeRunParams } from './serializeParams'
import type { ApiExecutionPanelProps, RunResponse } from './types'
import { useAccounts } from '@/features/environments/hooks'

/**
 * 单 API 执行面板：动态参数表单 + 执行 + 结果。
 * 父级用 key 绑定 projectId:assetId，切换资产时整树重挂载以清空状态。
 */
export function ApiExecutionPanel({
  projectId,
  assetId,
  env,
  caseParams,
  requestDefinition,
  runDisabled,
  parameterContext,
}: ApiExecutionPanelProps) {
  const paramsQuery = useAssetParams(projectId, assetId, parameterContext?.commit_sha)

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
      env={env}
      caseParams={caseParams}
      requestDefinition={requestDefinition}
      runDisabled={runDisabled}
      key={`${projectId}:${assetId}:${env}`}
      params={paramsQuery.data?.params ?? []}
      assetDefaults={paramsQuery.data?.asset_defaults}
      parameterContext={parameterContext}
    />
  )
}

function ApiExecutionPanelReady({
  projectId,
  assetId,
  env,
  caseParams,
  params,
  requestDefinition,
  runDisabled,
  assetDefaults,
  parameterContext,
}: ApiExecutionPanelProps & {
  params: NonNullable<ReturnType<typeof useAssetParams>['data']>['params']
  assetDefaults?: Record<string, unknown>
}) {
  // Form 实例仅在已挂载 ParamForm 的子树中创建，避免 useForm disconnected 警告
  const [form] = Form.useForm<Record<string, unknown>>()
  const values = Form.useWatch([], form) ?? {}
  const [runResult, setRunResult] = useState<RunResponse | null>(null)
  const [submitError, setSubmitError] = useState<unknown>(null)
  const [editBody, setEditBody] = useState(false)
  const [identity, setIdentity] = useState<string | undefined>()
  const accounts = useAccounts(projectId, env)
  const bodyType = String(requestDefinition?.type ?? 'json')
  const bodyLabel = ({ query: 'Query 参数', json: 'JSON 请求体', form: 'Form 表单', raw: 'Raw 文本' } as Record<string, string>)[bodyType] ?? bodyType
  const rawBody = bodyType === 'raw'
  const originalBody = rawBody
    ? String(requestDefinition?.body ?? '')
    : JSON.stringify(requestDefinition && 'body' in requestDefinition ? requestDefinition.body : {}, null, 2)
  const [bodyText, setBodyText] = useState(originalBody)
  const runMutation = useRunAsset(projectId, assetId)
  const submitting = runMutation.isPending

  const handleRun = async () => {
    if (runDisabled) return
    setSubmitError(null)
    setRunResult(null)
    try {
      const values = editBody ? {} : await form.validateFields()
      const serialized = serializeRunParams(params, values, true)
      let body: unknown
      if (editBody) {
        try {
          body = rawBody ? bodyText : JSON.parse(bodyText)
        } catch {
          throw new Error('临时请求内容不是合法 JSON')
        }
        if (['query', 'form'].includes(bodyType) && (
          body === null || typeof body !== 'object' || Array.isArray(body)
          || Object.values(body).some((value) => value !== null && !['string', 'number', 'boolean'].includes(typeof value))
        )) {
          throw new Error('Query/Form 临时内容必须是一层标量键值对象')
        }
      }
      // Phase 4.0：运行体必填 env（与项目环境下拉一致）
      const data = await runMutation.mutateAsync({
        env,
        params: serialized,
        ...(identity ? { identity } : {}),
        ...(editBody ? { request_override: { body } } : {}),
      })
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
          <Typography.Text>请求</Typography.Text>
          <Tag>{bodyLabel}</Tag>
          <Typography.Text type="secondary" code>
            {assetId}
          </Typography.Text>
        </Space>
      }
      data-testid="api-execution-panel"
    >
      <div style={{ marginBottom: 12 }}>
        <Typography.Text>调用账号 </Typography.Text>
        <Select
          aria-label="调用账号" placeholder="选择本次调用账号" allowClear
          style={{ minWidth: 240, maxWidth: '100%' }} value={identity}
          loading={accounts.isLoading} disabled={submitting}
          onChange={setIdentity}
          options={[
            { value: 'none', label: '匿名调用' },
            ...(accounts.data ?? []).map((account) => ({
              value: account.account_name,
              label: `${account.display_name ?? account.account_name}${account.login_username ? ` · ${account.login_username}` : ''}`,
              disabled: !account.enabled,
            })),
          ]}
        />
        {accounts.isError ? <Alert type="error" message="账号列表加载失败" action={<Button size="small" onClick={() => { void accounts.refetch() }}>重试</Button>} /> : null}
      </div>
      {requestDefinition ? (
        <Radio.Group
          aria-label="请求编辑方式"
          value={editBody}
          disabled={submitting}
          onChange={(event) => setEditBody(event.target.value === true)}
          options={[
            { label: '使用 YAML 模板', value: false },
            { label: '编辑完整请求内容', value: true },
          ]}
          style={{ marginBottom: 12 }}
        />
      ) : null}
      {requestDefinition && !editBody ? <div style={{ marginBottom: 12 }}>
        <Typography.Text type="secondary">YAML 模板 · 填写下方模板参数后运行</Typography.Text>
        <JsonBlock value={rawBody ? originalBody : requestDefinition.body} aria-label="请求模板" />
      </div> : null}
      <div style={{ display: editBody ? 'none' : undefined }}>
        <ParamForm form={form} params={params} disabled={submitting} caseParams={caseParams} assetDefaults={assetDefaults} context={parameterContext} />
        <Button size="small" disabled={submitting} onClick={() => form.resetFields()}>清除本次输入</Button>
        <ParameterPreview env={env} params={params} assetDefaults={assetDefaults} caseParams={caseParams} temporary={serializeRunParams(params, values)} context={parameterContext} />
      </div>
      {editBody ? (
        <div>
          <Typography.Paragraph>
            {bodyLabel} · 临时调试
            {rawBody ? '（原始文本）' : '（JSON）'}
          </Typography.Paragraph>
          <Input.TextArea
            aria-label="临时请求内容"
            value={bodyText}
            onChange={(event) => setBodyText(event.target.value)}
            disabled={submitting}
            autoSize={{ minRows: 8, maxRows: 24 }}
            style={{ fontFamily: 'monospace' }}
          />
          <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
            可以新增、删除或修改任意字段。填写实际请求内容后原样发送，仅本次运行生效。
            此模式不使用上方模板参数与默认值预览。
          </Typography.Paragraph>
          <Button size="small" disabled={submitting} onClick={() => setBodyText(originalBody)}>
            从 YAML 恢复
          </Button>
        </div>
      ) : null}

      <Space style={{ marginTop: 8 }}>
        <Button
          type="primary"
          className="tp-run-btn"
          icon={<PlayCircleOutlined />}
          loading={submitting}
          disabled={submitting || runDisabled}
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
          description={formatRunFailure(submitError, env)}
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
          <ApiRunResult result={runResult} env={env} />
        </div>
      ) : null}
    </Card>
  )
}
