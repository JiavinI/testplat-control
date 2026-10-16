import { Alert, Button, Input, Modal, Space, Switch, Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useState } from 'react'
import { formatErrorMessage } from '@/shared/ui/errorMessage'
import { ErrorState, LoadingState } from '@/shared/ui/AsyncState'
import { getEnvironment } from './api'
import {
  useCreateEnvironment,
  useEnvironments,
  useUpdateEnvironment,
} from './hooks'
import {
  collectHosts,
  formatCaseParams,
  hostsToRows,
  parseCaseParamsText,
  parseTimeoutText,
  validateEnvName,
  type HostRow,
} from './names'
import { isRevisionConflict, REVISION_CONFLICT_MESSAGE } from './revision'
import type { ProjectEnvironment } from './types'

interface EnvDraft {
  mode: 'create' | 'edit'
  env: string
  enabled: boolean
  timeoutText: string
  caseParamsText: string
  hosts: HostRow[]
  revision: number | null
}

function blankDraft(): EnvDraft {
  return {
    mode: 'create',
    env: '',
    enabled: true,
    timeoutText: '',
    caseParamsText: '',
    hosts: [{ name: '', url: '' }],
    revision: null,
  }
}

function draftFromEnvironment(row: ProjectEnvironment): EnvDraft {
  return {
    mode: 'edit',
    env: row.env,
    enabled: row.enabled,
    timeoutText: row.timeout_seconds === null ? '' : String(row.timeout_seconds),
    caseParamsText: formatCaseParams(row.case_params),
    hosts: hostsToRows(row.api_hosts),
    revision: row.revision,
  }
}

/**
 * 环境新增、编辑、停用。保存带 revision；409 只提示刷新，不自动用旧表单覆盖。
 * 不用 Monaco、继承树或拖拽编辑器。
 */
