import { Alert, Button, Input, Modal, Space, Typography } from 'antd'
import { useState, type ReactNode } from 'react'
import { ErrorState, LoadingState } from '@/shared/ui/AsyncState'
import { formatErrorMessage } from '@/shared/ui/errorMessage'
import { ApiHttpError } from '@/shared/api/errors'
import { useParameterContext, useSaveParameterSet } from './hooks'
import type { ParameterContext } from './types'

type Scope = 'asset_default' | 'environment_override'
type Props = {
  projectId: string; assetType: 'api' | 'case'; assetId: string; env: string; commit: string
  children: (context: ParameterContext | undefined) => ReactNode
}

export function StoredParameters(props: Props) {
  const query = useParameterContext(props.projectId, props.assetType, props.assetId, props.env, props.commit)
  const [editing, setEditing] = useState<{ scope: Scope; context: ParameterContext } | null>(null)
  if (query.isPending) return <LoadingState tip="加载已保存参数…" />
  // 尚未升级的本地服务没有该路由；保留原调试入口，明确提示保存不可用。
  // 已存在路由的资产／环境 404、其它读取错误均不能回退忽略已保存值。
  if (query.isError && query.error instanceof ApiHttpError && query.error.status === 404 && query.error.detail === 'Not Found') {
    return <><Alert type="info" message="当前服务尚未启用参数保存；可继续使用已有默认值和本次输入。" />{props.children(undefined)}</>
  }
  if (query.isError) return <ErrorState title="参数配置加载失败" error={query.error} onRetry={() => { void query.refetch() }} />
  if (query.data.commit_sha !== props.commit) return <Alert type="warning" message="资产版本已更新，请刷新工作区后运行或维护参数" />
  const context = query.data
  return <>
    <div className="tp-surface" style={{ padding: 12 }}>
      <Space wrap>
        <Typography.Text>当前资产参数</Typography.Text>
        <Button size="small" onClick={() => setEditing({ scope: 'asset_default', context })}>维护默认值</Button>
        <Button size="small" onClick={() => setEditing({ scope: 'environment_override', context })}>维护 {props.env} 覆盖</Button>
        <Button size="small" onClick={() => { void query.refetch() }}>刷新参数</Button>
      </Space>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0, marginTop: 8 }}>
        仅影响当前平台、项目和资产；默认值适用于各环境，环境覆盖仅适用于 {props.env}。兼容共享环境值继续生效。
      </Typography.Paragraph>
    </div>
    {props.children(context)}
    {editing ? <ParameterEditor key={`${editing.scope}:${editing.context.env}`} {...props} scope={editing.scope} context={editing.context} onClose={() => setEditing(null)} /> : null}
  </>
}

function ParameterEditor({ projectId, assetType, assetId, env, scope, context, onClose }: Props & {
  scope: Scope; context: ParameterContext; onClose: () => void
}) {
  const [text, setText] = useState(JSON.stringify(context[scope].values, null, 2))
  const [error, setError] = useState<unknown>(null)
  const save = useSaveParameterSet(projectId, assetType, assetId, env)
  const submit = async () => {
    setError(null)
    try {
      const value: unknown = JSON.parse(text)
      if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('请输入 JSON 对象')
      await save.mutateAsync({ scope, values: value as Record<string, unknown>, revision: context[scope].revision, commit_sha: context.commit_sha })
      onClose()
    } catch (cause) { setError(cause) }
  }
  return <Modal open title={scope === 'asset_default' ? '维护当前资产默认值' : `维护当前资产 · ${env} 覆盖`}
    width={760} onCancel={onClose} maskClosable={false} closable={!save.isPending} keyboard={!save.isPending}
    footer={<Space><Button disabled={save.isPending} onClick={onClose}>取消</Button><Button type="primary" loading={save.isPending} onClick={() => { void submit() }}>保存参数</Button></Space>}>
    <Typography.Paragraph>{projectId} · {assetId}</Typography.Paragraph>
    <Typography.Paragraph type="secondary">
      仅保存普通业务参数，不填写密码、Cookie 或令牌。此 JSON 整份替换本层；删除键或保存 {'{}'} 恢复下层值，null 是实际值。不会写回 Git 或修改共享配置。
    </Typography.Paragraph>
    <Input.TextArea aria-label="持久化参数 JSON" value={text} onChange={(event) => setText(event.target.value)} disabled={save.isPending} autoSize={{ minRows: 8, maxRows: 20 }} style={{ fontFamily: 'monospace' }} />
    {error ? <Alert style={{ marginTop: 12 }} type="error" message={formatErrorMessage(error)} description="草稿已保留。版本冲突时先取消并刷新参数，核对最新值后重新编辑；不会自动覆盖。" /> : null}
  </Modal>
}