export function EnvironmentSection({ projectId }: { projectId: string }) {
  const listQuery = useEnvironments(projectId)
  const createMutation = useCreateEnvironment(projectId)
  const updateMutation = useUpdateEnvironment(projectId)
  const [draft, setDraft] = useState<EnvDraft | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [conflict, setConflict] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [listError, setListError] = useState<string | null>(null)
  const saving = createMutation.isPending || updateMutation.isPending

  const save = async () => {
    if (!draft) {
      return
    }
    setFormError(null)
    const envName = draft.env.trim()
    if (draft.mode === 'create') {
      const nameError = validateEnvName(envName)
      if (nameError) {
        setFormError(nameError)
        return
      }
    }
    const hosts = collectHosts(draft.hosts)
    if ('error' in hosts) {
      setFormError(hosts.error)
      return
    }
    const params = parseCaseParamsText(draft.caseParamsText)
    if ('error' in params) {
      setFormError(params.error)
      return
    }
    const timeout = parseTimeoutText(draft.timeoutText)
    if ('error' in timeout) {
      setFormError(timeout.error)
      return
    }
    const body = {
      api_hosts: hosts.hosts,
      timeout_seconds: timeout.value,
      case_params: params.value,
      enabled: draft.enabled,
    }
    try {
      if (draft.mode === 'create') {
        await createMutation.mutateAsync({ env: envName, ...body })
      } else {
        if (draft.revision === null) {
          setFormError('缺少配置版本，请刷新后再保存')
          return
        }
        await updateMutation.mutateAsync({
          env: draft.env,
          body: { revision: draft.revision, ...body },
        })
      }
      setDraft(null)
      setConflict(false)
    } catch (error) {
      if (isRevisionConflict(error)) {
        setConflict(true)
        setFormError(REVISION_CONFLICT_MESSAGE)
        return
      }
      setFormError(formatErrorMessage(error))
    }
  }

  const refresh = async () => {
    if (!draft || draft.mode !== 'edit') {
      return
    }
    setRefreshing(true)
    try {
      const fresh = await getEnvironment(projectId, draft.env)
      setDraft(draftFromEnvironment(fresh))
      setConflict(false)
      setFormError(null)
    } catch (error) {
      setFormError(formatErrorMessage(error))
    } finally {
      setRefreshing(false)
    }
  }

  const toggleEnabled = async (row: ProjectEnvironment) => {
    setListError(null)
    try {
      await updateMutation.mutateAsync({
        env: row.env,
        body: { revision: row.revision, enabled: !row.enabled },
      })
    } catch (error) {
      if (isRevisionConflict(error)) {
        setListError(REVISION_CONFLICT_MESSAGE)
        return
      }
      setListError(formatErrorMessage(error))
    }
  }

  if (listQuery.isLoading) {
    return <LoadingState tip="加载环境…" />
  }
  if (listQuery.isError) {
    return (
      <ErrorState
        error={listQuery.error}
        title="环境加载失败"
        onRetry={() => {
          void listQuery.refetch()
        }}
      />
    )
  }

  const rows = listQuery.data ?? []
  const columns: ColumnsType<ProjectEnvironment> = [
    { title: '环境名', dataIndex: 'env', key: 'env' },
    {
      title: '启用',
      dataIndex: 'enabled',
      key: 'enabled',
      render: (value: boolean) => (value ? '是' : '否'),
    },
    {
      title: '超时',
      dataIndex: 'timeout_seconds',
      key: 'timeout_seconds',
      render: (value: number | null) => (value === null ? '默认 30' : String(value)),
    },
    { title: '版本', dataIndex: 'revision', key: 'revision' },
    {
      title: '更新人',
      dataIndex: 'updated_by',
      key: 'updated_by',
      render: (value: string | null) => value || '—',
    },
    {
      title: '操作',
      key: 'actions',
      render: (_value, row) => (
        <Space>
          <Button
            size="small"
            data-testid={`env-edit-${row.env}`}
            onClick={() => {
              setFormError(null)
              setConflict(false)
              setDraft(draftFromEnvironment(row))
            }}
          >
            编辑
          </Button>
          <Button
            size="small"
            data-testid={`env-toggle-${row.env}`}
            onClick={() => {
              void toggleEnabled(row)
            }}
          >
            {row.enabled ? '停用' : '启用'}
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div data-testid="environment-manager">
      <Space style={{ marginBottom: 12 }}>
        <Button
          type="primary"
          data-testid="env-create-open"
          onClick={() => {
            setFormError(null)
            setConflict(false)
            setDraft(blankDraft())
          }}
        >
          新增环境
        </Button>
      </Space>
      {listError ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message={listError}
          data-testid="env-list-error"
        />
      ) : null}
      <Table
        size="small"
        rowKey="env"
        columns={columns}
        dataSource={rows}
        pagination={false}
        data-testid="environment-table"
        locale={{ emptyText: '还没有环境' }}
      />
      <Modal
        title={draft?.mode === 'edit' ? `编辑环境 ${draft.env}` : '新增环境'}
        open={draft !== null}
        onCancel={() => {
          setDraft(null)
          setConflict(false)
        }}
        destroyOnClose
        footer={
          <Space>
            <Button
              onClick={() => {
                setDraft(null)
                setConflict(false)
              }}
            >
              取消
            </Button>
            <Button
              type="primary"
              loading={saving}
              data-testid="env-save"
              onClick={() => {
                void save()
              }}
            >
              保存环境
            </Button>
          </Space>
        }
      >
        {draft ? (
          <EnvironmentForm
            draft={draft}
            conflict={conflict}
            refreshing={refreshing}
            formError={formError}
            onChange={setDraft}
            onRefresh={() => {
              void refresh()
            }}
          />
        ) : null}
      </Modal>
    </div>
  )
}

function EnvironmentForm({
  draft,
  conflict,
  refreshing,
  formError,
  onChange,
  onRefresh,
}: {
  draft: EnvDraft
  conflict: boolean
  refreshing: boolean
  formError: string | null
  onChange: (next: EnvDraft) => void
  onRefresh: () => void
}) {
  return (
    <div data-testid="env-editor">
      {conflict ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          data-testid="revision-conflict"
          message={REVISION_CONFLICT_MESSAGE}
          description="刷新后请再保存。未保存的修改会被服务器上的版本替换。"
          action={
            <Button
              size="small"
              data-testid="revision-refresh"
              loading={refreshing}
              onClick={onRefresh}
            >
              刷新
            </Button>
          }
        />
      ) : null}
      {formError && !conflict ? (
        <Alert type="error" showIcon style={{ marginBottom: 12 }} message={formError} />
      ) : null}
      {draft.mode === 'edit' && draft.revision !== null ? (
        <Typography.Paragraph data-testid="editing-revision" style={{ marginBottom: 8 }}>
          版本 {draft.revision}
        </Typography.Paragraph>
      ) : null}
      <Typography.Text>环境名</Typography.Text>
      <Input
        aria-label="环境名"
        style={{ margin: '4px 0 12px' }}
        value={draft.env}
        disabled={draft.mode === 'edit'}
        onChange={(event) => onChange({ ...draft, env: event.target.value })}
      />
      <Space style={{ marginBottom: 12 }}>
        <span>启用</span>
        <Switch
          aria-label="启用环境"
          checked={draft.enabled}
          onChange={(checked) => onChange({ ...draft, enabled: checked })}
        />
      </Space>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
        逻辑服务名与地址。留空表示该环境不配置 host。
      </Typography.Paragraph>
      {draft.hosts.map((row, index) => (
        <Space key={index} style={{ display: 'flex', marginBottom: 8 }} align="baseline">
          <Input
            aria-label={`服务名 ${index + 1}`}
            placeholder="gsb"
            value={row.name}
            onChange={(event) => {
              const hosts = draft.hosts.slice()
              hosts[index] = { ...row, name: event.target.value }
              onChange({ ...draft, hosts })
            }}
          />
          <Input
            aria-label={`地址 ${index + 1}`}
            placeholder="https://example.invalid"
            value={row.url}
            onChange={(event) => {
              const hosts = draft.hosts.slice()
              hosts[index] = { ...row, url: event.target.value }
              onChange({ ...draft, hosts })
            }}
          />
          <Button
            aria-label={`删除服务地址 ${index + 1}`}
            onClick={() => {
              const hosts = draft.hosts.filter((_, itemIndex) => itemIndex !== index)
              onChange({
                ...draft,
                hosts: hosts.length > 0 ? hosts : [{ name: '', url: '' }],
              })
            }}
          >
            删除
          </Button>
        </Space>
      ))}
      <Button
        style={{ marginBottom: 12 }}
        onClick={() => onChange({ ...draft, hosts: [...draft.hosts, { name: '', url: '' }] })}
      >
        添加服务地址
      </Button>
      <Typography.Text>超时（秒）</Typography.Text>
      <Input
        aria-label="超时（秒）"
        style={{ margin: '4px 0 12px' }}
        value={draft.timeoutText}
        placeholder="留空使用默认 30 秒"
        onChange={(event) => onChange({ ...draft, timeoutText: event.target.value })}
      />
      <Typography.Text>参数默认值</Typography.Text>
      <Input.TextArea
        aria-label="参数默认值"
        style={{ marginTop: 4 }}
        rows={4}
        value={draft.caseParamsText}
        placeholder='{"product_keyword":"demo"}'
        onChange={(event) => onChange({ ...draft, caseParamsText: event.target.value })}
      />
      <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
        JSON 对象，只放非秘密业务默认值。
      </Typography.Paragraph>
    </div>
  )
}
